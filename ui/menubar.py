"""
Menu Bar Application

Main application class for LangSwitcher menu bar app.
"""

import threading
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
from ui.settings import PrefsWindow


# Word boundary and backspace keys
WORD_BOUNDARY_KEYS = {keyboard.Key.space, keyboard.Key.enter}
BACKSPACE_KEYS = {keyboard.Key.backspace, keyboard.Key.delete}


class LangSwitcherApp(rumps.App):
    """Main LangSwitcher application"""
    
    def __init__(self, config: Config):
        """
        Initialize application
        
        Args:
            config: Configuration instance
        """
        self.config = config
        
        # Initialize icon
        icon_emoji = config.language.layouts[config.language.detection_langs[0]][1]
        version_item = rumps.MenuItem(
            f"{__app_name__} {__version__} by {__author__}",
            callback=lambda _: None
        )
        
        super().__init__(
            name=__app_name__,
            icon=None,
            title=icon_emoji,
            menu=["Toggle Detection", "Open Debug Console", "Settings…", "Quit", None, version_item],
            quit_button=None
        )
        
        # Initialize components
        self.keyboard_switcher = KeyboardSwitcher(
            config.language.layouts,
            script_dir=self._get_script_dir()
        )
        
        self.language_detector = LanguageDetector(
            detection_langs=list(config.language.detection_langs),
            dict_langs=config.language.dict_langs,
            buffer_size=config.detection.buffer_size,
            switch_threshold=config.detection.switch_threshold,
            min_word_length=config.detection.min_word_length,
            confidence_threshold=config.detection.model_confidence_threshold,
            fallback_to_buffer=config.detection.fallback_to_buffer_on_ambiguous
        )
        
        self.frustration_detector = FrustrationDetector(
            time_window=config.frustration.time_window,
            cooldown=config.frustration.cooldown,
            enable_replay=config.frustration.enable_keystroke_replay
        )
        
        # Application state
        self.detecting = True
        self.word_buffer = ""
        self.current_lang = config.language.detection_langs[0]
        
        # Sync with actual macOS layout at startup
        self._sync_with_macos()
        
        # Start keyboard listener in background
        threading.Thread(target=self._start_listener, daemon=True).start()
    
    def _get_script_dir(self) -> str:
        """Get directory containing the script"""
        import os
        return os.path.dirname(os.path.abspath(__file__))
    
    def _sync_with_macos(self):
        """
        Synchronize app state with macOS keyboard layout
        
        Note: We use "lazy sync" (sync-on-demand) rather than continuous polling.
        This is intentional because:
        - Manual layout changes are rare
        - Desync is harmless (icon cosmetic, operations guarded)
        - Next automatic switch corrects any drift
        - Polling would waste CPU cycles for minimal UX benefit
        """
        actual_lang = self.keyboard_switcher.sync_state(self.current_lang)
        if actual_lang and actual_lang != self.current_lang:
            self.current_lang = actual_lang
            icon = self.keyboard_switcher.get_icon(actual_lang)
            if icon:
                self.title = icon
            self.language_detector.clear_buffer()
            logging.info(f"[SYNC] Synchronized to {actual_lang}")
    
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
    
    @rumps.clicked("Toggle Detection")
    def toggle(self, _):
        """Toggle language detection on/off"""
        self.detecting = not self.detecting
        state = "ON" if self.detecting else "OFF"
        rumps.notification(__app_name__, "", f"Detection is now {state}")
        logging.info(f"Detection toggled {state}")
    
    @rumps.clicked("Open Debug Console")
    def open_console(self, _):
        """Open Terminal with debug log"""
        self._open_debug_console()
        rumps.notification(__app_name__, "", "Debug console opened")
    
    @rumps.clicked("Settings…")
    def settings(self, _):
        """Open settings window"""
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        pw = PrefsWindow.alloc().initWithConfig_(self.config)
        pw.run()
    
    @rumps.clicked("Quit")
    def quit(self, _):
        """Quit application"""
        rumps.quit_application()
    
    def _start_listener(self):
        """Start keyboard listener"""
        def on_press(key):
            if not self.detecting:
                return
            
            # Track for frustration detection
            vk_code = getattr(key, 'vk', None)
            if vk_code is not None:
                event_type = 'backspace' if key in BACKSPACE_KEYS else 'key'
                
                # Check if frustration pattern detected
                if self.frustration_detector.track_key_event(vk_code, event_type):
                    self._handle_frustration()
                    return
            
            # Language detection logic
            try:
                ch = key.char
                if ch and (ch.isalpha() or ch in self.config.detection.valid_punctuation):
                    self.word_buffer += ch
                    return
                if ch and ch.isspace():
                    self._process_word_buffer()
                    return
            except AttributeError:
                pass
            
            # Handle special keys
            if key in WORD_BOUNDARY_KEYS:
                self._process_word_buffer()
            elif key in BACKSPACE_KEYS:
                # Track backspace for frustration detection
                # Use string identifier since backspace doesn't have reliable VK code
                if self.frustration_detector.track_key_event('backspace', 'backspace'):
                    self._handle_frustration()
                    return
                
                # Also handle word buffer
                self.word_buffer = self.word_buffer[:-1]
                logging.debug(f"[BUFFER] After backspace: '{self.word_buffer}'")
        
        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()
    
    def _process_word_buffer(self):
        """Process accumulated word buffer for language detection"""
        txt = self.word_buffer
        self.word_buffer = ""
        
        if not txt:
            return
        
        logging.debug(f"[WORD] Typed: {txt}")
        
        # Detect language (pass current keyboard layout for ambiguous first words)
        detected_lang = self.language_detector.detect(txt, current_lang=self.current_lang)
        
        if detected_lang is None:
            return
        
        # Check if we should switch
        if self.language_detector.should_switch(detected_lang, self.current_lang):
            self._switch_to_language(detected_lang, txt)
    
    def _switch_to_language(self, target_lang: str, trigger_word: str = ""):
        """Switch to target language"""
        # Sync before switching
        self._sync_with_macos()
        
        # Perform switch
        if self.keyboard_switcher.switch_to(target_lang):
            self.current_lang = target_lang
            icon = self.keyboard_switcher.get_icon(target_lang)
            if icon:
                self.title = icon
            logging.info(f"[SWITCH] → {target_lang.upper()} (trigger: '{trigger_word}')")
    
    def _handle_frustration(self):
        """Handle detected frustration pattern - switch layout, user retypes"""
        # Sync with macOS first
        self._sync_with_macos()
        
        # Toggle to opposite language
        available_langs = list(self.config.language.detection_langs)
        target_lang = self.keyboard_switcher.toggle(self.current_lang, available_langs)
        
        if target_lang:
            self.current_lang = target_lang
            icon = self.keyboard_switcher.get_icon(target_lang)
            if icon:
                self.title = icon
            
            # Clear detectors to prevent double-triggering
            self.frustration_detector.clear_history()
            self.language_detector.clear_buffer()
            
            logging.info(f"[FRUSTRATION] Switched to {target_lang} - user will retype")
            # No auto-replay - user retypes naturally!

