"""Lifecycle and fail-open behavior without creating a real macOS event tap."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import keyboard_events as events
from keyboard_access import AccessReport, KeyboardAccessError


def tap_info(identifier=1, pid=None, mask=0x1c00, enabled=True, options=0, point=1):
    return SimpleNamespace(eventTapID=identifier,
                           tappingProcess=events.os.getpid() if pid is None else pid,
                           eventsOfInterest=mask, enabled=enabled,
                           options=options, tapPoint=point)


class KeyboardEventTapTests(unittest.TestCase):
    def setUp(self):
        self.native = {
            "CGEventTapCreate": Mock(return_value=object()),
            "CFMachPortCreateRunLoopSource": Mock(return_value=object()),
            "CFRunLoopGetMain": Mock(return_value=object()),
            "CFRunLoopAddSource": Mock(),
            "CFRunLoopRemoveSource": Mock(),
            "CGEventTapEnable": Mock(),
            "CGGetEventTapList": Mock(side_effect=[(0, [], 0), (0, [tap_info()], 1)]),
            "CFMachPortInvalidate": Mock(),
            "collect_access_report": Mock(side_effect=lambda **kwargs: AccessReport(
                accessibility=True, input_monitoring=True, **{'keyboard_access': False, **kwargs})),
        }
        self.patch = patch.multiple(events, **self.native)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.callback = Mock(side_effect=lambda _kind, event: event)
        self.tap = events.KeyboardEventTap(self.callback)

    def test_start_creates_active_tap_on_main_run_loop(self):
        self.assertIs(self.tap.start(), self.tap)
        args = self.native["CGEventTapCreate"].call_args.args
        self.assertEqual(args[:3], (
            events.kCGSessionEventTap,
            events.kCGHeadInsertEventTap,
            events.kCGEventTapOptionDefault,
        ))
        self.assertEqual(args[3], (
            events.CGEventMaskBit(events.kCGEventKeyDown)
            | events.CGEventMaskBit(events.kCGEventKeyUp)
            | events.CGEventMaskBit(events.kCGEventFlagsChanged)
        ))
        self.assertIs(args[4], self.tap._native_callback)
        self.native["CFRunLoopAddSource"].assert_called_once_with(
            self.native["CFRunLoopGetMain"].return_value,
            self.native["CFMachPortCreateRunLoopSource"].return_value,
            events.kCFRunLoopCommonModes,
        )
        self.native["CGEventTapEnable"].assert_called_once_with(
            self.native["CGEventTapCreate"].return_value, True,
        )

    def test_start_is_idempotent(self):
        self.tap.start()
        self.tap.start()
        self.native["CGEventTapCreate"].assert_called_once()
        self.native["CFRunLoopAddSource"].assert_called_once()

    def test_modified_event_is_returned_before_forwarding(self):
        self.tap.start()
        event, result = object(), object()
        self.callback.side_effect = None
        self.callback.return_value = result
        self.assertIs(self.tap._handle_event(None, events.kCGEventKeyDown, event, None), result)
        self.callback.assert_called_once_with(events.kCGEventKeyDown, event)

    def test_callback_none_result_cannot_suppress_input(self):
        self.tap.start()
        self.callback.side_effect = None
        self.callback.return_value = None
        event = object()
        self.assertIs(self.tap._handle_event(None, events.kCGEventKeyDown, event, None), event)

    def test_callback_exception_passes_original_input_through(self):
        self.tap.start()
        self.callback.side_effect = RuntimeError("test failure")
        event = object()
        with self.assertLogs(events.logger, level="ERROR"):
            result = self.tap._handle_event(None, events.kCGEventKeyDown, event, None)
        self.assertIs(result, event)

    def test_disabled_notifications_reenable_without_parsing(self):
        self.tap.start()
        self.native["CGEventTapEnable"].reset_mock()
        for event_type in (
            events.kCGEventTapDisabledByTimeout,
            events.kCGEventTapDisabledByUserInput,
        ):
            with self.subTest(event_type=event_type):
                self.assertIsNone(self.tap._handle_event(None, event_type, None, None))
        self.callback.assert_not_called()
        self.assertEqual(self.native["CGEventTapEnable"].call_count, 2)

    def test_failed_reenable_does_not_escape_native_callback(self):
        self.tap.start()
        self.native["CGEventTapEnable"].side_effect = RuntimeError("test failure")
        with self.assertLogs(events.logger, level="ERROR"):
            result = self.tap._handle_event(None, events.kCGEventTapDisabledByTimeout, None, None)
        self.assertIsNone(result)
        self.callback.assert_not_called()

    def test_stop_disables_removes_and_invalidates_tap(self):
        self.tap.start()
        tap = self.native["CGEventTapCreate"].return_value
        source = self.native["CFMachPortCreateRunLoopSource"].return_value
        run_loop = self.native["CFRunLoopGetMain"].return_value
        self.native["CGEventTapEnable"].reset_mock()
        self.tap.stop()
        self.native["CGEventTapEnable"].assert_called_once_with(tap, False)
        self.native["CFRunLoopRemoveSource"].assert_called_once_with(
            run_loop, source, events.kCFRunLoopCommonModes,
        )
        self.native["CFMachPortInvalidate"].assert_called_once_with(tap)
        self.assertIsNone(self.tap._tap)
        self.assertIsNone(self.tap._source)
        self.assertIsNone(self.tap._run_loop)
        self.tap.stop()
        self.native["CFMachPortInvalidate"].assert_called_once()

    def test_stop_continues_cleanup_when_disabling_fails(self):
        self.tap.start()
        self.native["CGEventTapEnable"].side_effect = RuntimeError("test failure")
        with self.assertLogs(events.logger, level="ERROR"):
            self.tap.stop()
        self.native["CFRunLoopRemoveSource"].assert_called_once()
        self.native["CFMachPortInvalidate"].assert_called_once()

    def test_stopped_callback_passes_input_through_without_calling_user(self):
        self.tap.start()
        self.tap.stop()
        event = object()
        self.assertIs(self.tap._handle_event(None, events.kCGEventKeyDown, event, None), event)
        self.callback.assert_not_called()

    def test_missing_permission_has_actionable_error(self):
        self.native["CGEventTapCreate"].return_value = None
        with self.assertRaisesRegex(KeyboardAccessError, "Privacy & Security") as caught:
            self.tap.start()
        self.assertFalse(caught.exception.report.keyboard_access)
        self.assertEqual(caught.exception.report.reason, 'tap_missing')
        self.native["CFRunLoopAddSource"].assert_not_called()

    def test_native_tap_creation_error_is_reported_without_attaching(self):
        self.native["CGEventTapCreate"].side_effect = OSError("test failure")
        with self.assertRaisesRegex(RuntimeError, "Could not create the keyboard event tap") as caught:
            self.tap.start()
        self.assertNotIsInstance(caught.exception, KeyboardAccessError)
        self.native["CFRunLoopAddSource"].assert_not_called()
        self.assertIsNone(self.tap._tap)

    def test_failed_source_creation_invalidates_allocated_port(self):
        self.native["CFMachPortCreateRunLoopSource"].return_value = None
        with self.assertRaisesRegex(RuntimeError, "run-loop source") as caught:
            self.tap.start()
        self.assertNotIsInstance(caught.exception, KeyboardAccessError)
        self.native["CFMachPortInvalidate"].assert_called_once()
        self.assertIsNone(self.tap._tap)

    def test_failed_attachment_cleans_native_resources(self):
        self.native["CFRunLoopAddSource"].side_effect = RuntimeError("test failure")
        with self.assertRaisesRegex(RuntimeError, "test failure") as caught:
            self.tap.start()
        self.assertNotIsInstance(caught.exception, KeyboardAccessError)
        self.native["CFMachPortInvalidate"].assert_called_once()
        self.assertIsNone(self.tap._tap)

    def test_start_on_background_thread_fails_before_native_calls(self):
        errors = []

        def start():
            try:
                self.tap.start()
            except RuntimeError as error:
                errors.append(str(error))

        thread = threading.Thread(target=start)
        thread.start()
        thread.join()
        self.assertEqual(errors, ["Keyboard event tap must run on the main thread"])
        self.native["CGEventTapCreate"].assert_not_called()

    def test_success_requires_verified_complete_enabled_keyboard_mask(self):
        self.tap.start()
        self.assertTrue(self.tap.report.keyboard_access)
        self.assertEqual(self.tap.report.reason, 'verified')
        self.assertIn('actual_mask=0x1c00', self.tap.report.details)

    def test_modifier_only_tap_is_rejected_and_completely_cleaned(self):
        self.native['CGGetEventTapList'].side_effect = [(0, [], 0), (0, [tap_info(mask=0x1000)], 1)]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'keyboard_events_filtered')
        self.assertIn('actual_mask=0x1000', caught.exception.report.details)
        self.assertFalse(caught.exception.report.keyboard_access)
        # Even all-green preflight checks cannot overrule the actual mask.
        self.assertTrue(caught.exception.report.accessibility)
        self.assertTrue(caught.exception.report.input_monitoring)
        self.assertIsNone(self.tap._tap)
        self.native['CFRunLoopRemoveSource'].assert_called_once()
        self.native['CFMachPortInvalidate'].assert_called_once()

    def test_old_own_tap_does_not_hide_new_filtered_tap(self):
        old = tap_info(identifier=5)
        filtered = tap_info(identifier=9, mask=0x1000)
        self.native['CGGetEventTapList'].side_effect = [(0, [old], 1), (0, [old, filtered], 2)]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'keyboard_events_filtered')

    def test_other_process_tap_cannot_establish_access(self):
        other = tap_info(pid=events.os.getpid() + 1)
        self.native['CGGetEventTapList'].side_effect = [(0, [], 0), (0, [other], 1)]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'verification_unavailable')
        self.native['CFMachPortInvalidate'].assert_called_once()

    def test_ambiguous_new_own_taps_are_not_assumed_to_be_ours(self):
        self.native['CGGetEventTapList'].side_effect = [
            (0, [], 0), (0, [tap_info(1), tap_info(2)], 2),
        ]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'verification_unavailable')

    def test_disabled_tap_is_rejected_after_enable(self):
        self.native['CGGetEventTapList'].side_effect = [(0, [], 0), (0, [tap_info(enabled=False)], 1)]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'tap_disabled')

    def test_wrong_tap_options_do_not_establish_filter_access(self):
        self.native['CGGetEventTapList'].side_effect = [(0, [], 0), (0, [tap_info(options=1)], 1)]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'verification_unavailable')

    def test_metadata_failure_before_creation_does_not_allocate_tap(self):
        self.native['CGGetEventTapList'].side_effect = OSError('metadata unavailable')
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'verification_unavailable')
        self.native['CGEventTapCreate'].assert_not_called()

    def test_metadata_failure_after_creation_cleans_resources(self):
        self.native['CGGetEventTapList'].side_effect = [(0, [], 0), (1001, [], 0)]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'verification_unavailable')
        self.native['CFRunLoopRemoveSource'].assert_called_once()
        self.native['CFMachPortInvalidate'].assert_called_once()

    def test_incomplete_metadata_cannot_verify_access(self):
        self.native['CGGetEventTapList'].side_effect = [(0, [], 0), (0, [tap_info()], 2)]
        with self.assertRaises(KeyboardAccessError) as caught:
            self.tap.start()
        self.assertEqual(caught.exception.report.reason, 'verification_unavailable')

    def test_failed_access_can_be_retried_after_recovery(self):
        self.native['CGGetEventTapList'].side_effect = [
            (0, [], 0), (0, [tap_info(mask=0x1000)], 1),
            (0, [], 0), (0, [tap_info(identifier=2)], 1),
        ]
        with self.assertRaises(KeyboardAccessError):
            self.tap.start()
        self.assertIs(self.tap.start(), self.tap)
        self.assertTrue(self.tap.report.keyboard_access)


if __name__ == "__main__":
    unittest.main()
