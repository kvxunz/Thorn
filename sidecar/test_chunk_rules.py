import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from chunk_rules import (
    coordinated_prep_conjuncts,
    coordinating_ccs_before,
    has_own_subject,
    independent_verbal_conjuncts,
    is_clausal_pcomp,
    is_comitative_participle,
    is_concessive_however_clause,
    is_dash_appositive,
    is_fixed_adverbial_particle,
    is_preposed_though_adjective,
    is_wh_relative_pronoun,
    mark_discourse_insertions,
    merge_or_so,
    merge_split_words,
    merge_tiny,
    phrasal_prep_verb_preposition,
    prep_object_start,
    prepare_parse_text,
    relative_pronoun_gloss,
    though_clause_verb,
    verb_group_indices,
)


class _FakeTok:
    def __init__(self, tag, lemma, children=None):
        self.tag_ = tag
        self.lemma_ = lemma
        self.children = children or []


class _FakeChild:
    def __init__(self, dep, lower):
        self.dep_ = dep
        self.lower_ = lower
        self.text = lower


class ChunkRuleTests(unittest.TestCase):
    def test_look_back_stays_in_the_verb_group(self):
        self.assertTrue(is_fixed_adverbial_particle("look", "back", "advmod"))
        self.assertFalse(is_fixed_adverbial_particle("look", "only", "advmod"))

    def test_however_degree_clause_overrides_false_relative_attachment(self):
        tokens = [
            ("however", "advmod", "SCONJ", "ADJ", "RB"),
            ("disputable", "acomp", "ADJ", "AUX", "JJ"),
            ("results", "nsubj", "NOUN", "AUX", "NNS"),
            ("be", "relcl", "AUX", "NOUN", "VB"),
        ]

        self.assertTrue(is_concessive_however_clause("relcl", tokens))

    def test_real_relative_clause_is_not_overridden(self):
        tokens = [
            ("which", "nsubj", "PRON", "VERB", "WDT"),
            ("seems", "relcl", "VERB", "NOUN", "VBZ"),
            ("irritating", "acomp", "ADJ", "VERB", "JJ"),
        ]

        self.assertFalse(is_concessive_however_clause("relcl", tokens))


class ComitativeParticipleTests(unittest.TestCase):
    def test_coupled_with_is_comitative(self):
        tok = _FakeTok("VBN", "couple", [_FakeChild("prep", "with")])
        self.assertTrue(is_comitative_participle(tok))

    def test_written_by_is_not_comitative(self):
        tok = _FakeTok("VBN", "write", [_FakeChild("agent", "by")])
        self.assertFalse(is_comitative_participle(tok))


class _VGTok:
    """Minimal spaCy-like token for verb_group_indices unit tests."""

    def __init__(self, i, text, dep, head_i, doc_ref, lemma=None, pos=None):
        self.i = i
        self.text = text
        self.dep_ = dep
        self._head_i = head_i
        self.lemma_ = lemma or text.lower()
        self.lower_ = text.lower()
        self.pos_ = pos or ""
        self._doc_ref = doc_ref

    @property
    def doc(self):
        return self._doc_ref

    @property
    def head(self):
        return self._doc_ref[self._head_i]

    @property
    def children(self):
        return [t for t in self._doc_ref if t._head_i == self.i and t.i != self.i]

    @property
    def subtree(self):
        yield self
        for child in self.children:
            yield from child.subtree


def _make_doc(specs):
    """specs: (text, dep, head_i) plus optional lemma and POS."""
    doc = []
    for i, spec in enumerate(specs):
        text, dep, head_i = spec[:3]
        lemma = spec[3] if len(spec) > 3 else None
        pos = spec[4] if len(spec) > 4 else None
        doc.append(_VGTok(i, text, dep, head_i, doc, lemma=lemma, pos=pos))
    return doc


