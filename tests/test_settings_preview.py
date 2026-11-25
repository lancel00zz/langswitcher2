"""Preview ownership/lifecycle without opening a native Settings window."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.settings import PrefsWindow


class SettingsPreviewTests(unittest.TestCase):
    def setUp(self):
        self.window = PrefsWindow.alloc().init()
        self.window.config = SimpleNamespace(flag_overlay=SimpleNamespace(enabled=False))
        self.window.on_save = Mock()
        self.window.on_flag_preview = Mock()
        self.window._flag_preview_active = False
        self.window._preview_session = 0
        self.window._window_open = True
        self.window._saving = False
        self.window._webview_loaded = True
        self.window.webview = Mock()
        self.window.win = Mock()
        self.values = {
            'flag_overlay.enabled': False,
            'flag_overlay.size_percent': '180',
            'flag_overlay.position': 'bottom_right',
            'flag_overlay.opacity_percent': '70',
        }

    def message(self, action='flag_preview_toggle', **extra):
        return dict(action=action, session=self.window._preview_session,
                    values=self.values, **extra)

    def test_explicit_preview_uses_unsaved_values_even_when_checkbox_is_off(self):
        observed_active = []
        self.window.on_flag_preview.side_effect = lambda _: observed_active.append(
            self.window.is_flag_preview_active())
        self.window.handle_save(self.message(active=True))
        self.window.on_flag_preview.assert_called_once_with(self.values)
        self.assertEqual(observed_active, [True])
        self.assertFalse(self.window.config.flag_overlay.enabled)
        self.window.on_save.assert_not_called()

    def test_live_updates_require_active_preview_and_stale_messages_cannot_restart_it(self):
        self.window.handle_save(self.message('flag_preview_update'))
        self.window.on_flag_preview.assert_not_called()
        self.window.handle_save(self.message(active=True))
        self.values['flag_overlay.size_percent'] = '200'
        self.window.handle_save(self.message('flag_preview_update'))
        self.window.on_flag_preview.assert_called_with(self.values)
        old_toggle = self.message(active=True)
        self.window.stop_flag_preview()
        self.window.on_flag_preview.assert_called_with(None)
        self.window.on_flag_preview.reset_mock()
        self.window.handle_save(old_toggle)
        self.window.handle_save(self.message('flag_preview_update'))
        self.window.on_flag_preview.assert_not_called()
        self.assertFalse(self.window.is_flag_preview_active())

    def test_save_stops_before_async_form_read_and_failed_save_allows_new_preview(self):
        self.window.handle_save(self.message(active=True))
        order = []
        self.window.on_flag_preview.side_effect = lambda value: order.append(('preview', value))
        self.window.webview.evaluateJavaScript_completionHandler_.side_effect = (
            lambda script, callback: order.append(('script', script)))
        self.window.save_(None)
        self.assertEqual(order[0], ('preview', None))
        self.assertEqual(order[-1], ('script', 'JSON.stringify(getFormValues())'))
        self.assertTrue(self.window._saving)
        self.window.on_flag_preview.reset_mock()
        self.window.handle_save(self.message(active=True))
        self.window.on_flag_preview.assert_not_called()
        with patch('ui.settings.NSAlert'):
            self.window.process_save(None, 'form error')
        self.assertFalse(self.window._saving)
        self.assertFalse(self.window.is_flag_preview_active())
        self.window.handle_save(self.message(active=True))
        self.window.on_flag_preview.assert_called_once_with(self.values)

    def test_cancel_and_native_close_stop_and_reject_late_preview_or_save(self):
        for close in (self.window.cancel_, self.window.windowWillClose_):
            with self.subTest(close=close):
                self.window._window_open = True
                self.window.handle_save(self.message(active=True))
                self.window.on_flag_preview.reset_mock()
                close(None)
                self.window.on_flag_preview.assert_called_once_with(None)
                self.window.on_flag_preview.reset_mock()
                self.window.handle_save(self.message(active=True))
                self.window.process_save('{}', None)
                self.window.on_flag_preview.assert_not_called()
                self.window.on_save.assert_not_called()
                self.assertFalse(self.window.is_flag_preview_active())


if __name__ == '__main__':
    unittest.main()
