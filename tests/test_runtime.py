"""Exercise real app handlers without starting an app, listener, or layout switch."""
import tempfile
import threading
import unittest
from concurrent.futures import Future
from contextlib import ExitStack
import Quartz
from pathlib import Path
from unittest.mock import Mock, patch

from pynput import keyboard
from config import Config
from ui.menubar import LangSwitcherApp
from keyboard_access import AccessReport, KeyboardAccessError


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
        self.app._pending_correction = None
        self.now = [10.0]
        clock = patch('ui.menubar.time.monotonic', lambda: self.now[0])
        clock.start()
        self.addCleanup(clock.stop)
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
        self.app._access_ready = True
        self.app._closed = False
        self.app._layout_overlay = Mock()
        self.app._flag_preview_overlay = None
        self.app._flag_preview_owner = None
        self.app._layout_feedback_epoch = 0
        self.app._menu = {'Show Keyboard Switch Flag': Mock()}
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
                       'frustration.enabled': False,
                       'flag_overlay.enabled': False,
                       'flag_overlay.size_percent': '190',
                       'flag_overlay.position': 'top_left',
                       'flag_overlay.opacity_percent': '35'})
        self.app.word_buffer = 'pending'
        self.app.apply_settings(values)
        language = self.app.language_detector
        self.assertEqual((language.buffer_size, language.lang_buffer.maxlen, language.switch_threshold,
                          language.min_word_length, language.confidence_threshold), (7, 7, 5, 4, 0.9))
        self.assertFalse(language.fallback_to_buffer)
        self.assertFalse(self.app.config.frustration.enabled)
        self.assertFalse(self.app.config.flag_overlay.enabled)
        self.assertEqual((self.app.config.flag_overlay.size_percent,
                          self.app.config.flag_overlay.position,
                          self.app.config.flag_overlay.opacity_percent), (190, 'top_left', 35))
        self.app._layout_overlay.configure.assert_called_once_with(self.app.config.flag_overlay)
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

    def test_flag_menu_toggle_persists_and_syncs_settings_without_resetting_detection(self):
        language, frustration = self.app.language_detector, self.app.frustration_detector
        self.app.prefs_window = Mock()
        self.app.toggle_flag_view(Mock())
        self.assertFalse(self.app.config.flag_overlay.enabled)
        self.assertFalse(Config(self.config.config_path).flag_overlay.enabled)
        self.assertEqual(self.app.menu['Show Keyboard Switch Flag'].state, 0)
        self.app.prefs_window.set_flag_enabled.assert_called_once_with(False)
        self.assertTrue(self.app.detecting)
        self.assertIs(self.app.language_detector, language)
        self.assertIs(self.app.frustration_detector, frustration)
        self.app._queue_layout_feedback('fr')
        self.app._layout_overlay.show_language.assert_not_called()

    def test_failed_menu_toggle_save_keeps_live_flag_visibility(self):
        with patch.object(Config, 'save', side_effect=OSError('disk full')), \
                patch('ui.menubar.rumps.alert'), self.assertLogs(level='ERROR'):
            self.app.toggle_flag_view(Mock())
        self.assertTrue(self.app.config.flag_overlay.enabled)
        self.app._layout_overlay.configure.assert_not_called()

    def test_flag_preview_uses_unsaved_appearance_without_saving_or_enabling_automatic_flags(self):
        owner = Mock()
        owner.is_flag_preview_active.return_value = True
        self.app.prefs_window = owner
        self.app._flag_preview_overlay = Mock()
        self.app.config.flag_overlay.enabled = False
        before = self.app.config.editable_values()
        values = dict(before)
        values.update({'flag_overlay.size_percent': '210', 'flag_overlay.position': 'bottom_right',
                       'flag_overlay.opacity_percent': '75'})
        self.app._preview_flag_settings(owner, values)
        appearance = self.app._flag_preview_overlay.configure.call_args.args[0]
        self.assertEqual((appearance.enabled, appearance.size_percent, appearance.position,
                          appearance.opacity_percent), (True, 210, 'bottom_right', 75))
        self.app._flag_preview_overlay.show_preview.assert_called_once_with('en')
        self.assertEqual(self.app.config.editable_values(), before)
        self.assertFalse(self.config.config_path.exists())
        self.app._layout_overlay.close.assert_called_once()
        self.app.config.flag_overlay.enabled = True
        self.app._queue_layout_feedback('fr')
        self.app._display_layout_feedback('fr', self.app._layout_feedback_epoch)
        self.app._layout_overlay.show_language.assert_not_called()
        self.app._preview_flag_settings(owner, None)
        self.app._flag_preview_overlay.close.assert_called_once()
        self.assertIsNone(self.app._flag_preview_owner)

    def test_late_preview_callbacks_cannot_reopen_or_close_another_settings_preview(self):
        owner, stale = Mock(), Mock()
        owner.is_flag_preview_active.return_value = False
        self.app.prefs_window = owner
        self.app._flag_preview_overlay = Mock()
        values = self.config.editable_values()
        self.app._preview_flag_settings(owner, values)
        self.app._preview_flag_settings(stale, values)
        self.app._flag_preview_overlay.show_preview.assert_not_called()
        self.app._flag_preview_owner = owner
        self.app._stop_flag_preview(stale)
        self.app._flag_preview_overlay.close.assert_not_called()
        self.assertIs(self.app._flag_preview_owner, owner)

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
        detector.track_key_event.assert_called_once_with('backspace', 'backspace', text=None)
        self.assertEqual(self.app.word_buffer, 'wor')
        detector.reset_mock()
        self.app._on_press(keyboard.Key.delete)
        detector.track_key_event.assert_not_called()
        detector.clear_history.assert_called_once()

    def test_courant_correction_waits_for_same_key_retry_before_switching(self):
        self.setup_virtual_layouts()
        for vk, text in ((44, '/'), (51, '')):
            self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(vk, text))
        self.app.keyboard_switcher.toggle.assert_not_called()
        self.app._layout_overlay.show_language.assert_not_called()
        self.assertEqual(self.app.current_lang, 'en')
        retry = self.raw_key(44, '/')
        self.app._intercept_event(Quartz.kCGEventKeyDown, retry)
        self.assertEqual(self.text(retry), 'é')
        self.assertEqual(self.app.current_lang, 'fr')
        self.app.keyboard_switcher.toggle.assert_called_once_with('en', ['en', 'fr'])
        self.app._layout_overlay.show_language.assert_called_once_with('fr')

    def test_french_correction_switches_back_on_same_physical_key_retry(self):
        actual = self.setup_virtual_layouts()
        actual['language'] = self.app.current_lang = 'fr'
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, 'é'))
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(51))
        self.assertEqual(self.app.current_lang, 'fr')
        retry = self.raw_key(44, 'é')
        self.app._intercept_event(Quartz.kCGEventKeyDown, retry)
        self.assertEqual(self.text(retry), '/')
        self.assertEqual(self.app.current_lang, 'en')
        self.app.keyboard_switcher.toggle.assert_called_once_with('fr', ['en', 'fr'])

    def test_failed_correction_retry_never_rewrites_or_flashes(self):
        self.setup_virtual_layouts()
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, '/'))
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(51))
        self.app.keyboard_switcher.toggle.side_effect = None
        self.app.keyboard_switcher.toggle.return_value = None
        retry = self.raw_key(44, '/')
        self.app._intercept_event(Quartz.kCGEventKeyDown, retry)
        self.assertEqual(self.text(retry), '/')
        self.assertEqual(self.app.current_lang, 'en')
        self.app._layout_overlay.show_language.assert_not_called()

    def test_retry_deadline_starts_at_backspace_and_expires_at_exact_cutoff(self):
        for delay, expected in ((2.499, 'é'), (2.5, '/'), (3.0, '/')):
            with self.subTest(delay=delay):
                self.app._reset_detection()
                self.app.current_lang = 'en'
                self.setup_virtual_layouts()
                self.app.keyboard_switcher.toggle.reset_mock()
                self.app._layout_overlay.show_language.reset_mock()
                self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, '/'))
                self.now[0] += 2.0
                self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(51))
                self.now[0] += delay
                retry = self.raw_key(44, '/')
                self.app._intercept_event(Quartz.kCGEventKeyDown, retry)
                self.assertEqual(self.text(retry), expected)
                self.assertEqual(self.app.keyboard_switcher.toggle.call_count, int(expected == 'é'))
                self.assertEqual(self.app._layout_overlay.show_language.call_count, int(expected == 'é'))

    def test_unrelated_input_or_extra_backspace_cancels_pending_retry(self):
        for vk, text in ((8, 'c'), (51, ''), (123, ''), (49, ' ')):
            with self.subTest(vk=vk):
                self.app._reset_detection()
                self.app.current_lang = 'en'
                self.setup_virtual_layouts()
                self.app.keyboard_switcher.toggle.reset_mock()
                for key, value in ((44, '/'), (51, ''), (vk, text), (44, '/')):
                    self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(key, value))
                self.app.keyboard_switcher.toggle.assert_not_called()

    def test_shift_does_not_refresh_pending_retry_deadline(self):
        self.setup_virtual_layouts()
        for vk, text in ((44, '/'), (51, '')):
            self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(vk, text))
        self.now[0] += 2.0
        self.app._intercept_event(Quartz.kCGEventFlagsChanged,
                                 self.raw_key(56, flags=Quartz.kCGEventFlagMaskShift))
        self.now[0] += 0.5
        retry = self.raw_key(44, '?', flags=Quartz.kCGEventFlagMaskShift)
        self.app._intercept_event(Quartz.kCGEventKeyDown, retry)
        self.assertEqual(self.text(retry), '?')
        self.app.keyboard_switcher.toggle.assert_not_called()

    def test_arming_retry_invalidates_already_queued_word_decision(self):
        self.setup_virtual_layouts()
        detector, epoch = self.app.language_detector, self.app._detection_epoch
        result = Future()
        result.set_result('fr')
        for vk, text in ((44, '/'), (51, '')):
            self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(vk, text))
        self.app._finish_word(result, detector, epoch, 'synthetic')
        self.app.keyboard_switcher.switch_to.assert_not_called()
        self.app.keyboard_switcher.toggle.assert_not_called()

    def test_missing_translation_cancels_retry_without_switching(self):
        self.setup_virtual_layouts()
        for vk, text in ((44, '/'), (51, '')):
            self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(vk, text))
        self.app.keyboard_switcher.translate_key.side_effect = None
        self.app.keyboard_switcher.translate_key.return_value = None
        retry = self.raw_key(44, '/')
        self.app._intercept_event(Quartz.kCGEventKeyDown, retry)
        self.assertEqual(self.text(retry), '/')
        self.app.keyboard_switcher.toggle.assert_not_called()
        self.app._layout_overlay.show_language.assert_not_called()

    def test_rearming_retry_preserves_previous_rewritten_keyup(self):
        self.setup_virtual_layouts()
        for vk, text in ((44, '/'), (51, ''), (44, '/'), (51, '')):
            self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(vk, text))
        up = self.raw_key(44, '/', down=False)
        self.app._intercept_event(Quartz.kCGEventKeyUp, up)
        self.assertEqual(self.text(up), 'é')
        self.assertIsNotNone(self.app._pending_correction)

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

    def test_ecole_correction_deletes_suffix_before_switching(self):
        self.setup_virtual_layouts()
        now = [10.0]
        visible = ''
        def press(vk, text=''):
            nonlocal visible
            event = self.raw_key(vk, text)
            self.app._intercept_event(Quartz.kCGEventKeyDown, event)
            visible = visible[:-1] if vk == 51 else visible + self.text(event)
        with patch('detectors.frustration.time.monotonic', lambda: now[0]):
            press(44, '/')
            press(8, 'c')
            now[0] += 2.0
            press(51)
            self.assertEqual(visible, '/')
            self.app.keyboard_switcher.toggle.assert_not_called()
            now[0] += 0.2
            press(51)
            self.assertEqual(self.app.current_lang, 'en')
            self.app._layout_overlay.show_language.assert_not_called()
            press(44, '/')  # Event may already have been translated as US.
            press(8, 'c')
        self.assertEqual(visible, 'éc')
        self.app.keyboard_switcher.toggle.assert_called_once_with('en', ['en', 'fr'])
        self.app._layout_overlay.show_language.assert_called_once_with('fr')

    def test_expired_ecole_correction_is_an_ordinary_edit(self):
        self.setup_virtual_layouts()
        now = [10.0]
        with patch('detectors.frustration.time.monotonic', lambda: now[0]):
            for vk, text in ((44, '/'), (8, 'c')):
                self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(vk, text))
            now[0] += 2.5
            for _ in range(2):
                self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(51))
            retry = self.raw_key(44, '/')
            self.app._intercept_event(Quartz.kCGEventKeyDown, retry)
        self.assertEqual(self.text(retry), '/')
        self.assertEqual(self.app.current_lang, 'en')
        self.app.keyboard_switcher.toggle.assert_not_called()
        self.app._layout_overlay.show_language.assert_not_called()

    def test_new_word_cancels_a_previous_words_correction(self):
        for key in (keyboard.KeyCode.from_char('/', vk=44), keyboard.KeyCode.from_char(' '),
                    keyboard.KeyCode.from_char('c', vk=8), keyboard.Key.backspace, keyboard.Key.backspace):
            self.app._on_press(key)
        self.app.keyboard_switcher.toggle.assert_not_called()

    def test_manual_layout_change_shows_one_flag_and_own_notification_preserves_retry(self):
        self.app.keyboard_switcher.sync_state.return_value = 'fr'
        self.app._input_source_changed()
        self.assertEqual(self.app.current_lang, 'fr')
        self.app._layout_overlay.show_language.assert_called_once_with('fr')
        self.app._pending_correction = (44, 'fr', self.now[0])
        self.app._input_source_changed()
        self.assertEqual(self.app._pending_correction, (44, 'fr', self.now[0]))
        self.app._layout_overlay.show_language.assert_called_once_with('fr')

    def test_automatic_switch_shows_flag_only_when_switch_succeeds(self):
        self.app.keyboard_switcher.switch_to.return_value = False
        self.app._switch_to_language('fr')
        self.app._layout_overlay.show_language.assert_not_called()
        self.app.keyboard_switcher.switch_to.return_value = True
        self.app._switch_to_language('fr')
        self.app._layout_overlay.show_language.assert_called_once_with('fr')

    def test_stale_feedback_and_feedback_after_close_are_ignored(self):
        with patch('ui.menubar.AppHelper.callAfter') as defer:
            self.app._queue_layout_feedback('fr')
            self.app._queue_layout_feedback('en')
        for call in defer.call_args_list:
            callback, *args = call.args
            callback(*args)
        self.app._layout_overlay.show_language.assert_called_once_with('en')
        self.app.config.flag_overlay.enabled = False
        self.app._display_layout_feedback('en', self.app._layout_feedback_epoch)
        self.app._layout_overlay.show_language.assert_called_once_with('en')
        self.app._closed = True
        self.app._display_layout_feedback('en', self.app._layout_feedback_epoch)
        self.app._layout_overlay.show_language.assert_called_once_with('en')

    def test_flag_failure_does_not_break_a_layout_switch(self):
        self.app.keyboard_switcher.switch_to.return_value = True
        self.app._layout_overlay.show_language.side_effect = RuntimeError('window unavailable')
        with self.assertLogs(level='ERROR'):
            self.app._switch_to_language('fr')
        self.assertEqual(self.app.current_lang, 'fr')

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
        self.app._pending_correction = (44, 'fr', self.now[0])
        event = self.raw_key(44, '/', flags=Quartz.kCGEventFlagMaskCommand)
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.assertEqual(self.text(event), '/')
        self.app.keyboard_switcher.translate_key.assert_not_called()
        self.assertIsNone(self.app._pending_correction)

    def test_paused_input_is_never_rewritten(self):
        self.app.detecting = False
        self.app._pending_correction = (44, 'fr', self.now[0])
        event = self.raw_key(44, '/')
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.assertEqual(self.text(event), '/')
        self.app.keyboard_switcher.translate_key.assert_not_called()

    def test_manual_menu_change_supersedes_pending_retry(self):
        actual = self.setup_virtual_layouts()
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, '/'))
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(51))
        actual['language'] = 'fr'
        event = self.raw_key(44, '/')
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.assertEqual(self.text(event), '/')
        self.assertEqual(self.app.current_lang, 'fr')
        self.app.keyboard_switcher.translate_key.assert_not_called()

    def test_option_backspace_deletes_word_without_switching(self):
        self.setup_virtual_layouts()
        self.app._intercept_event(Quartz.kCGEventKeyDown, self.raw_key(44, '/'))
        event = self.raw_key(51, flags=Quartz.kCGEventFlagMaskAlternate)
        self.app._intercept_event(Quartz.kCGEventKeyDown, event)
        self.app.keyboard_switcher.toggle.assert_not_called()
        self.assertEqual(self.app.frustration_detector.key_history, [])
        self.assertEqual(self.app.word_buffer, '')

    def test_fresh_keypress_discards_stale_keyup_rewrite_but_autorepeat_preserves_it(self):
        for repeat in (0, 1):
            with self.subTest(repeat=repeat):
                self.app._rewritten_keyups[44] = 'é'
                event = self.raw_key(44, '/')
                Quartz.CGEventSetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat, repeat)
                self.app._intercept_event(Quartz.kCGEventKeyDown, event)
                self.assertEqual(self.app._rewritten_keyups.get(44), 'é' if repeat else None)

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


