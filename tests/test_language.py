"""Regressions for layout switches driven by actual language evidence."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from detectors import language


class LanguageDetectorTests(unittest.TestCase):
    def setUp(self):
        # Each test supplies only the dictionary/model outcomes it needs. This
        # makes the switching contract independent of installed word lists.
        self.enchant = patch.object(language, "ENCHANT_AVAILABLE", False)
        self.enchant.start()
        self.addCleanup(self.enchant.stop)
        self.model = patch.object(language, "detect_langs", return_value=[])
        self.detect_langs = self.model.start()
        self.addCleanup(self.model.stop)
        self.detector = language.LanguageDetector(
            ["en", "fr"], {}, buffer_size=5, switch_threshold=3,
            min_word_length=2, confidence_threshold=0.65,
        )

    def test_unknown_words_do_not_multiply_one_french_detection(self):
        for word in ["avec", "qzxvpl", "qzxvpl"]:
            detected = self.detector.detect(word, current_lang="en")
            self.assertEqual(detected, "fr")
            self.assertFalse(self.detector.should_switch(detected, "en"))
        self.assertEqual(self.detector.get_buffer_state(), ["fr"])

    def test_shared_common_words_are_neutral_in_both_layouts(self):
        self.detect_langs.return_value = [SimpleNamespace(lang="en", prob=0.999)]
        for current in ["en", "fr"]:
            for word in ["on", "me", "as", "On", "ME"]:
                with self.subTest(current=current, word=word):
                    self.detector.clear_buffer()
                    detected = self.detector.detect(word, current_lang=current)
                    self.assertEqual(detected, current)
                    self.assertFalse(self.detector.should_switch(detected, current))
                    self.assertEqual(self.detector.get_buffer_state(), [])
        self.detect_langs.assert_not_called()

    def test_shared_common_words_are_independent_of_language_order(self):
        self.detector.detection_langs = ["fr", "en"]
        self.assertIsNone(self.detector._detect_common_word("on"))
        self.assertEqual(self.detector.detect("on", current_lang="en"), "en")
        self.assertEqual(self.detector.get_buffer_state(), [])

    def test_genuine_words_still_switch_in_both_directions(self):
        for current, target, words in [
            ("en", "fr", ["avec", "pour", "vous"]),
            ("fr", "en", ["with", "your", "what"]),
        ]:
            self.detector.clear_buffer()
            for index, word in enumerate(words):
                with self.subTest(current=current, word=word):
                    detected = self.detector.detect(word, current_lang=current)
                    self.assertEqual(detected, target)
                    self.assertEqual(
                        self.detector.should_switch(detected, current), index == 2,
                    )

    def test_ambiguous_word_cannot_trigger_from_existing_full_buffer(self):
        for word in ["avec", "pour", "vous"]:
            self.detector.detect(word, current_lang="en")
        for word in ["on", "qzxvpl"]:
            detected = self.detector.detect(word, current_lang="en")
            self.assertEqual(detected, "fr")
            self.assertFalse(self.detector.should_switch(detected, "en"))
        self.assertEqual(self.detector.get_buffer_state(), ["fr", "fr", "fr"])

    def test_conflicting_evidence_prevents_early_switch(self):
        for word in ["avec", "pour", "the", "vous", "avec"]:
            detected = self.detector.detect(word, current_lang="en")
            self.assertFalse(self.detector.should_switch(detected, "en"))
        detected = self.detector.detect("pour", current_lang="en")
        self.assertTrue(self.detector.should_switch(detected, "en"))

    def test_shared_dictionary_word_bypasses_model(self):
        self.detector.dicts = {"en": Mock(), "fr": Mock()}
        for dictionary in self.detector.dicts.values():
            dictionary.check.return_value = True
        self.detect_langs.return_value = [SimpleNamespace(lang="en", prob=0.999)]
        for current in ["en", "fr"]:
            detected = self.detector.detect("menu", current_lang=current)
            self.assertEqual(detected, current)
            self.assertFalse(self.detector.should_switch(detected, current))
        self.assertEqual(self.detector.get_buffer_state(), [])
        self.detect_langs.assert_not_called()

    def test_unique_dictionary_word_counts_as_evidence(self):
        self.detector.dicts = {"en": Mock(), "fr": Mock()}
        self.detector.dicts["en"].check.return_value = False
        self.detector.dicts["fr"].check.return_value = True
        self.assertEqual(self.detector.detect("bonjour", current_lang="en"), "fr")
        self.assertEqual(self.detector.get_buffer_state(), ["fr"])
        self.detect_langs.assert_not_called()

    def test_short_word_is_neutral_even_after_enough_evidence(self):
        for word in ["avec", "pour", "vous"]:
            self.detector.detect(word, current_lang="en")
        self.assertIsNone(self.detector.detect("a", current_lang="en"))
        self.assertFalse(self.detector.should_switch("fr", "en"))
        self.assertEqual(self.detector.get_buffer_state(), ["fr", "fr", "fr"])

    def test_fallback_setting_changes_context_but_never_adds_votes(self):
        self.detector.detect("avec", current_lang="en")
        self.detector.fallback_to_buffer = False
        self.assertEqual(self.detector.detect("qzxvpl", current_lang="en"), "en")
        self.assertEqual(self.detector.get_buffer_state(), ["fr"])
        self.assertFalse(self.detector.should_switch("en", "fr"))

    def test_low_model_confidence_stays_neutral(self):
        self.detect_langs.return_value = [SimpleNamespace(lang="fr", prob=0.4)]
        detected = self.detector.detect("qzxvpl", current_lang="en")
        self.assertEqual(detected, "en")
        self.assertEqual(self.detector.get_buffer_state(), [])

    def test_confident_model_result_counts_as_evidence(self):
        self.detect_langs.return_value = [SimpleNamespace(lang="fr", prob=0.99)]
        self.assertEqual(self.detector.detect("qzxvpl", current_lang="en"), "fr")
        self.assertEqual(self.detector.get_buffer_state(), ["fr"])

    def test_unsupported_model_language_is_neutral_even_at_zero_threshold(self):
        self.detector.confidence_threshold = 0.0
        self.detect_langs.return_value = [SimpleNamespace(lang="de", prob=0.99)]
        self.assertEqual(self.detector.detect("qzxvpl", current_lang="fr"), "fr")
        self.assertEqual(self.detector.get_buffer_state(), [])

    def test_clear_buffer_discards_evidence(self):
        self.detector.detect("avec", current_lang="en")
        self.detector.clear_buffer()
        self.assertEqual(self.detector.get_buffer_state(), [])
        self.assertFalse(self.detector.should_switch("fr", "en"))


if __name__ == "__main__":
    unittest.main()
