import unittest
from unittest.mock import patch

from switchers.keyboard import KeyboardSwitcher

LAYOUTS = {'en': ('com.apple.keylayout.US', 'US'),
           'fr': ('com.apple.keylayout.Canadian-CSA', 'FR')}


class NativeSwitcherTests(unittest.TestCase):
    def setUp(self):
        factory = patch('switchers.keyboard.NativeInputSources')
        self.native = factory.start().return_value
        self.addCleanup(factory.stop)
        self.switcher = KeyboardSwitcher(LAYOUTS)

    def test_read_select_and_translation_use_native_backend(self):
        self.native.get_current_layout_id.return_value = LAYOUTS['en'][0]
        self.assertEqual(self.switcher.get_current_layout(), 'en')
        self.native.select.return_value = True
        self.assertEqual(self.switcher.toggle('en', ['en', 'fr']), 'fr')
        self.native.select.assert_called_once_with(LAYOUTS['fr'][0])
        self.native.translate_key.return_value = 'é'
        self.assertEqual(self.switcher.translate_key(44, 0, 'fr'), 'é')
        self.native.translate_key.assert_called_once_with(LAYOUTS['fr'][0], 44, 0)

    def test_failed_selection_does_not_change_cached_language(self):
        self.native.get_current_layout_id.return_value = LAYOUTS['en'][0]
        self.switcher.get_current_layout()
        self.native.select.return_value = False
        self.assertIsNone(self.switcher.toggle('en', ['en', 'fr']))
        self.assertEqual(self.switcher._current_lang, 'en')

    def test_initialization_failure_is_not_hidden_by_subprocess_fallback(self):
        with patch('switchers.keyboard.NativeInputSources', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                KeyboardSwitcher(LAYOUTS)

    def test_close_releases_native_resources(self):
        self.switcher.close()
        self.native.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
