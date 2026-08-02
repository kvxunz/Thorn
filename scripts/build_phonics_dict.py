# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the bundled phonics dictionary (Resources/phonics-en.tsv).

One-time offline step, run by the developer:

    uv run --script scripts/build_phonics_dict.py

Pipeline: CMUdict 0.7b -> embedded m2m-style EM grapheme-phoneme aligner
(forward-backward DP, no third-party deps) -> maximal-onset syllabification
-> ARPAbet-to-IPA -> sorted TSV for byte-wise binary search at runtime.

Output line format (fields separated by tabs):

    word<TAB>ipa<TAB>syllables

where syllables look like  [a:ə].ˈ[b:b|ou:aʊ|t:t]  — syllables joined by
".", each optionally prefixed with the IPA stress mark (ˈ primary,
ˌ secondary), chunks joined by "|", one chunk being "grapheme:ipa" (ipa is
empty for silent letters merged into a neighbor chunk... those never survive
as standalone chunks; every chunk keeps its own letters).

Integrity invariant (entries failing it are dropped, project rule: a wrong
tree is worse than no tree): the concatenation of all chunk graphemes must
equal the word byte-for-byte, and every source phoneme must appear in
exactly one chunk, in order.
"""
import argparse
import math
import re
import sys
import time
import urllib.request
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

CMUDICT_URL = "https://raw.githubusercontent.com/Alexir/CMUdict/master/cmudict-0.7b"
CACHE = Path.home() / ".cache" / "thorn" / "cmudict-0.7b"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "Resources" / "phonics-en.tsv"

# Words: plain letters plus internal apostrophe/hyphen ("don't", "mother-in-law").
WORD_RE = re.compile(r"[A-Z][A-Z'\-]*")

VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
    "IH", "IY", "OW", "OY", "UH", "UW",
}

# ARPAbet -> IPA (General American). Stressed/unstressed splits where the
# teaching convention differs (AH1=ʌ vs AH0=ə, ER1=ɜːr vs ER0=ər).
IPA = {
    "AA": "ɑː", "AE": "æ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "e", "EY": "eɪ",
    "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "iː", "JH": "dʒ",
    "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "OW": "oʊ",
    "OY": "ɔɪ", "P": "p", "R": "r", "S": "s", "SH": "ʃ", "T": "t",
    "TH": "θ", "UH": "ʊ", "UW": "uː", "V": "v", "W": "w", "Y": "j",
    "Z": "z", "ZH": "ʒ",
}


def phone_ipa(stressed: str) -> str:
    base = stressed.rstrip("012")
    stress = stressed[len(base):]
    if base == "AH":
        return "ə" if stress == "0" else "ʌ"
    if base == "ER":
        return "ər" if stress == "0" else "ɜːr"
    return IPA[base]


# Legal English onsets over base ARPAbet phones (Kyle Gorman's syllabify list,
# trimmed to clusters that occur in CMUdict). Used by maximal-onset splitting.
ONSETS = {
    ("P",), ("T",), ("K",), ("B",), ("D",), ("G",), ("F",), ("V",),
    ("TH",), ("DH",), ("S",), ("Z",), ("SH",), ("CH",), ("JH",), ("M",),
    ("N",), ("R",), ("L",), ("HH",), ("W",), ("Y",), ("ZH",),
    ("P", "R"), ("T", "R"), ("K", "R"), ("B", "R"), ("D", "R"), ("G", "R"),
    ("F", "R"), ("TH", "R"), ("SH", "R"),
    ("P", "L"), ("K", "L"), ("B", "L"), ("G", "L"), ("F", "L"), ("S", "L"),
    ("T", "W"), ("K", "W"), ("D", "W"), ("S", "W"), ("TH", "W"), ("G", "W"),
    ("S", "P"), ("S", "T"), ("S", "K"), ("S", "M"), ("S", "N"), ("S", "F"),
    ("P", "Y"), ("K", "Y"), ("B", "Y"), ("F", "Y"), ("M", "Y"), ("V", "Y"),
    ("H", "Y"), ("HH", "Y"), ("G", "Y"), ("N", "Y"), ("T", "Y"), ("D", "Y"),
    ("L", "Y"), ("S", "Y"), ("Z", "Y"), ("TH", "Y"),
    ("S", "P", "R"), ("S", "P", "L"), ("S", "T", "R"), ("S", "K", "R"),
    ("S", "K", "W"), ("S", "K", "Y"), ("S", "P", "Y"), ("S", "T", "Y"),
}
MAX_ONSET = 3


# --------------------------------------------------------------- EM aligner
#
# Many-to-many alignment in the style of Jiampojamarn & Kondrak's m2m-aligner:
# units are (grapheme substring, phone tuple). Joint-normalized EM prefers
# bigger units (fewer probability factors), which produces non-teaching
# chunks like "ab":AH B, so the unit shapes are deliberately narrow:
#   1-2 letters -> 1 phone   (digraphs: th -> TH, ea -> IY)
#   1 letter    -> 2 phones  (x -> K S, u -> Y UW, o -> W AH)
#   1 letter    -> silence   (magic-e, gh; merged into a neighbor afterwards)
# Longer teaching graphemes ("igh", "ough") emerge from the silent-letter
# merge after Viterbi decoding.


def unit_moves(letters: str, phones: tuple, i: int, j: int):
    """Yield (di, dj, unit_key) moves available from DP state (i, j)."""
    L, P = len(letters), len(phones)
    if i < L:
        yield 1, 0, (letters[i], "")  # silent letter
        if j < P:
            yield 1, 1, (letters[i], phones[j])
            if i + 2 <= L:
                yield 2, 1, (letters[i:i + 2], phones[j])
            if j + 2 <= P:
                yield 1, 2, (letters[i], " ".join(phones[j:j + 2]))


def em_align(entries, max_iterations=12, tolerance=1e-4, log=print):
    """entries: list of (word_letters, base_phones tuple). Returns unit probs."""
    prob = defaultdict(lambda: 1.0)
    previous_ll = None
    for iteration in range(1, max_iterations + 1):
        started = time.time()
        counts = defaultdict(float)
        log_likelihood = 0.0
        aligned = 0
        for letters, phones in entries:
            L, P = len(letters), len(phones)
            fwd = [[0.0] * (P + 1) for _ in range(L + 1)]
            fwd[0][0] = 1.0
            for i in range(L + 1):
                row = fwd[i]
                for j in range(P + 1):
                    v = row[j]
                    if v == 0.0:
                        continue
                    for di, dj, key in unit_moves(letters, phones, i, j):
                        fwd[i + di][j + dj] += v * prob[key]
            total = fwd[L][P]
            if total <= 0.0:
                continue
            aligned += 1
            log_likelihood += math.log(total)
            bwd = [[0.0] * (P + 1) for _ in range(L + 1)]
            bwd[L][P] = 1.0
            for i in range(L, -1, -1):
                for j in range(P, -1, -1):
                    if fwd[i][j] == 0.0:
                        continue
                    for di, dj, key in unit_moves(letters, phones, i, j):
                        back = bwd[i + di][j + dj]
                        if back == 0.0:
                            continue
                        p = prob[key]
                        bwd[i][j] += p * back
                        counts[key] += fwd[i][j] * p * back / total
        mass = sum(counts.values())
        prob = defaultdict(float, {k: v / mass for k, v in counts.items()})
        log(f"  EM iter {iteration}: ll={log_likelihood:.0f} "
            f"aligned={aligned}/{len(entries)} ({time.time() - started:.1f}s)")
        if (previous_ll is not None
                and previous_ll != 0
                and abs(log_likelihood - previous_ll) / abs(previous_ll) < tolerance):
            break
        previous_ll = log_likelihood
    return prob


def viterbi(letters: str, phones: tuple, prob):
    """Best alignment as a list of (grapheme, phone_start, phone_end)."""
    L, P = len(letters), len(phones)
    best = [[0.0] * (P + 1) for _ in range(L + 1)]
    back = [[None] * (P + 1) for _ in range(L + 1)]
    best[0][0] = 1.0
    for i in range(L + 1):
        for j in range(P + 1):
            v = best[i][j]
            if v == 0.0:
                continue
            for di, dj, key in unit_moves(letters, phones, i, j):
                p = prob[key]
                if p <= 0.0:
                    continue
                score = v * p
                if score > best[i + di][j + dj]:
                    best[i + di][j + dj] = score
                    back[i + di][j + dj] = (i, j, di, dj)
    if best[L][P] <= 0.0:
        return None
    units = []
    i, j = L, P
    while (i, j) != (0, 0):
        pi, pj, di, dj = back[i][j]
        units.append((letters[pi:pi + di], pj, pj + dj))
        i, j = pi, pj
    units.reverse()
    return units


def merge_silent(units):
    """Silent-letter units join the preceding chunk (magic-e, 'ough' tails,
    doubled consonants); a leading silent run joins the following chunk."""
    merged = []
    pending = ""
    for grapheme, p0, p1 in units:
        if p0 == p1:  # silent
            if merged:
                g, q0, q1 = merged[-1]
                merged[-1] = (g + grapheme, q0, q1)
            else:
                pending += grapheme
        else:
            merged.append((pending + grapheme, p0, p1))
            pending = ""
    if pending:  # entire word silent — caller drops it
        return None
    return merged


# ---------------------------------------------------------- syllabification

def syllabify(stressed: tuple):
    """Maximal-onset syllable index for each phone. Returns (indices, stresses)
    where stresses[k] is '', 'ˈ' or 'ˌ' for syllable k."""
    bases = [p.rstrip("012") for p in stressed]
    nuclei = [i for i, b in enumerate(bases) if b in VOWELS]
    if not nuclei:
        return [0] * len(stressed), [""]
    boundaries = [0]
    for prev, cur in pairwise(nuclei):
        cluster_start, cluster_end = prev + 1, cur  # consonants in between
        onset_start = cluster_end
        for take in range(min(MAX_ONSET, cluster_end - cluster_start), 0, -1):
            if tuple(bases[cluster_end - take:cluster_end]) in ONSETS:
                onset_start = cluster_end - take
                break
        boundaries.append(onset_start)
    indices = []
    syllable = 0
    for i in range(len(stressed)):
        while syllable + 1 < len(boundaries) and i >= boundaries[syllable + 1]:
            syllable += 1
        indices.append(syllable)
    stresses = [""] * len(boundaries)
    for i in nuclei:
        digit = stressed[i][-1] if stressed[i][-1] in "012" else ""
        k = indices[i]
        if digit == "1":
            stresses[k] = "ˈ"
        elif digit == "2" and not stresses[k]:
            stresses[k] = "ˌ"
    return indices, stresses


# ------------------------------------------------------------------ output

def render_entry(word: str, chunks, stressed: tuple):
    """chunks: list of (grapheme, p0, p1). Returns TSV line or None."""
    indices, stresses = syllabify(stressed)
    syllable_of_chunk = [indices[p0] for _, p0, p1 in chunks]

    groups = []  # (syllable_index, [chunk...])
    for chunk, syllable in zip(chunks, syllable_of_chunk):
        if groups and groups[-1][0] == syllable:
            groups[-1][1].append(chunk)
        else:
            groups.append((syllable, [chunk]))

    parts = []
    for syllable, group in groups:
        rendered = "|".join(
            f"{g}:{''.join(phone_ipa(p) for p in stressed[p0:p1])}"
            for g, p0, p1 in group
        )
        parts.append(f"{stresses[syllable]}[{rendered}]")
    spec = ".".join(parts)

    ipa_parts = []
    for k in range(max(indices) + 1):
        segment = "".join(phone_ipa(p) for p, s in zip(stressed, indices) if s == k)
        ipa_parts.append(stresses[k] + segment)
    ipa = "".join(ipa_parts)

    # Integrity check: graphemes must rebuild the word, phones must be
    # covered exactly once in order.
    if "".join(g for g, _, _ in chunks) != word:
        return None
    covered = [i for _, p0, p1 in chunks for i in range(p0, p1)]
    if covered != list(range(len(stressed))):
        return None
    return f"{word}\t{ipa}\t{spec}"


# ------------------------------------------------------------------- main

def load_cmudict(log=print):
    if not CACHE.exists():
        log(f"downloading CMUdict -> {CACHE}")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(CMUDICT_URL, timeout=60) as response:
            CACHE.write_bytes(response.read())
    entries = []
    for raw in CACHE.read_text(encoding="latin1").splitlines():
        if raw.startswith(";;;"):
            continue
        head, _, tail = raw.partition("  ")
        if not tail or not WORD_RE.fullmatch(head):
            continue  # symbols, variants WORD(2), comments
        word = head.lower()
        stressed = tuple(tail.split())
        entries.append((word, stressed))
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0,
                        help="only use the first N entries (debugging)")
    parser.add_argument("--sample", default="",
                        help="comma-separated words to print alignments for")
    parser.add_argument("--self-check", action="store_true",
                        help="validate an existing output file and exit")
    args = parser.parse_args()

    if args.self_check:
        return self_check(args.output)

    entries = load_cmudict()
    if args.limit:
        entries = entries[:args.limit]
    print(f"CMUdict entries accepted: {len(entries)}")

    training = [(w, tuple(p.rstrip("012") for p in s)) for w, s in entries]
    prob = em_align(training, max_iterations=args.iterations)

    lines = {}
    dropped_unaligned = dropped_invariant = 0
    for (word, stressed), (_, bases) in zip(entries, training):
        if word in lines:
            continue
        units = viterbi(word, bases, prob)
        chunks = merge_silent(units) if units else None
        line = render_entry(word, chunks, stressed) if chunks else None
        if units is None:
            dropped_unaligned += 1
        elif line is None:
            dropped_invariant += 1
        else:
            lines[word] = line

    ordered = [lines[w] for w in sorted(lines)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(ordered) + "\n", encoding="utf-8")
    print(f"wrote {len(ordered)} entries -> {args.output}")
    print(f"dropped: {dropped_unaligned} unalignable, "
          f"{dropped_invariant} failed integrity check")

    if args.sample:
        table = {l.split("\t")[0]: l for l in ordered}
        for word in args.sample.split(","):
            print(" ", table.get(word.strip().lower(), f"{word}: <missing>"))
    return 0


def self_check(output: Path):
    previous = None
    problems = 0
    count = 0
    for line in output.read_text(encoding="utf-8").splitlines():
        count += 1
        word, ipa, spec = line.split("\t")
        if previous is not None and not (previous < word):
            print(f"ORDER: {previous!r} !< {word!r}")
            problems += 1
        previous = word
        rebuilt = "".join(
            chunk.split(":")[0]
            for syllable in spec.split(".")
            for chunk in syllable.strip("ˈˌ")[1:-1].split("|")
        )
        if rebuilt != word:
            print(f"GRAPHEME MISMATCH: {word!r} != {rebuilt!r}")
            problems += 1
        if not ipa:
            print(f"EMPTY IPA: {word}")
            problems += 1
    print(f"self-check: {count} entries, {problems} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
