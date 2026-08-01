"""Rule tests for grammar_notes.

Every dependency label asserted here was read off a live ``en_core_web_trf``
parse of the sentence in the test name, not guessed.  The fakes exist only
for speed — the model takes ~3 s to load and these are pure lookups over it
— and they are worth nothing unless the tree they describe is the tree
spaCy actually produces.  One of them once wasn't, and the green suite hid
a rule that never fired; see
``test_copula_that_already_has_a_complement_is_extraposition``.

So: when adding a case, dump the real parse first.
"""

import unittest

from grammar_notes import note_for_token


class Morph:
    def __init__(self, reflex=False):
        self._reflex = ["Yes"] if reflex else []

    def get(self, feature):
        return self._reflex if feature == "Reflex" else []


class Token:
    """Just the surface spaCy exposes to the rules."""

    def __init__(self, text, pos, dep, lemma=None, reflex=False):
        self.text = text
        self.lower_ = text.lower()
        self.pos_ = pos
        self.dep_ = dep
        self.lemma_ = lemma if lemma is not None else text.lower()
        self.morph = Morph(reflex)
        self.head = self
        self.children = []

    def under(self, head):
        self.head = head
        head.children.append(self)
        return self


class AnticipatoryItTests(unittest.TestCase):
    """"It is obvious that he lied" vs "I bought a book. It was good."

    spaCy tags both ``nsubj`` — only "There is…" gets ``expl`` — and the two
    pronouns are morphologically identical.  The head is the only witness.
    """

    def test_clausal_complement_on_the_head_marks_a_formal_subject(self):
        matter = Token("matter", "VERB", "ROOT")
        it = Token("It", "PRON", "nsubj").under(matter)
        Token("think", "VERB", "ccomp").under(matter)

        self.assertEqual(note_for_token(it), "形式主语，真正内容在后面的从句")

    def test_copula_that_already_has_a_complement_is_extraposition(self):
        """"It is easy to please him": both hang off ``is``, side by side.

        The infinitive does *not* attach to ``easy`` — that adjective has no
        children at all.  An earlier version of this test asserted the
        opposite from an invented tree, passed, and shipped a rule that
        silently skipped every "It is ADJ to V" sentence.
        """
        is_ = Token("is", "AUX", "ROOT", lemma="be")
        it = Token("It", "PRON", "nsubj").under(is_)
        Token("easy", "ADJ", "acomp").under(is_)
        Token("please", "VERB", "xcomp").under(is_)

        self.assertEqual(note_for_token(it), "形式主语，真正内容在后面的从句")

    def test_copula_without_a_complement_gets_no_note(self):
        """"It is going to rain.": ``is`` here raises rather than extraposes.

        Being a copula is not enough — the complement is what the clause is
        extraposed *from*.
        """
        is_ = Token("is", "AUX", "ROOT", lemma="be")
        it = Token("It", "PRON", "nsubj").under(is_)
        Token("going", "VERB", "xcomp").under(is_)

        self.assertEqual(note_for_token(it), "")

    def test_referential_it_gets_no_note(self):
        """"It is good.": an ``acomp`` is not a clause, so nothing is deferred."""
        is_ = Token("is", "AUX", "ROOT", lemma="be")
        it = Token("It", "PRON", "nsubj").under(is_)
        Token("good", "ADJ", "acomp").under(is_)

        self.assertEqual(note_for_token(it), "")

    def test_raising_verb_gets_no_note(self):
        """"It seems to work.": the ``xcomp`` here belongs to ``seems``.

        Raising and extraposition produce the same shape at this level, and
        "It seems/tends/continues to …" is common enough that a guess would
        mislabel referential ``it`` regularly.
        """
        seems = Token("seems", "VERB", "ROOT")
        it = Token("It", "PRON", "nsubj").under(seems)
        Token("work", "VERB", "xcomp").under(seems)

        self.assertEqual(note_for_token(it), "")

    def test_weather_it_gets_no_note(self):
        """"It was raining when I left.": the ``advcl`` is a real adverbial.

        This is why ``advcl`` is excluded from the clausal set even though it
        costs coverage on "It's all ironic when you consider that…" — that
        ``it`` goes unannotated rather than risk calling weather-it a
        placeholder.
        """
        raining = Token("raining", "VERB", "ROOT")
        it = Token("It", "PRON", "nsubj").under(raining)
        Token("left", "VERB", "advcl").under(raining)

        self.assertEqual(note_for_token(it), "")


