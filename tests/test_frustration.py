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

    def event(self, vk, kind='key', advance=0.1):
        self.now += advance
        return self.detector.track_key_event(vk, kind)

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

    def test_intervening_letter_or_space_cancels_before_backspace(self):
        for vk in (0, 1, 49):
            with self.subTest(vk=vk):
                self.detector.clear_history()
                results = [self.event(44), self.event(vk),
                           self.event('backspace', 'backspace')]
                self.assertFalse(any(results))

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

    def test_slow_adjacent_deletion_still_switches(self):
        self.event(44)
        self.assertTrue(self.event('backspace', 'backspace', advance=10_000.0))

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

    def test_legacy_timing_settings_do_not_gate_gestures(self):
        self.detector.time_window = 0.000001
        self.detector.cooldown = 1_000_000.0
        self.assertTrue(self.gesture()[-1])
        self.assertTrue(self.gesture()[-1])
        self.event(44)
        self.assertTrue(self.event('backspace', 'backspace', advance=1_000_000.0))


if __name__ == '__main__':
    unittest.main()
