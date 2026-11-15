"""Lifecycle and fail-open behavior without creating a real macOS event tap."""

import threading
import unittest
from unittest.mock import Mock, patch

import keyboard_events as events


class KeyboardEventTapTests(unittest.TestCase):
    def setUp(self):
        self.native = {
            "CGEventTapCreate": Mock(return_value=object()),
            "CFMachPortCreateRunLoopSource": Mock(return_value=object()),
            "CFRunLoopGetMain": Mock(return_value=object()),
            "CFRunLoopAddSource": Mock(),
            "CFRunLoopRemoveSource": Mock(),
            "CGEventTapEnable": Mock(),
            "CFMachPortInvalidate": Mock(),
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
        with self.assertRaisesRegex(RuntimeError, "Privacy & Security > Accessibility"):
            self.tap.start()
        self.native["CFRunLoopAddSource"].assert_not_called()

    def test_native_tap_creation_error_is_reported_without_attaching(self):
        self.native["CGEventTapCreate"].side_effect = OSError("test failure")
        with self.assertRaisesRegex(RuntimeError, "Could not create the keyboard event tap"):
            self.tap.start()
        self.native["CFRunLoopAddSource"].assert_not_called()
        self.assertIsNone(self.tap._tap)

    def test_failed_source_creation_invalidates_allocated_port(self):
        self.native["CFMachPortCreateRunLoopSource"].return_value = None
        with self.assertRaisesRegex(RuntimeError, "run-loop source"):
            self.tap.start()
        self.native["CFMachPortInvalidate"].assert_called_once()
        self.assertIsNone(self.tap._tap)

    def test_failed_attachment_cleans_native_resources(self):
        self.native["CFRunLoopAddSource"].side_effect = RuntimeError("test failure")
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            self.tap.start()
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


if __name__ == "__main__":
    unittest.main()