class VerbGroupTests(unittest.TestCase):
    def test_would_almost_certainly_bring_is_one_group(self):
        # indices: 0 would aux→3, 1 almost advmod→2, 2 certainly advmod→3, 3 bring ROOT
        doc = _make_doc([
            ("would", "aux", 3),
            ("almost", "advmod", 2),
            ("certainly", "advmod", 3),
            ("bring", "ROOT", 3),
        ])
        got = verb_group_indices(doc[3])
        self.assertEqual(got, {0, 1, 2, 3})

    def test_can_hardly_be_classed_sandwich(self):
        # can aux, hardly advmod→classed, be aux, classed
        doc = _make_doc([
            ("can", "aux", 3),
            ("hardly", "advmod", 3),
            ("be", "aux", 3),
            ("classed", "ROOT", 3),
        ])
        self.assertEqual(verb_group_indices(doc[3]), {0, 1, 2, 3})

    def test_postverbal_adverb_stays_out(self):
        # bring carefully — carefully after verb, not mid-complex
        doc = _make_doc([
            ("would", "aux", 1),
            ("bring", "ROOT", 1),
            ("carefully", "advmod", 1),
        ])
        self.assertEqual(verb_group_indices(doc[1]), {0, 1})

    def test_no_aux_does_not_swallow_preverbal_adverbs(self):
        # almost certainly bring with no aux — leave degree adverbs free
        doc = _make_doc([
            ("almost", "advmod", 1),
            ("certainly", "advmod", 2),
            ("bring", "ROOT", 2),
        ])
        self.assertEqual(verb_group_indices(doc[2]), {2})


class PhrasalPrepVerbTests(unittest.TestCase):
    """Every tree below was read off a live ``en_core_web_trf`` parse.

    The three shapes are not a taxonomy anyone designed — they are what the
    model happens to emit for one construction, so guessing any of them
    ends in a rule that never fires.
    """

    def test_particle_prt_with_preposition_on_the_verb(self):
        """"live up to": ``up`` is ``prt``, ``to`` hangs off ``live``."""
        doc = _make_doc([
            ("live", "xcomp", 0),
            ("up", "prt", 0),
            ("to", "prep", 0),
            ("promise", "pobj", 2),
        ])
        self.assertIs(phrasal_prep_verb_preposition(doc[0]), doc[2])
        self.assertEqual(verb_group_indices(doc[0]), {0, 1, 2})

    def test_particle_advmod_with_preposition_on_the_particle(self):
        """"fall back on": ``back`` is ``advmod`` and ``on`` hangs off it."""
        doc = _make_doc([
            ("fell", "ROOT", 0, "fall"),
            ("back", "advmod", 0),
            ("on", "prep", 1),
            ("method", "pobj", 2),
        ])
        self.assertIs(phrasal_prep_verb_preposition(doc[0]), doc[2])
        self.assertEqual(verb_group_indices(doc[0]), {0, 1, 2})

    def test_particle_tagged_prep_is_still_a_particle(self):
        """"face up to": spaCy calls ``up`` a preposition here."""
        doc = _make_doc([
            ("face", "ROOT", 0),
            ("up", "prep", 0),
            ("to", "prep", 0),
            ("facts", "pobj", 2),
        ])
        self.assertIs(phrasal_prep_verb_preposition(doc[0]), doc[2])
        self.assertEqual(verb_group_indices(doc[0]), {0, 1, 2})

    def test_unlisted_combination_is_left_alone(self):
        """"looked up at the sky": ``look up`` is literal, ``at`` is its own."""
        doc = _make_doc([
            ("looked", "ROOT", 0, "look"),
            ("up", "prt", 0),
            ("at", "prep", 0),
            ("sky", "pobj", 2),
        ])
        self.assertIsNone(phrasal_prep_verb_preposition(doc[0]))
        self.assertEqual(verb_group_indices(doc[0]), {0, 1})

    def test_separated_particle_is_not_the_idiom(self):
        """"put the book up on the shelf": the object splits the two words.

        Adjacency is the whole guard against reading a listed combination
        into a sentence that merely contains those words.
        """
        doc = _make_doc([
            ("put", "ROOT", 0),
            ("book", "dobj", 0),
            ("up", "prt", 0),
            ("on", "prep", 0),
            ("shelf", "pobj", 3),
        ])
        self.assertIsNone(phrasal_prep_verb_preposition(doc[0]))