class EmphaticReflexiveTests(unittest.TestCase):
    def test_appositive_reflexive_is_emphasis(self):
        """"She herself wrote the letter." """
        wrote = Token("wrote", "VERB", "ROOT")
        herself = Token("herself", "PRON", "appos", reflex=True).under(wrote)

        self.assertEqual(note_for_token(herself), "强调“本人、亲自”，不是宾语")

    def test_npadvmod_reflexive_is_emphasis(self):
        """"Shakespeare was himself an actor." """
        was = Token("was", "AUX", "ccomp", lemma="be")
        himself = Token("himself", "PRON", "npadvmod", reflex=True).under(was)

        self.assertEqual(note_for_token(himself), "强调“本人、亲自”，不是宾语")

    def test_object_reflexive_gets_no_note(self):
        """"He hurt himself badly.": here the word really is the object."""
        hurt = Token("hurt", "VERB", "ROOT")
        himself = Token("himself", "PRON", "dobj", reflex=True).under(hurt)

        self.assertEqual(note_for_token(himself), "")


class ComplementizerThatTests(unittest.TestCase):
    def test_object_clause(self):
        """"…you consider that Shakespeare was…" """
        consider = Token("consider", "VERB", "advcl")
        was = Token("was", "AUX", "ccomp", lemma="be").under(consider)
        that = Token("that", "SCONJ", "mark").under(was)

        self.assertEqual(note_for_token(that), "引导宾语从句，本身不译")

    def test_appositive_clause(self):
        """"The fact that he left surprised me.": the clause is ``acl``."""
        fact = Token("fact", "NOUN", "nsubj")
        left = Token("left", "VERB", "acl").under(fact)
        that = Token("that", "SCONJ", "mark").under(left)

        self.assertEqual(note_for_token(that), "引导同位语从句，说明前面的名词")

    def test_clause_under_a_copula_is_not_called_an_object_clause(self):
        """"It is no wonder that he left."

        spaCy hangs the clause off the copula as ``ccomp``, but a copula has
        no object; naming the clause type there would teach the wrong term.
        """
        is_ = Token("is", "AUX", "ROOT", lemma="be")
        left = Token("left", "VERB", "ccomp").under(is_)
        that = Token("that", "SCONJ", "mark").under(left)

        self.assertEqual(note_for_token(that), "引导从句，本身不译")

    def test_demonstrative_that_gets_no_note(self):
        """"That book is mine.": a determiner, not a complementizer."""
        book = Token("book", "NOUN", "nsubj")
        that = Token("that", "PRON", "det").under(book)

        self.assertEqual(note_for_token(that), "")


class DegreeAllTests(unittest.TestCase):
    def test_adverbial_all_is_intensity(self):
        """"It's all deliciously ironic." """
        s = Token("'s", "AUX", "ROOT", lemma="be")
        all_ = Token("all", "ADV", "advmod").under(s)

        self.assertEqual(note_for_token(all_), "程度副词“完全”，不是“全部”")

    def test_quantifier_all_gets_no_note(self):
        """"It took me all day.": here ``all`` really does mean 全部."""
        day = Token("day", "NOUN", "npadvmod")
        all_ = Token("all", "DET", "det").under(day)

        self.assertEqual(note_for_token(all_), "")


if __name__ == "__main__":
    unittest.main()
