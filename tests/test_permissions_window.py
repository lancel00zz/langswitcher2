"""Permission instructions and Settings links, without opening native windows."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui import permissions_window as permissions


def report(ready=False, accessibility=False, input_monitoring=False):
    return SimpleNamespace(
        keyboard_access=ready,
        accessibility=accessibility,
        input_monitoring=input_monitoring,
        reason="Partial keyboard access",
        details="requested_mask=7168 actual_mask=4096",
    )


class PermissionWindowCopyTests(unittest.TestCase):
    def test_os_27_uses_current_control_permission_name(self):
        self.assertEqual(permissions.control_permission_label(27), "Device Control and Data Access")
        self.assertEqual(permissions.control_permission_label(28), "Device Control and Data Access")
        self.assertEqual(permissions.control_permission_label(26), "Accessibility")

    def test_os_version_is_read_from_native_process_info_when_unspecified(self):
        with patch.object(permissions, "NSProcessInfo") as process_info:
            process_info.processInfo.return_value.operatingSystemVersion.return_value.majorVersion = 27
            self.assertEqual(permissions.control_permission_label(), "Device Control and Data Access")

    def test_os_version_can_be_a_plain_pyobjc_tuple(self):
        with patch.object(permissions, "NSProcessInfo") as process_info:
            version = process_info.processInfo.return_value.operatingSystemVersion
            version.return_value = (27, 2, 1)
            self.assertEqual(permissions.control_permission_label(), "Device Control and Data Access")
            version.return_value = (26, 4, 0)
            self.assertEqual(permissions.control_permission_label(), "Accessibility")

    def test_running_app_path_uses_main_bundle_only_when_frozen(self):
        with patch.object(permissions.sys, "frozen", "macosx_app", create=True), \
                patch.object(permissions, "NSBundle") as bundle:
            bundle.mainBundle.return_value.bundlePath.return_value = "/Applications/LangSwitcher.app"
            self.assertEqual(permissions.running_application_path(), "/Applications/LangSwitcher.app")

    def test_source_mode_does_not_claim_python_bundle_is_langswitcher(self):
        with patch.object(permissions.sys, "frozen", False, create=True), \
                patch.object(permissions, "NSBundle") as bundle:
            bundle.mainBundle.return_value.bundlePath.return_value = "/Python.framework/Resources/Python.app"
            self.assertIsNone(permissions.running_application_path())
            bundle.mainBundle.assert_not_called()

    def test_unexpected_bundle_path_does_not_invent_an_app_location(self):
        with patch.object(permissions.sys, "frozen", True, create=True), \
                patch.object(permissions, "NSBundle") as bundle:
            bundle.mainBundle.return_value.bundlePath.return_value = "/usr/local/bin"
            self.assertIsNone(permissions.running_application_path())

    def test_unhealthy_copy_explains_remove_readd_enable_and_relaunch(self):
        path = "/Applications/My Apps/LangSwitcher.app"
        copy = permissions.window_copy(report(), path, "Device Control and Data Access")
        self.assertIn("needs attention", copy["title"])
        self.assertEqual(copy["location"], path)
        self.assertIn("Input Monitoring and Device Control and Data Access", copy["steps"])
        self.assertIn("In each list", copy["steps"])
        self.assertIn("minus (−)", copy["steps"])
        self.assertIn("plus (+)", copy["steps"])
        self.assertIn("exact running app", copy["steps"])
        self.assertIn("turn its switch on", copy["steps"])
        self.assertIn("Quit LangSwitcher", copy["steps"])
        self.assertIn("reopen that same app", copy["steps"])

    def test_healthy_copy_does_not_recommend_resetting_working_permissions(self):
        copy = permissions.window_copy(report(True, True, True), "/Applications/LangSwitcher.app", "Accessibility")
        self.assertEqual(copy["title"], "Keyboard access is ready")
        self.assertIn("No permission setup is needed", copy["summary"])
        self.assertNotIn("plus (+)", copy["steps"])
        self.assertIn("Only remove and re-add permissions when access needs attention", copy["steps"])

    def test_unknown_preflights_are_not_presented_as_denials(self):
        copy = permissions.window_copy(report(accessibility=None, input_monitoring=None), None, "Accessibility")
        self.assertEqual(copy["statuses"], "Input Monitoring: Not confirmed\nAccessibility: Not confirmed")

    def test_statuses_distinguish_allowed_from_not_allowed(self):
        copy = permissions.window_copy(report(accessibility=True), None, "Accessibility")
        self.assertEqual(copy["statuses"], "Input Monitoring: Not allowed\nAccessibility: Allowed")

    def test_source_mode_has_separate_honest_recovery_steps(self):
        copy = permissions.window_copy(report(), None, "Accessibility")
        self.assertIn("Source mode (Python)", copy["location"])
        self.assertIn("no packaged LangSwitcher.app is running", copy["location"])
        self.assertIn("Quit this source or test copy", copy["steps"])
        self.assertIn("Open the built LangSwitcher.app", copy["steps"])
        self.assertNotIn("exact running app shown above", copy["steps"])

    def test_technical_diagnostics_are_not_exposed_in_product_copy(self):
        copy = permissions.window_copy(report(), "/Applications/LangSwitcher.app", "Accessibility")
        rendered = " ".join(copy.values())
        self.assertNotIn("7168", rendered)
        self.assertNotIn("4096", rendered)
        self.assertNotIn("mask", rendered)

    def test_machine_reasons_have_friendly_explanations(self):
        for reason in ("tap_missing", "keyboard_events_filtered", "tap_disabled", "verification_unavailable"):
            current_report = report()
            current_report.reason = reason
            copy = permissions.window_copy(current_report, "/Applications/LangSwitcher.app", "Accessibility")
            self.assertNotIn(reason, " ".join(copy.values()))
            self.assertIn("Automatic switching is unavailable", copy["summary"])

    def test_actual_keyboard_access_overrides_missing_separate_monitoring_grant(self):
        copy = permissions.window_copy(report(True, True, False), "/Applications/LangSwitcher.app", "Accessibility")
        self.assertEqual(copy["title"], "Keyboard access is ready")
        self.assertIn("No permission setup is needed", copy["summary"])
        self.assertIn("keyboard access is working", copy["statuses"])

    def test_filtered_events_with_both_approvals_explain_stale_version_grant(self):
        current_report = report(False, True, True)
        current_report.reason = "keyboard_events_filtered"
        copy = permissions.window_copy(current_report, "/Applications/LangSwitcher.app", "Accessibility")
        self.assertIn("approval from an older app version", copy["summary"])
        self.assertIn("even when both switches are on", copy["summary"])
        self.assertIn("Remove and re-add this copy", copy["summary"])
        self.assertNotIn("keyboard_events_filtered", copy["summary"])

    def test_unexpected_error_reason_is_not_rendered_as_technical_copy(self):
        current_report = report()
        current_report.reason = "CFMachPortCreate failed: internal status 123"
        copy = permissions.window_copy(current_report, None, "Accessibility")
        self.assertNotIn("CFMachPort", " ".join(copy.values()))
        self.assertIn("could not confirm keyboard access", copy["summary"])

    def test_failed_check_recommends_relaunch_and_console_without_permission_reset(self):
        current_report = report(False, True, True)
        current_report.reason = "check_failed"
        copy = permissions.window_copy(current_report, "/Applications/LangSwitcher.app", "Accessibility")
        self.assertIn("could not finish checking", copy["summary"])
        self.assertIn("Quit LangSwitcher", copy["steps"])
        self.assertIn("reopen the same copy", copy["steps"])
        self.assertIn("Open Debug Console", copy["steps"])
        self.assertIn("Keep your existing permission settings", copy["steps"])
        self.assertNotIn("minus", copy["steps"])
        self.assertNotIn("plus", copy["steps"])
        self.assertNotIn("re-add", copy["steps"])


class PermissionSettingsLinkTests(unittest.TestCase):
    def test_both_buttons_open_exact_permission_panes(self):
        expected = {
            "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
            "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        }
        for pane, link in expected.items():
            with self.subTest(pane=pane), patch.object(permissions, "NSWorkspace") as workspace, \
                    patch.object(permissions, "NSURL") as url:
                native_url = object()
                url.URLWithString_.return_value = native_url
                workspace.sharedWorkspace.return_value.openURL_.return_value = True
                self.assertTrue(permissions.open_permission_settings(pane))
                url.URLWithString_.assert_called_once_with(link)
                workspace.sharedWorkspace.return_value.openURL_.assert_called_once_with(native_url)

    def test_settings_open_failure_is_reported_to_caller(self):
        with patch.object(permissions, "NSWorkspace") as workspace:
            workspace.sharedWorkspace.return_value.openURL_.return_value = False
            self.assertFalse(permissions.open_permission_settings("input_monitoring"))

    def test_unknown_pane_never_opens_a_url(self):
        with patch.object(permissions, "NSWorkspace") as workspace:
            with self.assertRaises(KeyError):
                permissions.open_permission_settings("reset_permissions")
            workspace.sharedWorkspace.assert_not_called()

    def test_settings_callback_exception_has_friendly_recovery_message(self):
        window = SimpleNamespace(_footer_field=Mock())
        with patch.object(permissions, "open_permission_settings", side_effect=RuntimeError("native error")), \
                self.assertLogs(permissions.logger, level="ERROR"):
            permissions.KeyboardAccessWindow._open_settings(window, "input_monitoring")
        message = window._footer_field.setStringValue_.call_args.args[0]
        self.assertIn("Open Privacy & Security", message)
        self.assertNotIn("native error", message)


if __name__ == "__main__":
    unittest.main()