class PrepObjectStartTests(unittest.TestCase):
    def test_object_starts_at_its_determiner(self):
        """"from the fact that …": the 宾语 card opens at ``the``, not ``fact``."""
        doc = _make_doc([
            ("from", "prep", 0, None, "ADP"),
            ("the", "det", 2, None, "DET"),
            ("fact", "pobj", 0, None, "NOUN"),
        ])
        self.assertEqual(prep_object_start(doc[0], 0, 2), 1)

    def test_compound_preposition_is_not_cut(self):
        """"in spite of the rain": spaCy's pobj is ``spite``.

        Splitting there would put "of" — half the preposition — on the object
        card, so the run stays one card instead.
        """
        doc = _make_doc([
            ("in", "prep", 0, None, "ADP"),
            ("spite", "pobj", 0, None, "NOUN"),
            ("of", "prep", 1, None, "ADP"),
            ("the", "det", 4, None, "DET"),
            ("rain", "pobj", 2, None, "NOUN"),
        ])
        self.assertIsNone(prep_object_start(doc[0], 0, 4))

    def test_preposition_without_an_object_in_the_run(self):
        """A stranded prep ("the man I spoke **to**") has nothing to split."""
        doc = _make_doc([
            ("spoke", "ROOT", 0, None, "VERB"),
            ("to", "prep", 0, None, "ADP"),
        ])
        self.assertIsNone(prep_object_start(doc[1], 1, 1))

    def test_object_outside_the_run_is_ignored(self):
        """The clause child owns those tokens; only the core run may be cut."""
        doc = _make_doc([
            ("from", "prep", 0, None, "ADP"),
            ("the", "det", 2, None, "DET"),
            ("fact", "pobj", 0, None, "NOUN"),
        ])
        self.assertIsNone(prep_object_start(doc[0], 0, 0))


class RelativePronounGlossTests(unittest.TestCase):
    def test_subject_relative_says_which_slot_it_fills(self):
        self.assertEqual(
            relative_pronoun_gloss("product", "nsubj"),
            "指代前述的 product，在从句中作主语",
        )

    def test_object_relative_says_object(self):
        self.assertEqual(
            relative_pronoun_gloss("book", "dobj"),
            "指代前述的 book，在从句中作宾语",
        )

    def test_unknown_slot_stays_silent_rather_than_guessing(self):
        self.assertEqual(
            relative_pronoun_gloss("place", "dep"),
            "指代前述的 place",
        )

    def test_no_referent_means_no_gloss(self):
        self.assertEqual(relative_pronoun_gloss(None, "nsubj"), "")


class OrSoTests(unittest.TestCase):
    def test_merge_or_so_fuses_discourse_hedge(self):
        chunks = [
            {"text": "or", "role": "conjunction", "gloss": "", "children": None},
            {"text": "so", "role": "adverbial", "gloss": "", "children": None},
            {"text": "the ad", "role": "subject", "gloss": "", "children": None},
        ]
        out = merge_or_so(chunks)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["text"], "or so")
        self.assertEqual(out[0]["role"], "insertion")
        self.assertEqual(out[0]["gloss"], "")


class DiscourseMarkerTests(unittest.TestCase):
    def test_of_course_becomes_insertion(self):
        chunks = [{"text": "of course,", "role": "prep-phrase", "children": None}]
        self.assertEqual(mark_discourse_insertions(chunks)[0]["role"], "insertion")

    def test_structural_prep_phrases_stay(self):
        chunks = [
            {"text": "to Ireland", "role": "prep-phrase", "children": None},
            {"text": "in fact-checking", "role": "prep-phrase", "children": None},
        ]
        out = mark_discourse_insertions(chunks)
        self.assertEqual(out[0]["role"], "prep-phrase")
        self.assertEqual(out[1]["role"], "prep-phrase")


class _PcompTok:
    def __init__(self, dep, pos, child_deps=()):
        self.dep_ = dep
        self.pos_ = pos
        self.children = [_FakeChild(dep, "") for dep in child_deps]


class ClausalPcompTests(unittest.TestCase):
    def test_pcomp_with_own_subject_is_a_clause(self):
        # "in how well it can control expression" — control: pcomp, VERB, nsubj it
        self.assertTrue(is_clausal_pcomp(_PcompTok("pcomp", "VERB", ("advmod", "nsubj", "dobj"))))

    def test_subjectless_gerund_pcomp_stays_flat(self):
        # "in doing so" — no own subject
        self.assertFalse(is_clausal_pcomp(_PcompTok("pcomp", "VERB", ("dobj",))))

    def test_non_pcomp_and_non_verbal_are_rejected(self):
        self.assertFalse(is_clausal_pcomp(_PcompTok("pobj", "NOUN", ("nsubj",))))
        self.assertFalse(is_clausal_pcomp(_PcompTok("pcomp", "NOUN", ("nsubj",))))