class PermissionRecoveryTests(unittest.TestCase):
    """A denied tap leaves a recoverable menu app, never a false active state."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(Path(self.directory.name) / 'settings.json')
        self.executor = self.stack.enter_context(patch('ui.menubar.ThreadPoolExecutor')).return_value
        self.switcher = self.stack.enter_context(patch('ui.menubar.KeyboardSwitcher')).return_value
        self.tap = self.stack.enter_context(patch('ui.menubar.KeyboardEventTap')).return_value
        self.stack.enter_context(patch('ui.menubar.LayoutOverlay'))
        self.stack.enter_context(patch('ui.menubar.InputSourceObserver'))
        self.deferred = self.stack.enter_context(patch('ui.menubar.AppHelper.callAfter'))
        self.stack.enter_context(patch('ui.menubar.rumps.MenuItem'))
        self.stack.enter_context(patch.object(LangSwitcherApp, '_sync_with_macos'))
        self.stack.enter_context(patch.object(LangSwitcherApp, '_update_icon'))
        self.stack.enter_context(patch.object(LangSwitcherApp, '_make_detectors',
                                             return_value=(Mock(), Mock())))
        self.stack.enter_context(patch('ui.menubar.collect_access_report', side_effect=lambda **kwargs:
                                      AccessReport(kwargs.get('keyboard_access', False), True, True,
                                                   kwargs.get('reason', ''), kwargs.get('details', ''))))
        def init_menu(app, **kwargs):
            app._menu = {name: Mock(title=name) for name in kwargs['menu'] if isinstance(name, str)}
        self.stack.enter_context(patch('ui.menubar.rumps.App.__init__', init_menu))
        self.denied = AccessReport(False, True, True, 'Keyboard access is unavailable', 'filtered mask')

    def make_app(self, denied=False):
        if denied:
            self.tap.start.side_effect = KeyboardAccessError(self.denied)
        app = LangSwitcherApp(self.config)
        self.addCleanup(app.close)
        return app

    def test_denied_startup_stays_paused_and_schedules_recovery(self):
        app = self.make_app(denied=True)
        self.assertFalse(app.detecting)
        self.assertFalse(app._access_ready)
        self.assertIs(app._access_report, self.denied)
        self.deferred.assert_called_once_with(app.open_keyboard_access, None)
        self.switcher.close.assert_not_called()
        self.executor.shutdown.assert_not_called()

    def test_successful_startup_does_not_open_recovery(self):
        app = self.make_app()
        self.assertTrue(app.detecting)
        self.assertTrue(app._access_ready)
        self.deferred.assert_not_called()

    def test_retry_after_permission_refresh_activates_detection(self):
        app = self.make_app(denied=True)
        self.tap.start.side_effect = None
        report = app._retry_keyboard_access()
        self.assertTrue(report.keyboard_access)
        self.assertTrue(app._access_ready)
        self.assertTrue(app.detecting)

    def test_resume_cannot_activate_a_denied_tap(self):
        app = self.make_app(denied=True)
        with patch.object(app, 'open_keyboard_access') as show:
            app.toggle(Mock())
        self.assertFalse(app.detecting)
        show.assert_called_once_with(None)

    def test_manual_recheck_preserves_an_intentional_pause(self):
        app = self.make_app()
        app.detecting = False
        app._detection_requested = False
        report = app._retry_keyboard_access()
        self.assertTrue(report.keyboard_access)
        self.assertFalse(app.detecting)

    def test_pause_survives_a_failed_check_then_successful_recovery(self):
        app = self.make_app()
        app.detecting = False
        app._detection_requested = False
        self.tap.start.side_effect = KeyboardAccessError(self.denied)
        self.assertFalse(app._retry_keyboard_access().keyboard_access)
        self.tap.start.side_effect = None
        self.assertTrue(app._retry_keyboard_access().keyboard_access)
        self.assertFalse(app.detecting)

    def test_post_start_sync_failure_stops_tap_and_clears_ready_state(self):
        app = self.make_app()
        app._sync_with_macos.side_effect = RuntimeError('input-source sync failed')
        with self.assertLogs(level='ERROR'):
            report = app._retry_keyboard_access()
        self.assertFalse(report.keyboard_access)
        self.assertFalse(app._access_ready)
        self.assertFalse(app.detecting)
        self.assertEqual(app.menu['Pause LangSwitcher'].title, 'Resume LangSwitcher')
        self.assertEqual(self.tap.stop.call_count, 3)

    def test_opening_access_menu_refreshes_previously_healthy_status(self):
        app = self.make_app()
        self.tap.start.side_effect = KeyboardAccessError(self.denied)
        with patch('ui.menubar.KeyboardAccessWindow') as window_class:
            app.open_keyboard_access(None)
        self.assertFalse(app.detecting)
        self.assertFalse(app._access_ready)
        window_class.alloc.return_value.initWithReport_.assert_called_once_with(self.denied)

    def test_ordinary_startup_failure_cleans_resources_and_is_not_permissions(self):
        self.tap.start.side_effect = RuntimeError('run-loop source failed')
        with self.assertRaisesRegex(RuntimeError, 'run-loop source failed'):
            LangSwitcherApp(self.config)
        self.switcher.close.assert_called_once()
        self.executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        self.deferred.assert_not_called()

    def test_failed_recheck_stops_tap_and_cannot_switch_from_old_worker(self):
        app = self.make_app()
        detector, epoch = app.language_detector, app._detection_epoch
        result = Future()
        result.set_result('fr')
        self.tap.start.side_effect = KeyboardAccessError(self.denied)
        app._retry_keyboard_access()
        app._finish_word(result, detector, epoch, 'bonjour')
        self.assertFalse(app.detecting)
        self.switcher.switch_to.assert_not_called()

    def test_close_is_idempotent(self):
        app = self.make_app()
        app._flag_preview_overlay = Mock()
        app._flag_preview_owner = Mock()
        self.tap.stop.reset_mock()
        app.close()
        app.close()
        self.tap.stop.assert_called_once()
        self.switcher.close.assert_called_once()
        self.executor.shutdown.assert_called_once()
        app._flag_preview_overlay.close.assert_called_once()
        self.assertIsNone(app._flag_preview_owner)


if __name__ == '__main__':
    unittest.main()
