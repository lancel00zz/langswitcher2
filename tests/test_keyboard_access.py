"""Nonprompting, process-local permission reports without system changes."""

from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch

import keyboard_access as access


class KeyboardAccessTests(unittest.TestCase):
    def setUp(self):
        self.ax = patch.object(access, 'AXIsProcessTrusted', return_value=True)
        self.listen = patch.object(access, 'CGPreflightListenEventAccess', return_value=False)
        self.ax_check = self.ax.start()
        self.listen_check = self.listen.start()
        self.addCleanup(self.ax.stop)
        self.addCleanup(self.listen.stop)

    def test_report_separates_actual_keyboard_access_from_permission_preflights(self):
        report = access.collect_access_report(reason='keyboard_events_filtered', details='actual=0x1000')
        self.assertFalse(report.keyboard_access)
        self.assertTrue(report.accessibility)
        self.assertFalse(report.input_monitoring)
        self.assertEqual(report.reason, 'keyboard_events_filtered')
        self.assertEqual(report.details, 'actual=0x1000')
        self.ax_check.assert_called_once_with()
        self.listen_check.assert_called_once_with()

    def test_verified_tap_can_succeed_despite_stale_preflight(self):
        report = access.collect_access_report(keyboard_access=True, reason='verified')
        self.assertTrue(report.keyboard_access)
        self.assertFalse(report.input_monitoring)

    def test_unavailable_accessibility_probe_does_not_invent_permission(self):
        self.ax_check.side_effect = RuntimeError('unavailable')
        with self.assertLogs(access.logger, level='WARNING'):
            report = access.collect_access_report()
        self.assertIsNone(report.accessibility)
        self.assertFalse(report.input_monitoring)

    def test_unavailable_input_probe_does_not_hide_accessibility(self):
        self.listen_check.side_effect = RuntimeError('unavailable')
        with self.assertLogs(access.logger, level='WARNING'):
            report = access.collect_access_report()
        self.assertTrue(report.accessibility)
        self.assertIsNone(report.input_monitoring)

    def test_reports_are_immutable(self):
        report = access.collect_access_report()
        with self.assertRaises(FrozenInstanceError):
            report.keyboard_access = True

    def test_typed_error_preserves_report_and_friendly_recovery_message(self):
        report = access.collect_access_report()
        error = access.KeyboardAccessError(report)
        self.assertIsInstance(error, RuntimeError)
        self.assertIs(error.report, report)
        self.assertIn('Input Monitoring', str(error))
        self.assertIn('Device Control and Data Access', str(error))
        self.assertIn('quit and reopen', str(error))


if __name__ == '__main__':
    unittest.main()