class _ClauseTok:
    """Minimal token graph for independent-conjunct promotion tests."""

    def __init__(self, i, text, dep, pos, head=None, children=None):
        self.i = i
        self.text = text
        self.dep_ = dep
        self.pos_ = pos
        self.head = head or self
        self.children = list(children or [])


class IndependentConjunctPromotionTests(unittest.TestCase):
    def test_shared_subject_vp_coordination_is_not_promoted(self):
        # "he came and left" — left has no own subject
        came = _ClauseTok(1, "came", "ccomp", "VERB")
        left = _ClauseTok(3, "left", "conj", "VERB", head=came)
        came.children = [
            _ClauseTok(0, "he", "nsubj", "PRON", head=came),
            _ClauseTok(2, "and", "cc", "CCONJ", head=came),
            left,
        ]
        self.assertEqual(list(independent_verbal_conjuncts(came)), [])

    def test_conjunct_with_own_subject_is_promoted(self):
        # "say [I curl …] and [I'll be tormented …]"
        curl = _ClauseTok(2, "curl", "ccomp", "VERB")
        tormented = _ClauseTok(6, "tormented", "conj", "VERB", head=curl)
        and_cc = _ClauseTok(4, "and", "cc", "CCONJ", head=curl)
        curl.children = [
            _ClauseTok(1, "I", "nsubj", "PRON", head=curl),
            and_cc,
            tormented,
        ]
        tormented.children = [
            _ClauseTok(5, "I", "nsubjpass", "PRON", head=tormented),
        ]
        promoted = list(independent_verbal_conjuncts(curl))
        self.assertEqual(promoted, [tormented])
        self.assertTrue(has_own_subject(tormented))
        self.assertEqual(list(coordinating_ccs_before(curl, tormented)), [and_cc])


class PrepConjunctAndThoughTests(unittest.TestCase):
    def test_coordinated_by_phrases_are_detected(self):
        first_by = _ClauseTok(4, "by", "agent", "ADP")
        second_by = _ClauseTok(10, "by", "conj", "ADP", head=first_by)
        and_cc = _ClauseTok(9, "and", "cc", "CCONJ", head=first_by)
        first_by.children = [and_cc, second_by]
        self.assertEqual(list(coordinated_prep_conjuncts(first_by)), [second_by])

    def test_preposed_though_adjective(self):
        odd = _ClauseTok(0, "Odd", "advcl", "ADJ")
        sounds = _ClauseTok(3, "sounds", "advcl", "VERB", head=odd)
        though = _ClauseTok(1, "though", "mark", "SCONJ", head=sounds)
        sounds.children = [though, _ClauseTok(2, "it", "nsubj", "PRON", head=sounds)]
        odd.children = [sounds]
        # lower_ for mark check
        though.lower_ = "though"
        self.assertTrue(is_preposed_though_adjective(odd))
        self.assertIs(though_clause_verb(odd), sounds)

    def test_wh_relative_pronoun(self):
        who = _ClauseTok(0, "who", "nsubj", "PRON")
        who.tag_ = "WP"
        who.lower_ = "who"
        self.assertTrue(is_wh_relative_pronoun(who))

    def test_a_demonstrative_that_is_not_a_relative_pronoun(self):
        # "That's the secret of Castle Rackrent" was taught with "That" as a
        # 连词 introducing nothing: the lexical fallback accepts the bare word,
        # and spaCy had already said DT/nsubj rather than WDT.
        that = _ClauseTok(0, "That", "nsubj", "PRON")
        that.tag_ = "DT"
        that.lower_ = "that"
        self.assertFalse(is_wh_relative_pronoun(that))

    def test_a_relative_that_spacy_tagged_is_still_caught(self):
        that = _ClauseTok(2, "that", "nsubj", "PRON")
        that.tag_ = "WDT"
        that.lower_ = "that"
        self.assertTrue(is_wh_relative_pronoun(that))

    def test_dash_appositive_detects_em_dash_child(self):
        institute = _ClauseTok(0, "Institute", "nsubj", "PROPN")
        group = _ClauseTok(2, "group", "appos", "NOUN", head=institute)
        dash = _ClauseTok(1, "—", "punct", "PUNCT", head=institute)
        institute.children = [dash, group]
        group.children = []
        # Fake doc for index walk is optional; punct child on head is enough.
        self.assertTrue(is_dash_appositive(group))


