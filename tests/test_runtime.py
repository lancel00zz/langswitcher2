"""Exercise real app handlers without starting an app, listener, or layout switch."""
import tempfile
import threading
import unittest
from concurrent.futures import Future
import Quartz
from pathlib import Path
from unittest.mock import Mock, patch

from pynput import keyboard
from config import Config
from ui.menubar import LangSwitcherApp


class ImmediateExecutor:
    def submit(self, callback, *args):
        future = Future()
        try:
            future.set_result(callback(*args))
        except Exception as error:
            future.set_exception(error)
        return future


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(Path(self.directory.name) / 'settings.json')
        self.app = object.__new__(LangSwitcherApp)
        self.app.config = self.config
        self.app._state_lock = threading.RLock()
        self.app._shortcut_keys_down = set()
        self.app._expected_retry = None
        self.app._rewritten_keyups = {}
        self.app._detection_epoch = 0
        self.app._word_executor = ImmediateExecutor()
        callbacks = patch('ui.menubar.AppHelper.callAfter', lambda callback, *args: callback(*args))
        callbacks.start()
        self.addCleanup(callbacks.stop)
        self.app.language_detector, self.app.frustration_detector = self.app._make_detectors(self.config)
        self.app.word_buffer = ''
        self.app.current_lang = 'en'
        self.app.detecting = True
        self.app.keyboard_switcher = Mock()
        self.app.keyboard_switcher.sync_state.return_value = 'en'
        self.app.keyboard_switcher.get_icon.return_value = 'flag'
        self.app._update_icon = Mock()

    def test_saved_settings_change_both_running_detectors_without_restart(self):
        values = self.config.editable_values()
        values.update({'detection.buffer_size': '7', 'detection.switch_threshold': '5',
                       'detection.min_word_length': '4',
                       'detection.model_confidence_threshold': '0.9',
                       'detection.fallback_to_buffer_on_ambiguous': False,
                       'frustration.enabled': False})
        self.app.word_buffer = 'pending'
        self.app.apply_settings(values)
        language = self.app.language_detector
        self.assertEqual((language.buffer_size, language.lang_buffer.maxlen, language.switch_threshold,
                          language.min_word_length, language.confidence_threshold), (7, 7, 5, 4, 0.9))
        self.assertFalse(language.fallback_to_buffer)
        self.assertFalse(self.app.config.frustration.enabled)
        self.assertEqual(self.app.word_buffer, '')
        self.assertEqual(Config(self.config.config_path).editable_values(), self.app.config.editable_values())

    def test_failed_save_keeps_live_settings_and_both_detectors(self):
        old_language = self.app.language_detector
        old_frustration = self.app.frustration_detector
        values = self.config.editable_values()
        values['detection.switch_threshold'] = '4'
        with patch.object(Config, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.app.apply_settings(values)
        self.assertIs(self.app.config, self.config)
        self.assertIs(self.app.language_detector, old_language)
        self.assertIs(self.app.frustration_detector, old_frustration)
        self.assertEqual(self.app.language_detector.switch_threshold, 3)

    def test_detector_preparation_failure_does_not_write_settings(self):
        with patch.object(self.app, '_make_detectors', side_effect=RuntimeError('init failed')):
            with self.assertRaises(RuntimeError):
                self.app.apply_settings(self.config.editable_values())
        self.assertFalse(self.config.config_path.exists())
        self.assertIs(self.app.config, self.config)

    def test_backspace_is_tracked_once_and_forward_delete_never_acts_as_backspace(self):
        detector = Mock()
        detector.track_key_event.return_value = False
        self.app.frustration_detector = detector
        self.app.word_buffer = 'word'
        self.app._on_press(keyboard.Key.backspace)
        detector.track_key_event.assert_called_once_with('backspace', 'backspace')
        self.assertEqual(self.app.word_buffer, 'wor')
        detector.reset_mock()
        self.app._on_press(keyboard.Key.delete)
        detector.track_key_event.assert_not_called()
        detector.clear_history.assert_called_once()

    def test_courant_slash_backspace_switches_before_first_retry(self):
        for char in 'courant ':
            self.app._on_press(keyboard.KeyCode.from_char(char))
        slash = keyboard.KeyCode.from_char('/', vk=44)
        self.app.keyboard_switcher.toggle.return_value = 'fr'
        with patch('detectors.frustration.time.monotonic', side_effect=[10.0, 10.1, 10.2]):
            self.app._on_press(slash)
            self.app.keyboard_switcher.toggle.assert_not_called()
            self.app._on_press(keyboard.Key.backspace)
            # The layout must already be French before the retry is pressed.
            self.app.keyboard_switcher.toggle.assert_called_once_with('en', ['en', 'fr'])
            self.assertEqual(self.app.current_lang, 'fr')
            self.assertEqual(self.app.word_buffer, '')
            self.app._on_press(keyboard.KeyCode.from_char('é', vk=44))
        self.app.keyboard_switcher.toggle.assert_called_once()
        self.assertEqual(self.app.word_buffer, 'é')

    def test_french_correction_switches_back_before_next_slash(self):
        self.app.current_lang = 'fr'
        self.app.keyboard_switcher.sync_state.return_value = 'fr'
        self.app.keyboard_switcher.toggle.return_value = 'en'
        self.app._on_press(keyboard.KeyCode.from_char('é', vk=44))
        self.app._on_press(keyboard.Key.backspace)
        self.app.keyboard_switcher.toggle.assert_called_once_with('fr', ['en', 'fr'])
        self.assertEqual(self.app.current_lang, 'en')
        self.app._on_press(keyboard.KeyCode.from_char('/', vk=44))
        self.app.keyboard_switcher.toggle.assert_called_once()

    def test_failed_switch_still_removes_deleted_character_from_buffer(self):
        self.app.word_buffer = 'l'
        self.app.keyboard_switcher.toggle.return_value = None
        self.app._on_press(keyboard.KeyCode.from_char("'", vk=39))
        self.assertEqual(self.app.word_buffer, "l'")
        self.app._on_press(keyboard.Key.backspace)
        self.assertEqual(self.app.word_buffer, 'l')
        self.assertEqual(self.app.current_lang, 'en')

    def test_ordinary_letters_break_correction_gesture(self):
        self.app._on_press(keyboard.KeyCode.from_vk(44))
        self.app._on_press(keyboard.KeyCode.from_char('a'))
        self.app._on_press(keyboard.Key.backspace)
        self.app._on_press(keyboard.KeyCode.from_vk(44))
        self.app.keyboard_switcher.toggle.assert_not_called()

    def test_command_shortcuts_are_not_treated_as_typed_words(self):
        self.app.word_buffer = 'pending'
        self.app._on_press(keyboard.Key.cmd)
        self.app._on_press(keyboard.KeyCode.from_char('a'))
        self.assertEqual(self.app.word_buffer, '')
        self.app._on_release(keyboard.Key.cmd)
        self.app._on_press(keyboard.KeyCode.from_char('a'))
        self.assertEqual(self.app.word_buffer, 'a')

    def test_external_change_clears_history_before_classifying_word(self):
        self.app.language_detector.lang_buffer.extend(['en', 'en', 'en'])
        self.app.word_buffer = 'on'
        self.app.keyboard_switcher.sync_state.return_value = 'fr'
        self.app._process_word_buffer()
        self.assertEqual(self.app.current_lang, 'fr')
        self.assertEqual(self.app.language_detector.get_buffer_state(), [])
        self.app.keyboard_switcher.switch_to.assert_not_called()

    def test_word_from_before_manual_change_cannot_undo_selection(self):
        self.app.language_detector.switch_threshold = 1
        self.app.word_buffer = 'the'
        self.app.keyboard_switcher.sync_state.return_value = 'fr'
        self.app._process_word_buffer()
        self.app.keyboard_switcher.switch_to.assert_not_called()
        self.assertEqual(self.app.current_lang, 'fr')
        self.assertEqual(self.app.language_detector.get_buffer_state(), [])

    def test_external_change_between_decision_and_switch_discards_decision(self):
        self.app.keyboard_switcher.sync_state.return_value = 'fr'
        self.app._switch_to_language('fr')
        self.app.keyboard_switcher.switch_to.assert_not_called()

    def test_pause_clears_partial_words_and_language_evidence(self):
        self.app.word_buffer = 'partial'
        self.app.language_detector.lang_buffer.extend(['fr', 'fr'])
        with patch('ui.menubar.rumps.notification'):
            self.app.toggle(Mock())
        self.assertFalse(self.app.detecting)
        self.assertEqual(self.app.word_buffer, '')
        self.assertEqual(self.app.language_detector.get_buffer_state(), [])

    @staticmethod
    def raw_key(vk, text='', down=True, flags=0):
        event = Quartz.CGEventCreateKeyboardEvent(None, vk, down)
        Quartz.CGEventSetFlags(event, flags)
        if text:
            Quartz.CGEventKeyboardSetUnicodeString(event, len(text.encode('utf-16-le')) // 2, text)
        return event

    @staticmethod
    def text(event):
        return Quartz.CGEventKeyboardGetUnicodeString(event, 100, None, None)[1]

    def setup_virtual_layouts(self):
        actual = {'language': 'en'}
        def toggle(current, available):
            actual['language'] = 'fr' if current == 'en' else 'en'
            return actual['language']
        self.app.keyboard_switcher.toggle.side_effect = toggle
        self.app.keyboard_switcher.sync_state.side_effect = lambda current: actual['language']
        self.app.keyboard_switcher.get_current_layout.side_effect = lambda: actual['language']
        self.app.keyboard_switcher.translate_key.side_effect = (
            lambda vk, flags, lang: ('É' if flags & Quartz.kCGEventFlagMaskShift else 'é')
            if lang == 'fr' else '/')
        return actual

    def test_pretranslated_fast_retries_alternate_without_any_sleep(self):
        self.setup_virtual_layouts()
        # All characters are translated as US *before* any switch. This
        # reproduces queued stale event text, rather than supplying the answer.
        events = [self.raw_key(44, '/')]
        for _ in range(100):
            events.extend([self.raw_key(51), self.raw_key(44, '/')])
        visible = ''
        observed = []
        for event in events:
            self.assertIs(self.app._intercept_event(Quartz.kCGEventKeyDown, event), event)
            vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if vk == 51:
                visible = visible[:-1]
            else:
                visible += self.text(event)
                observed.append(visible)
        self.assertEqual(observed, ['/' if i % 2 == 0 else 'é' for i in range(101)])
        self.assertEqual(self.app.keyboard_switcher.toggle.call_count, 100)

    def test_retry_uses_shift_flags_and_matches_keyup(self):
        self.setup_virtual_layouts()
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, '/'))
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(51))
        down = self.raw_key(44, '?', flags=Quartz.kCGEventFlagMaskShift)
        up = self.raw_key(44, '?', down=False, flags=Quartz.kCGEventFlagMaskShift)
        self.app._intercept_event(Quartz.kCGEventKeyDown, down)
        self.app._intercept_event(Quartz.kCGEventKeyUp, up)
        self.assertEqual(self.text(down), 'É')
        self.assertEqual(self.text(up), 'É')

    def test_command_shortcut_is_never_rewritten_as_retry(self):
        self.setup_virtual_layouts()
        self.app._expected_retry = (44, 'fr')
        event = self.raw_key(44, '/', flags=Quartz.kCGEventFlagMaskCommand)
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.assertEqual(self.text(event), '/')
        self.app.keyboard_switcher.translate_key.assert_not_called()
        self.assertIsNone(self.app._expected_retry)

    def test_paused_input_is_never_rewritten(self):
        self.app.detecting = False
        self.app._expected_retry = (44, 'fr')
        event = self.raw_key(44, '/')
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.assertEqual(self.text(event), '/')
        self.app.keyboard_switcher.translate_key.assert_not_called()

    def test_manual_menu_change_supersedes_pending_retry(self):
        actual = self.setup_virtual_layouts()
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, '/'))
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(51))
        actual['language'] = 'en'
        event = self.raw_key(44, '/')
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.assertEqual(self.text(event), '/')
        self.assertEqual(self.app.current_lang, 'en')
        self.app.keyboard_switcher.translate_key.assert_not_called()

    def test_option_backspace_deletes_word_without_switching(self):
        self.setup_virtual_layouts()
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, '/'))
        event = self.raw_key(51, flags=Quartz.kCGEventFlagMaskAlternate)
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.app.keyboard_switcher.toggle.assert_not_called()
        self.assertEqual(self.app.frustration_detector.key_history, [])
        self.assertEqual(self.app.word_buffer, '')

    def test_language_work_is_queued_outside_keyboard_event(self):
        self.app._word_executor = Mock()
        future = Future()
        self.app._word_executor.submit.return_value = future
        self.app.word_buffer = 'bonjour'
        with patch.object(self.app.language_detector, 'detect') as detect:
            self.app._process_word_buffer()
            detect.assert_not_called()
        self.app._word_executor.submit.assert_called_once()
        self.assertEqual(self.app.word_buffer, '')

    def test_old_worker_result_cannot_undo_a_correction(self):
        detector = self.app.language_detector
        epoch = self.app._detection_epoch
        result = Future()
        result.set_result('fr')
        self.app._reset_detection()
        self.app._finish_word(result, detector, epoch, 'bonjour')
        self.app.keyboard_switcher.switch_to.assert_not_called()


if __name__ == '__main__':
    unittest.main()
