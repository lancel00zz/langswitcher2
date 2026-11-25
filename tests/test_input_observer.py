"""Observe lifecycle and queued delivery without registering native observers."""

import threading
import unittest
from unittest.mock import Mock, patch

from switchers import input_observer as observers


class InputSourceObserverTests(unittest.TestCase):
    def setUp(self):
        self.callback = Mock()
        self.observer = observers.InputSourceObserver.alloc().initWithCallback_(self.callback)
        center_patch = patch.object(observers, "NSDistributedNotificationCenter")
        self.center_class = center_patch.start()
        self.addCleanup(center_patch.stop)
        self.center = self.center_class.defaultCenter.return_value
        defer_patch = patch.object(observers.AppHelper, "callAfter")
        self.defer = defer_patch.start()
        self.addCleanup(defer_patch.stop)
        self.addCleanup(self.observer.close)

    def test_start_registers_exact_selected_source_notification_while_inactive(self):
        self.assertIs(self.observer.start(), self.observer)
        self.center.addObserver_selector_name_object_suspensionBehavior_.assert_called_once_with(
            self.observer,
            "inputSourceChanged:",
            "com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged",
            None,
            observers.NSNotificationSuspensionBehaviorDeliverImmediately,
        )
        self.callback.assert_not_called()

    def test_start_is_idempotent(self):
        self.observer.start()
        self.observer.start()
        self.center.addObserver_selector_name_object_suspensionBehavior_.assert_called_once()

    def test_notification_defers_delivery_and_never_reads_payload(self):
        self.observer.start()
        payload = Mock()
        self.observer.inputSourceChanged_(payload)
        self.callback.assert_not_called()
        payload.assert_not_called()
        self.assertEqual(payload.mock_calls, [])
        self.defer.assert_called_once_with(self.observer._deliver)
        self.defer.call_args.args[0]()
        self.callback.assert_called_once_with()

    def test_queued_callback_is_ignored_after_close(self):
        self.observer.start()
        self.observer.inputSourceChanged_(None)
        queued = self.defer.call_args.args[0]
        self.observer.close()
        queued()
        self.callback.assert_not_called()

    def test_unstarted_or_closed_observer_never_queues_callbacks(self):
        self.observer.inputSourceChanged_(None)
        self.observer.start()
        self.observer.close()
        self.observer.inputSourceChanged_(None)
        self.defer.assert_not_called()

    def test_close_removes_registration_once_and_releases_callback(self):
        self.observer.start()
        self.observer.close()
        self.observer.close()
        self.center.removeObserver_name_object_.assert_called_once_with(
            self.observer, observers.SELECTED_INPUT_SOURCE_CHANGED, None,
        )
        self.assertIsNone(self.observer._callback)
        self.assertIsNone(self.observer._center)

    def test_close_before_start_never_registers_or_removes(self):
        self.observer.close()
        self.center_class.defaultCenter.assert_not_called()
        self.center.removeObserver_name_object_.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.observer.start()

    def test_removal_failure_stops_callbacks_and_can_be_retried(self):
        self.observer.start()
        self.observer.inputSourceChanged_(None)
        queued = self.defer.call_args.args[0]
        self.center.removeObserver_name_object_.side_effect = RuntimeError("native error")
        with self.assertRaisesRegex(RuntimeError, "native error"):
            self.observer.close()
        queued()
        self.callback.assert_not_called()
        self.center.removeObserver_name_object_.side_effect = None
        self.observer.close()
        self.assertIsNone(self.observer._center)

    def test_failed_registration_does_not_claim_started_state(self):
        self.center.addObserver_selector_name_object_suspensionBehavior_.side_effect = RuntimeError("native error")
        with self.assertRaisesRegex(RuntimeError, "native error"):
            self.observer.start()
        self.assertFalse(self.observer._started)
        self.observer.inputSourceChanged_(None)
        self.defer.assert_not_called()

    def test_callback_failure_is_logged_without_escaping_delivery(self):
        self.observer.start()
        self.callback.side_effect = RuntimeError("callback failed")
        with self.assertLogs(observers.logger, level="ERROR"):
            self.observer._deliver()

    def test_scheduler_failure_cannot_escape_native_notification_callback(self):
        self.observer.start()
        self.defer.side_effect = RuntimeError("schedule failed")
        with self.assertLogs(observers.logger, level="ERROR"):
            self.observer.inputSourceChanged_(None)

    def test_lifecycle_rejects_background_threads_before_native_calls(self):
        errors = []
        def background():
            for action in (self.observer.start, self.observer.close):
                try:
                    action()
                except RuntimeError as error:
                    errors.append(str(error))
        thread = threading.Thread(target=background)
        thread.start()
        thread.join()
        self.assertEqual(errors, ["Input-source observer must run on the main thread"] * 2)
        self.center_class.defaultCenter.assert_not_called()
        self.center.removeObserver_name_object_.assert_not_called()

    def test_non_callable_callback_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "must be callable"):
            observers.InputSourceObserver.alloc().initWithCallback_(None)


if __name__ == "__main__":
    unittest.main()