class DashParentheticalRepairTests(unittest.TestCase):
    def test_normalize_spaces_double_dashes_and_strips_pdf_brackets(self):
        raw = "workplace--all that[tObj] reengineering--are only"
        self.assertEqual(
            prepare_parse_text(raw).parser,
            "workplace -- all that reengineering -- are only",
        )

    def test_parser_cleanup_maps_normalized_dashes_back_to_surface_text(self):
        prepared = prepare_parse_text("workplace—aside—works")
        self.assertEqual(prepared.surface, "workplace—aside—works")
        self.assertEqual(prepared.parser, "workplace -- aside -- works")
        parser_offsets = ((0, 9), (10, 12), (13, 18), (19, 21), (22, 27))
        source_offsets = prepared.source_token_offsets(parser_offsets)
        self.assertEqual(
            [prepared.surface[start:end] for start, end in source_offsets],
            ["workplace", "—", "aside", "—", "works"],
        )

    def test_parser_cleanup_is_idempotent_for_pre_spaced_dashes(self):
        for raw in (
            "workplace -- aside -- works",
            "workplace-- aside--works",
            "workplace — aside — works",
        ):
            with self.subTest(raw=raw):
                prepared = prepare_parse_text(raw)
                self.assertEqual(prepared.parser, "workplace -- aside -- works")
                offsets = ((0, 9), (10, 12), (13, 18), (19, 21), (22, 27))
                mapped = prepared.source_token_offsets(offsets)
                self.assertTrue(all(end > start for start, end in mapped))

    def test_surface_cleanup_drops_object_markers_without_guessing_word_breaks(self):
        prepared = prepare_parse_text("Social Security\uFFFCwith much orall")
        self.assertEqual(prepared.surface, "Social Security with much orall")
        self.assertIn("orall", prepared.parser)

    def test_artifact_only_input_has_no_parser_view(self):
        prepared = prepare_parse_text("\uFFFC[tObj]\u2060")
        self.assertEqual(prepared.surface, "")
        self.assertEqual(prepared.parser, "")


if __name__ == "__main__":
    unittest.main()


