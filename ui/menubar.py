"""
Menu Bar Application

Main application class for LangSwitcher menu bar app.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from PyObjCTools import AppHelper
import Quartz
import logging
import subprocess
from typing import Optional

import rumps
from pynput import keyboard
from Cocoa import NSApplication

from config import Config
from version import __version__, __app_name__, __author__
from detectors import LanguageDetector, FrustrationDetector
from switchers import KeyboardSwitcher
from keyboard_events import KeyboardEventTap
from ui.settings import PrefsWindow


# Word boundary and backspace keys
WORD_BOUNDARY_KEYS = {keyboard.Key.space, keyboard.Key.enter}
MODIFIER_KEYS = {
    keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
    keyboard.Key.caps_lock,
}
SHORTCUT_KEYS = {
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
}
EDITING_KEYS = {
    keyboard.Key.delete, keyboard.Key.left, keyboard.Key.right,
    keyboard.Key.up, keyboard.Key.down, keyboard.Key.home, keyboard.Key.end,
    keyboard.Key.esc, keyboard.Key.tab,
}

SPECIAL_KEYS_BY_VK = {
    key.value.vk: key for key in keyboard.Key
    if not getattr(key.value, '_is_media', False)
}


class LangSwitcherApp(rumps.App):
    """Main LangSwitcher application"""
    
    def __init__(self, config: Config):
        """
        Initialize application
        
        Args:
            config: Configuration instance
        """
        self.config = config
        self._state_lock = threading.RLock()
        self._shortcut_keys_down = set()
        self._expected_retry = None
        self._rewritten_keyups = {}
        self._detection_epoch = 0
        self._word_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='language-detection')
        
        # Initialize icon
        icon_emoji = config.language.layouts[config.language.detection_langs[0]][1]
        version_item = rumps.MenuItem(
            f"{__app_name__} {__version__}",
            callback=None  # Not clickable (greyed out)
        )
        
        super().__init__(
            name=__app_name__,
            icon=None,
            title=icon_emoji,
            menu=["Pause LangSwitcher", "Open Debug Console", "Settings…", "Quit", None, version_item],
            quit_button=None
        )
        
        # Initialize components
        self.keyboard_switcher = KeyboardSwitcher(
            config.language.layouts,
            script_dir=self._get_script_dir()
        )
        
        self.language_detector, self.frustration_detector = self._make_detectors(config)

        # Application state
        self.detecting = True
        self.word_buffer = ""
        self.current_lang = config.language.detection_langs[0]
        self.base_icon = icon_emoji  # Store base icon without pause indicator
        
        # Sync with actual macOS layout at startup
        self._sync_with_macos()
        
        # The active tap and TIS calls run on the main Cocoa runloop. Returning
        # an event forwards it only after correction handling has completed.
        self._event_tap = KeyboardEventTap(self._intercept_event)
        self._event_tap.start()
    
    @staticmethod
    def _make_detectors(config):
        return (
            LanguageDetector(
                detection_langs=list(config.language.detection_langs),
                dict_langs=config.language.dict_langs,
                buffer_size=config.detection.buffer_size,
                switch_threshold=config.detection.switch_threshold,
                min_word_length=config.detection.min_word_length,
                confidence_threshold=config.detection.model_confidence_threshold,
                fallback_to_buffer=config.detection.fallback_to_buffer_on_ambiguous,
            ),
            FrustrationDetector(),
        )

    def apply_settings(self, values):
        """Validate, persist, and apply the same settings to both live detectors."""
        with self._state_lock:
            candidate = self.config.with_settings(values)
            language, frustration = self._make_detectors(candidate)
            candidate.save()
            self.config = candidate
            self.language_detector = language
            self.frustration_detector = frustration
            self._reset_detection()
            logging.info("[SETTINGS] Saved and applied settings to live detectors")

    def _reset_detection(self):
        self.word_buffer = ""
        self.language_detector = self.language_detector.fresh()
        self.frustration_detector.clear_history()
        self._detection_epoch += 1
        self._expected_retry = None
        self._rewritten_keyups.clear()

    def _get_script_dir(self) -> str:
        """Get directory containing bundled resources (im-select)"""
        import os
        import sys
        
        # When bundled with py2app, resources are in Contents/Resources/
        if getattr(sys, 'frozen', False):
            # Running in bundled app
            # sys._MEIPASS for PyInstaller, resourcePath() for py2app
            if hasattr(sys, '_MEIPASS'):
                return sys._MEIPASS
            else:
                # py2app: __file__ will be in Resources/lib/python3.13/ui/
                # We need to go up to Resources/
                resource_path = os.path.dirname(os.path.abspath(__file__))
                # Go up from ui/ -> python3.13/ -> lib/ -> Resources/
                for _ in range(3):
                    resource_path = os.path.dirname(resource_path)
                return resource_path
        else:
            # Running as script - im-select is in project root
            # Go up from ui/ to project root
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def _sync_with_macos(self):
        """Sync before word detection or switching; discard stale typing context."""
        actual_lang = self.keyboard_switcher.sync_state(self.current_lang)
        if actual_lang and actual_lang != self.current_lang:
            self.current_lang = actual_lang
            icon = self.keyboard_switcher.get_icon(actual_lang)
            if icon:
                self.base_icon = icon
                self._update_icon()
            self._reset_detection()
            logging.info(f"[SYNC] Synchronized to {actual_lang}")
            return True
        return False
    
    def _update_icon(self):
        """Update menu bar icon with pause indicator if paused"""
        if self.detecting:
            self.title = self.base_icon
        else:
            self.title = f"{self.base_icon}⏸"  # Add pause symbol when paused
    
    def _open_debug_console(self):
        """Open Terminal with tail -f on log file"""
        applescript = f'''
        tell application "Terminal"
          activate
          do script "tail -f {self.config.app.debug_log_path}"
        end tell
        '''
        subprocess.Popen(
            ["osascript", "-e", applescript],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    
    @rumps.clicked("Pause LangSwitcher")
    def toggle(self, sender):
        """Toggle language detection on/off"""
        with self._state_lock:
            self.detecting = not self.detecting
            self._reset_detection()
            if self.detecting:
                self._sync_with_macos()
        
        if self.detecting:
            sender.title = "Pause LangSwitcher"
            rumps.notification(__app_name__, "", "LangSwitcher resumed")
            logging.info("Detection resumed")
        else:
            sender.title = "Resume LangSwitcher"
            rumps.notification(__app_name__, "", "LangSwitcher paused")
            logging.info("Detection paused")
        
        # Update icon to show/hide pause indicator
        self._update_icon()
    
    @rumps.clicked("Open Debug Console")
    def open_console(self, _):
        """Open Terminal with debug log"""
        self._open_debug_console()
        rumps.notification(__app_name__, "", "Debug console opened")
    
    @rumps.clicked("Settings…")
    def settings(self, _):
        """Open settings window"""
        # Always create fresh window to get updated HTML/CSS
        self.prefs_window = PrefsWindow.alloc().initWithConfig_(self.config)
        self.prefs_window.on_save = self.apply_settings
        self.prefs_window.show()
    
    @rumps.clicked("Quit")
    def quit(self, _):
        """Quit application"""
        self._event_tap.stop()
        self.keyboard_switcher.close()
        self._word_executor.shutdown(wait=False, cancel_futures=True)
        rumps.quit_application()
    
    def _intercept_event(self, event_type, event):
        """Normalize queued retries before forwarding the original OS event."""
        vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        flags = Quartz.CGEventGetFlags(event)
        self._shortcut_keys_down = set()
        if flags & Quartz.kCGEventFlagMaskCommand:
            self._shortcut_keys_down.add(keyboard.Key.cmd)
        if flags & Quartz.kCGEventFlagMaskControl:
            self._shortcut_keys_down.add(keyboard.Key.ctrl)

        if event_type == Quartz.kCGEventKeyUp:
            rewritten = self._rewritten_keyups.pop(vk, None)
            if rewritten is not None:
                Quartz.CGEventKeyboardSetUnicodeString(event, len(rewritten.encode('utf-16-le')) // 2, rewritten)
            self._on_release(SPECIAL_KEYS_BY_VK.get(vk, keyboard.KeyCode.from_vk(vk)))
            return event

        if event_type == Quartz.kCGEventFlagsChanged:
            if self._shortcut_keys_down:
                self._reset_detection()
            return event

        if event_type != Quartz.kCGEventKeyDown:
            return event

        if vk == keyboard.Key.backspace.value.vk and flags & Quartz.kCGEventFlagMaskAlternate:
            # Option+Backspace deletes a whole word, not just the last key.
            self._reset_detection()
            return event

        if self.detecting and not self._shortcut_keys_down:
            retry = self._expected_retry
            if retry is not None and retry[0] == vk:
                # The event can have been translated before the preceding
                # Backspace changed the source. Repair that event in place.
                if self.keyboard_switcher.get_current_layout() == retry[1]:
                    text = self.keyboard_switcher.translate_key(vk, flags, retry[1])
                    if text:
                        Quartz.CGEventKeyboardSetUnicodeString(event, len(text.encode('utf-16-le')) // 2, text)
                        self._rewritten_keyups[vk] = text
                else:
                    # A manual menu/source change supersedes the pending retry.
                    self._sync_with_macos()
                self._expected_retry = None
            elif vk in self.frustration_detector.FRUSTRATION_ELIGIBLE_KEYS:
                self._sync_with_macos()
                self._expected_retry = None
            elif vk not in {key.value.vk for key in MODIFIER_KEYS}:
                self._expected_retry = None

        key = SPECIAL_KEYS_BY_VK.get(vk)
        if key is None:
            length, text = Quartz.CGEventKeyboardGetUnicodeString(event, 100, None, None)
            key = keyboard.KeyCode.from_char(text, vk=vk) if length else keyboard.KeyCode.from_vk(vk)
        self._on_press(key)
        return event

    def _on_release(self, key):
        with self._state_lock:
            self._shortcut_keys_down.discard(key)

    def _on_press(self, key):
        with self._state_lock:
            if key in SHORTCUT_KEYS:
                self._shortcut_keys_down.add(key)
                self._reset_detection()
                return
            if key in MODIFIER_KEYS:
                return
            if not self.detecting:
                return
            if self._shortcut_keys_down or key in EDITING_KEYS:
                self._reset_detection()
                return

            # Send each physical key exactly once, including keys that cancel
            # a pending correction gesture. Forward Delete is handled above.
            if self.config.frustration.enabled:
                is_backspace = key == keyboard.Key.backspace
                vk_code = 'backspace' if is_backspace else getattr(key, 'vk', None)
                event_type = 'backspace' if is_backspace else 'key'
                if self.frustration_detector.track_key_event(vk_code, event_type):
                    # Mirror this Backspace in our buffer even if the native
                    # layout change fails; the real event is always forwarded.
                    if is_backspace:
                        self.word_buffer = self.word_buffer[:-1]
                    self._handle_frustration()
                    return

            if key == keyboard.Key.backspace:
                self.word_buffer = self.word_buffer[:-1]
                return

            ch = getattr(key, 'char', None)
            if ch and (ch.isalpha() or ch in self.config.detection.valid_punctuation):
                self.word_buffer += ch
            elif (ch and ch.isspace()) or key in WORD_BOUNDARY_KEYS:
                self._process_word_buffer()
            elif ch:
                # Punctuation and numbers must not join separate words together.
                self._process_word_buffer()

    def _process_word_buffer(self):
        """Process accumulated word buffer for language detection"""
        txt = self.word_buffer
        self.word_buffer = ""
        
        if not txt:
            return
        
        if self._sync_with_macos():
            return
        detector = self.language_detector
        epoch = self._detection_epoch
        current_lang = self.current_lang
        future = self._word_executor.submit(self._detect_word, detector, txt, current_lang)
        future.add_done_callback(lambda result: AppHelper.callAfter(
            self._finish_word, result, detector, epoch, txt))

    @staticmethod
    def _detect_word(detector, text, current_lang):
        """Slow dictionaries/model work never runs inside the keyboard tap."""
        detected_lang = detector.detect(text, current_lang=current_lang)
        if detected_lang and detector.should_switch(detected_lang, current_lang):
            return detected_lang
        return None

    def _finish_word(self, result, detector, epoch, text):
        if result.cancelled():
            return
        try:
            target = result.result()
        except Exception:
            logging.exception("Language detection failed")
            return
        if (self.detecting and epoch == self._detection_epoch
                and detector is self.language_detector and target):
            self._switch_to_language(target, text)

    def _switch_to_language(self, target_lang: str, trigger_word: str = ""):
        """Switch to target language"""
        # A manual layout change invalidates the decision made from old history.
        if self._sync_with_macos() or target_lang == self.current_lang:
            return
        
        # Perform switch
        if self.keyboard_switcher.switch_to(target_lang):
            self.current_lang = target_lang
            icon = self.keyboard_switcher.get_icon(target_lang)
            if icon:
                self.base_icon = icon
                self._update_icon()
            self._reset_detection()
            logging.info(f"[SWITCH] → {target_lang.upper()} (trigger: '{trigger_word}')")
    
    def _handle_frustration(self):
        """Handle detected frustration pattern - switch layout, user retypes"""
        # The preceding eligible physical key was synchronized in the tap.
        # Do not add a subprocess or resync that can undo a rapid switch-back.
        trigger_vk = self.frustration_detector.get_last_triggered_key()

        # Toggle to opposite language
        available_langs = list(self.config.language.detection_langs)
        target_lang = self.keyboard_switcher.toggle(self.current_lang, available_langs)
        
        if target_lang:
            self.current_lang = target_lang
            icon = self.keyboard_switcher.get_icon(target_lang)
            if icon:
                self.base_icon = icon
                self._update_icon()
            
            # Start clean after the switch; the next correction can toggle immediately.
            self._reset_detection()
            self._expected_retry = (trigger_vk, target_lang)

            logging.info(f"[FRUSTRATION] Switched to {target_lang} - user will retype")
            # No auto-replay - user retypes naturally!

