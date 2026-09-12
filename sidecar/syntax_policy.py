from __future__ import annotations

_LINKING_LEMMAS = frozenset({
    "be", "seem", "become", "remain", "appear", "look", "feel", "sound", "stay", "grow",
})


def backbone_role(dependency: str, governor_lemma: str) -> tuple[str, bool] | None:
    if dependency in {"nsubj", "nsubjpass", "expl"}:
        return "subject", False
    if dependency in {"dobj", "obj", "iobj", "dative", "oprd"}:
        return ("complement" if governor_lemma in _LINKING_LEMMAS else "object"), False
    if dependency in {"attr", "acomp"}:
        return "complement", False
    if dependency == "xcomp":
        return "complement", True
    if dependency in {"ccomp", "csubj", "csubjpass"}:
        return "clause-noun", True
    return None
