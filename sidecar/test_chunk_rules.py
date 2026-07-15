import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from chunk_rules import (
    is_concessive_however_clause,
    is_fixed_adverbial_particle,
)


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


if __name__ == "__main__":
    unittest.main()