class MergeTinyTests(unittest.TestCase):
    """merge_tiny owns whether a token can vanish between passes."""

    def test_trailing_punctuation_joins_the_previous_chunk(self):
        merged = merge_tiny([
            {"text": "the cat", "_lo": 0, "_hi": 1},
            {"text": ".", "_lo": 2, "_hi": 2},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "the cat.")
        self.assertEqual(merged[0]["_hi"], 2)

    def test_leading_punctuation_joins_the_next_chunk(self):
        merged = merge_tiny([
            {"text": "—", "_lo": 0, "_hi": 0},
            {"text": "like the egg", "_lo": 1, "_hi": 3},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "—like the egg")
        self.assertEqual(merged[0]["_lo"], 0)
        self.assertEqual(merged[0]["_hi"], 3)

    def test_an_all_punctuation_list_still_yields_its_tokens(self):
        # spaCy splits "re-investigate" into three conj tokens and calls the
        # bare hyphen a coordinate VERB, so its inline clause builds to exactly
        # this. Returning [] here opened a one-token coverage gap that failed
        # the whole sentence with "engine unavailable".
        merged = merge_tiny([{"text": "-", "_lo": 22, "_hi": 22}])
        self.assertEqual(merged, [{"text": "-", "_lo": 22, "_hi": 22}])

    def test_consecutive_leading_punctuation_keeps_the_outer_bounds(self):
        merged = merge_tiny([
            {"text": "(", "_lo": 0, "_hi": 0},
            {"text": "—", "_lo": 1, "_hi": 1},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "(—")
        self.assertEqual(merged[0]["_lo"], 0)
        self.assertEqual(merged[0]["_hi"], 1)


class _FakeDoc:
    """Just enough of a spaCy Doc for splits_a_word: text plus token offsets."""

    def __init__(self, text, tokens):
        self.text = text
        self._tokens = []
        cursor = 0
        for piece in tokens:
            cursor = text.index(piece, cursor)
            self._tokens.append(type("T", (), {"idx": cursor, "text": piece})())
            cursor += len(piece)

    def __len__(self):
        return len(self._tokens)

    def __getitem__(self, index):
        return self._tokens[index]


class MergeSplitWordsTests(unittest.TestCase):
    """A card boundary may never fall inside one written word."""

    def test_a_hyphenated_verb_is_one_card(self):
        doc = _FakeDoc("and re-investigate some", ["and", "re", "-", "investigate", "some"])
        merged = merge_split_words([
            {"text": "re-", "_lo": 1, "_hi": 2, "role": "verb"},
            {"text": "investigate", "_lo": 3, "_hi": 3, "role": "verb"},
        ], doc)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "re-investigate")
        self.assertEqual(merged[0]["role"], "verb")
        self.assertEqual(merged[0]["_hi"], 3)

    def test_the_joiner_may_sit_on_either_side_of_the_seam(self):
        # spaCy makes the hyphen its own token, so the boundary can fall
        # before it as easily as after -- "re" | "-investigate" is the same
        # defect and was missed while the test only looked rightwards.
        doc = _FakeDoc("and re-investigate some", ["and", "re", "-", "investigate", "some"])
        merged = merge_split_words([
            {"text": "re", "_lo": 1, "_hi": 1, "role": "verb"},
            {"text": "-", "_lo": 2, "_hi": 2, "role": "verb"},
            {"text": "investigate", "_lo": 3, "_hi": 3, "role": "verb"},
        ], doc)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "re-investigate")

    def test_a_contraction_names_both_slots_it_fused(self):
        # "I'm supposed": the merge has to happen -- the boundary is inside a
        # written word -- but keeping the subject's role taught the learner
        # that "I'm supposed" is a noun phrase.
        doc = _FakeDoc("but I’m supposed", ["but", "I", "’m", "supposed"])
        merged = merge_split_words([
            {"text": "I", "_lo": 1, "_hi": 1, "role": "subject"},
            {"text": "’m supposed", "_lo": 2, "_hi": 3, "role": "verb"},
        ], doc)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "I’m supposed")
        self.assertEqual(merged[0]["role"], "subject-verb")

    def test_a_fused_pair_of_one_role_keeps_that_role(self):
        # Only a mixed pair gets renamed: "re-investigate" is a verb twice
        # over and must not come back as something new.
        doc = _FakeDoc("and re-investigate some", ["and", "re", "-", "investigate", "some"])
        merged = merge_split_words([
            {"text": "re-", "_lo": 1, "_hi": 2, "role": "verb"},
            {"text": "investigate", "_lo": 3, "_hi": 3, "role": "verb"},
        ], doc)
        self.assertEqual(merged[0]["role"], "verb")

    def test_a_dash_run_still_separates_two_cards(self):
        # "The plan--his own--failed": the dash appositive must keep splitting.
        doc = _FakeDoc("plan--his own", ["plan", "--", "his", "own"])
        chunks = [
            {"text": "plan", "_lo": 0, "_hi": 0, "role": "subject"},
            {"text": "--his own", "_lo": 1, "_hi": 3, "role": "insertion"},
        ]
        self.assertEqual(merge_split_words(list(chunks), doc), chunks)

    def test_a_space_at_the_seam_is_a_real_boundary(self):
        doc = _FakeDoc("the cat sat", ["the", "cat", "sat"])
        chunks = [
            {"text": "the cat", "_lo": 0, "_hi": 1, "role": "subject"},
            {"text": "sat", "_lo": 2, "_hi": 2, "role": "verb"},
        ]
        self.assertEqual(merge_split_words(list(chunks), doc), chunks)

    def test_an_expanded_card_is_never_folded_away(self):
        # Folding a card with children would silently destroy a whole layer;
        # a word split across two expanded cards must stay visible instead.
        doc = _FakeDoc("and re-investigate some", ["and", "re", "-", "investigate", "some"])
        chunks = [
            {"text": "re-", "_lo": 1, "_hi": 2, "role": "verb"},
            {"text": "investigate", "_lo": 3, "_hi": 3, "role": "verb",
             "children": [{"text": "investigate", "_lo": 3, "_hi": 3}]},
        ]
        self.assertEqual(merge_split_words(list(chunks), doc), chunks)
