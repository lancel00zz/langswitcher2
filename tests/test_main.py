"""Actionable startup failures without starting an app or showing native UI."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main as entrypoint
from config import Config


class MainTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(Path(self.directory.name) / "settings.json")
        self.config.app.debug_log_path = str(Path(self.directory.name) / "app.log")
        self.app = Mock()
        for name, value in [
            ("get_config", Mock(return_value=self.config)),
            ("setup_logging", Mock()),
            ("LangSwitcherApp", Mock(return_value=self.app)),
            ("show_startup_error", Mock()),
        ]:
            patcher = patch.object(entrypoint, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_normal_run_closes_resources_without_showing_error(self):
        entrypoint.main()
        entrypoint.setup_logging.assert_called_once_with(self.config.app.debug_log_path)
        entrypoint.LangSwitcherApp.assert_called_once_with(self.config)
        self.app.run.assert_called_once_with()
        self.app.close.assert_called_once_with()
        entrypoint.show_startup_error.assert_not_called()

    def test_constructor_failure_is_logged_and_shown_without_run_or_close(self):
        error = RuntimeError(
            "Required keyboard input sources are not enabled. Enable Canadian – CSA "
            "in System Settings > Keyboard > Input Sources, then relaunch LangSwitcher."
        )
        entrypoint.LangSwitcherApp.side_effect = error
        with self.assertLogs(level="ERROR") as captured:
            entrypoint.main()
        self.app.run.assert_not_called()
        self.app.close.assert_not_called()
        entrypoint.show_startup_error.assert_called_once_with(
            error, self.config.app.debug_log_path,
        )
        self.assertIn("LangSwitcher could not start", captured.output[0])
        self.assertIn("Traceback (most recent call last)", captured.output[0])
        self.assertIn("Required keyboard input sources", captured.output[0])

    def test_run_failure_closes_resources_before_showing_error(self):
        error = RuntimeError("native loop failed")
        self.app.run.side_effect = error
        order = Mock()
        order.attach_mock(self.app.close, "close")
        order.attach_mock(entrypoint.show_startup_error, "show")
        with self.assertLogs(level="ERROR"):
            entrypoint.main()
        self.app.close.assert_called_once_with()
        entrypoint.show_startup_error.assert_called_once_with(
            error, self.config.app.debug_log_path,
        )
        self.assertEqual([item[0] for item in order.mock_calls], ["close", "show"])

    def test_dialog_failure_is_logged_without_escaping_to_launcher(self):
        entrypoint.LangSwitcherApp.side_effect = RuntimeError("startup failed")
        entrypoint.show_startup_error.side_effect = RuntimeError("native UI failed")
        with self.assertLogs(level="ERROR") as captured:
            entrypoint.main()
        self.assertTrue(any("Could not display the startup error dialog" in item
                            and "native UI failed" in item for item in captured.output))

    def test_cleanup_failure_is_logged_and_preserves_original_startup_error(self):
        error = RuntimeError("startup failed")
        self.app.run.side_effect = error
        self.app.close.side_effect = RuntimeError("close failed")
        with self.assertLogs(level="ERROR") as captured:
            entrypoint.main()
        self.assertTrue(any("Could not clean up LangSwitcher resources" in item
                            and "close failed" in item for item in captured.output))
        entrypoint.show_startup_error.assert_called_once_with(
            error, self.config.app.debug_log_path,
        )

    def test_keyboard_interrupt_closes_resources_without_startup_error_dialog(self):
        self.app.run.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            entrypoint.main()
        self.app.close.assert_called_once_with()
        entrypoint.show_startup_error.assert_not_called()


class StartupErrorDialogTests(unittest.TestCase):
    def test_native_dialog_uses_actual_condition_and_log_path(self):
        error = RuntimeError(
            "Enable Canadian – CSA in System Settings > Keyboard > Input Sources."
        )
        with patch.object(entrypoint, "NSApplication") as application, \
                patch.object(entrypoint, "NSAlert") as native_alert, \
                patch.object(entrypoint, "NSRunningApplication") as running:
            entrypoint.show_startup_error(error, "/tmp/LangSwitcher.log")
        application.sharedApplication.assert_called_once_with()
        running.currentApplication.return_value.activateWithOptions_.assert_called_once_with(
            entrypoint.NSApplicationActivateIgnoringOtherApps,
        )
        alert = native_alert.alloc.return_value.init.return_value
        alert.setAlertStyle_.assert_called_once_with(entrypoint.NSAlertStyleCritical)
        alert.setMessageText_.assert_called_once_with("LangSwitcher could not start")
        information = alert.setInformativeText_.call_args.args[0]
        self.assertIn(str(error), information)
        self.assertIn("/tmp/LangSwitcher.log", information)
        self.assertNotIn("Accessibility", information)
        self.assertNotIn("permission", information.lower())
        alert.addButtonWithTitle_.assert_called_once_with("Quit")
        alert.runModal.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
