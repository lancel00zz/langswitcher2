"""Regressions for layout switching before the user's next retry key."""

import unittest
from unittest.mock import patch

from detectors.frustration import FrustrationDetector


class FrustrationDetectorTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.clock = patch('detectors.frustration.time.monotonic', lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.detector = FrustrationDetector(time_window=1.5, cooldown=2.0)

    def event(self, vk, kind='key', advance=0.1, text=None):
        self.now += advance
        return self.detector.track_key_event(vk, kind, text=text)

    def gesture(self, vk=44):
        return [self.event(vk), self.event('backspace', 'backspace')]

    def test_switch_is_requested_on_backspace_without_waiting_for_retry(self):
        self.assertEqual(self.gesture(), [False, True])
        self.assertEqual(self.detector.get_last_triggered_key(), 44)
        self.assertEqual(self.detector.key_history, [])

    def test_retry_key_does_not_trigger_another_switch(self):
        self.assertTrue(self.gesture()[-1])
        self.assertFalse(self.event(44))
        self.assertFalse(self.event(0))

    def test_first_gesture_works_early_in_monotonic_clock(self):
        self.assertTrue(self.gesture()[-1])

    def test_deleting_a_letter_after_slash_does_not_switch_until_slash_is_deleted(self):
        for vk in (0, 1, 8):
            with self.subTest(vk=vk):
                self.detector.clear_history()
                results = [self.event(44), self.event(vk),
                           self.event('backspace', 'backspace')]
                self.assertFalse(any(results))
                self.assertTrue(self.event('backspace', 'backspace'))
                self.assertEqual(self.detector.get_last_triggered_key(), 44)

    def test_deleting_multiple_suffix_letters_reaches_the_original_eligible_key(self):
        self.event(44, text='/')
        self.event(8, text='c')
        self.event(31, text='o')
        self.assertFalse(self.event('backspace', 'backspace'))
        self.assertFalse(self.event('backspace', 'backspace'))
        self.assertTrue(self.event('backspace', 'backspace'))

    def test_word_boundary_keys_discard_the_previous_word(self):
        for vk in (49, 36, 76):
            with self.subTest(vk=vk):
                self.event(44)
                self.event(vk)
                self.assertFalse(self.event('backspace', 'backspace'))

    def test_supplied_whitespace_or_control_text_discards_history(self):
        for text in (' ', '\t', '\n', '\x00', ''):
            with self.subTest(text=repr(text)):
                self.event(44)
                self.event(None, text=text)
                self.assertFalse(self.event('backspace', 'backspace'))

    def test_printable_text_with_no_virtual_key_still_counts_as_a_deletion(self):
        self.event(44, text='/')
        self.event(None, text='c')
        self.assertFalse(self.event('backspace', 'backspace'))
        self.assertTrue(self.event('backspace', 'backspace'))

    def test_deletion_run_can_only_switch_once_even_with_multiple_eligible_keys(self):
        self.event(44)
        self.event(33)
        self.assertTrue(self.event('backspace', 'backspace'))
        self.assertEqual(self.detector.get_last_triggered_key(), 33)
        self.assertFalse(self.event('backspace', 'backspace'))

    def test_later_word_cannot_reach_a_previous_words_eligible_key(self):
        for vk in (44, 49, 8):
            self.event(vk)
        self.assertFalse(self.event('backspace', 'backspace'))
        self.assertFalse(self.event('backspace', 'backspace'))

    def test_long_suffix_uses_constant_memory_and_retains_no_typed_text(self):
        self.event(44)
        for _ in range(10_000):
            self.event(8, text='c')
        self.assertEqual(len(self.detector.key_history), 1)
        self.assertTrue(all(set(event) == {'timestamp', 'vk_code', 'type'}
                            for event in self.detector.key_history))
        for _ in range(10_000):
            self.assertFalse(self.event('backspace', 'backspace'))
        self.assertTrue(self.event('backspace', 'backspace'))

    def test_ordinary_letter_then_backspace_does_not_switch(self):
        self.assertFalse(self.event(0))
        self.assertFalse(self.event('backspace', 'backspace'))

    def test_most_recent_punctuation_key_is_the_deleted_key(self):
        self.assertFalse(self.event(44))
        self.assertFalse(self.event(33))
        self.assertTrue(self.event('backspace', 'backspace'))
        self.assertEqual(self.detector.get_last_triggered_key(), 33)

    def test_repeated_backspaces_only_switch_once(self):
        self.assertTrue(self.gesture()[-1])
        self.assertFalse(self.event('backspace', 'backspace'))
        self.assertFalse(self.event('backspace', 'backspace'))

    def test_forward_delete_or_navigation_cancels_gesture(self):
        for kind in ('delete', 'other'):
            with self.subTest(kind=kind):
                self.detector.clear_history()
                results = [self.event(44), self.event(117, kind),
                           self.event('backspace', 'backspace')]
                self.assertFalse(any(results))

    def test_idle_deletion_is_a_normal_edit_without_switching(self):
        self.event(44)
        self.assertFalse(self.event('backspace', 'backspace', advance=20.0))
        self.assertEqual(self.detector.key_history, [])

    def test_correction_still_works_just_before_idle_cutoff(self):
        self.event(44)
        self.assertTrue(self.event('backspace', 'backspace', advance=2.499))

    def test_exact_idle_cutoff_is_a_normal_edit(self):
        self.event(44)
        self.assertFalse(self.event('backspace', 'backspace', advance=2.5))

    def test_late_first_backspace_cannot_rearm_the_candidate(self):
        self.event(44, text='/')
        self.event(8, text='c')
        self.assertFalse(self.event('backspace', 'backspace', advance=2.5))
        self.assertFalse(self.event('backspace', 'backspace'))

    def test_late_second_backspace_is_a_normal_edit(self):
        self.event(44, text='/')
        self.event(8, text='c')
        self.assertFalse(self.event('backspace', 'backspace'))
        self.assertFalse(self.event('backspace', 'backspace', advance=2.5))

    def test_each_typed_or_deleted_suffix_key_refreshes_idle_window(self):
        self.event(44, text='/')
        self.event(8, text='c', advance=2.0)
        self.event(31, text='o', advance=2.0)
        self.assertFalse(self.event('backspace', 'backspace', advance=2.0))
        self.assertFalse(self.event('backspace', 'backspace', advance=2.0))
        self.assertTrue(self.event('backspace', 'backspace', advance=2.0))

    def test_ordinary_typing_after_expiry_does_not_revive_old_candidate(self):
        self.event(44)
        self.event(8, text='c', advance=2.5)
        self.assertFalse(self.event('backspace', 'backspace'))
        self.assertFalse(self.event('backspace', 'backspace'))

    def test_new_eligible_key_can_start_a_fresh_window_after_expiry(self):
        self.event(44)
        self.event(33, advance=2.5)
        self.assertTrue(self.event('backspace', 'backspace'))
        self.assertEqual(self.detector.get_last_triggered_key(), 33)

    def test_timeout_must_be_positive_and_finite(self):
        for value in (0, -1, float('inf'), float('-inf'), float('nan')):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'positive and finite'):
                    FrustrationDetector(correction_timeout=value)

    def test_explicit_timeout_parameter_controls_idle_window(self):
        self.detector = FrustrationDetector(correction_timeout=1.0)
        self.event(44)
        self.assertFalse(self.event('backspace', 'backspace', advance=1.0))

    def test_rapid_alternating_corrections_have_no_minimum_interval(self):
        # The same physical slash key yields / or é depending on the layout.
        # Both zero elapsed time and a microsecond between events must work.
        for interval in (0.0, 0.000001):
            with self.subTest(interval=interval):
                self.detector.clear_history()
                for _ in range(100):
                    self.assertFalse(self.event(44, advance=interval))
                    self.assertTrue(
                        self.event('backspace', 'backspace', advance=interval)
                    )

    def test_history_reset_does_not_require_a_pause(self):
        self.assertTrue(self.gesture()[-1])
        self.detector.clear_history()
        self.assertTrue(self.gesture()[-1])

    def test_legacy_timing_settings_do_not_override_correction_timeout(self):
        self.detector.time_window = 0.000001
        self.detector.cooldown = 1_000_000.0
        self.assertTrue(self.gesture()[-1])
        self.assertTrue(self.gesture()[-1])
        self.event(44)
        self.assertFalse(self.event('backspace', 'backspace', advance=2.5))
        self.assertTrue(self.gesture()[-1])


if __name__ == '__main__':
    unittest.main()
