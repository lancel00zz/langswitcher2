#!/usr/bin/env python3
import os
import sys
import json
import threading
import logging
import pathlib
import subprocess
import time
from shutil import which

import rumps
import enchant
from pynput import keyboard
from langdetect import detect_langs, LangDetectException

from Cocoa import (
    NSApp,
    NSApplication,
    NSWindow,
    NSBackingStoreBuffered,
    NSTextField,
    NSButton,
    NSSwitch,
    NSRunningApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSObject,
    NSMakeRect,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
)
import objc

# ——— CONFIGURATION ———
VERSION = "1.1 dev"
DETECTION_LANGS = ["en", "fr"]
LAYOUTS = {
    "en": ("com.apple.keylayout.US", "🇺🇸"),
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
}
DICT_LANGS = {"en": "en_US", "fr": "fr_FR"}
BUFFER_SIZE = 4
SWITCH_THRESHOLD = 3
MIN_WORD_LENGTH = 2
MODEL_CONFIDENCE_THRESHOLD = 0.5
FALLBACK_TO_BUFFER_ON_AMBIGUOUS = True
DISPLAY_DEBUG_CONSOLE = False
DEBUG_LOG_PATH = os.path.expanduser("~/langswitcher.log")
VALID_PUNCT = ("'", "’", "-")
WORD_BOUNDARY_KEYS = {keyboard.Key.space, keyboard.Key.enter}
BACKSPACE_KEYS = {keyboard.Key.backspace, keyboard.Key.delete}
# ——— END CONFIGURATION ———

# Determine path to im-select: check bundled, then system PATH.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_IM = os.path.join(SCRIPT_DIR, 'im-select')
if os.path.isfile(BUNDLED_IM) and os.access(BUNDLED_IM, os.X_OK):
    IM_SELECT = BUNDLED_IM
else:
    IM_SELECT = which('im-select') or BUNDLED_IM  # falls back to bundled even if missing

_conf_path = pathlib.Path(__file__).with_suffix(".conf.json")
if _conf_path.exists():
    overrides = json.loads(_conf_path.read_text()) or {}
    globals().update(overrides)

logging.basicConfig(
    filename=DEBUG_LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s %(message)s"
)

dicts = {lang: enchant.Dict(code) for lang, code in DICT_LANGS.items()}


def open_debug_console():
    if not DISPLAY_DEBUG_CONSOLE:
        return
    applescript = f'''
    tell application "Terminal"
      activate
      do script "tail -f {DEBUG_LOG_PATH}"
    end tell
    '''
    subprocess.Popen(
        ["osascript", "-e", applescript],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class PrefsWindow(NSObject):
    def init(self):
        self = objc.super(PrefsWindow, self).init()
        if not self:
            return None

        WIDTH, HEIGHT = 320, 450
        rect = NSMakeRect(0, 0, WIDTH, HEIGHT)
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )
        self.win.setTitle_("Lang Switcher Preferences")
        self.win.center()

        cf = self.win.contentView().frame()
        W, H = cf.size.width, cf.size.height

        LABEL_X = W * 0.05
        FIELD_X = W * 0.55
        CW, CH = W * 0.40, 24
        SPY = 50
        y = H - CH - 30

        def label(txt, yy):
            l = NSTextField.alloc().initWithFrame_(NSMakeRect(LABEL_X, yy, CW, CH))
            l.setStringValue_(txt)
            l.setBezeled_(False)
            l.setDrawsBackground_(False)
            l.setEditable_(False)
            self.win.contentView().addSubview_(l)

        def textf(val, yy):
            t = NSTextField.alloc().initWithFrame_(NSMakeRect(FIELD_X, yy, CW, CH))
            t.setStringValue_(str(val))
            self.win.contentView().addSubview_(t)
            return t

        def sw(val, yy):
            s = NSSwitch.alloc().initWithFrame_(NSMakeRect(FIELD_X, yy, 40, CH))
            s.setState_(1 if val else 0)
            self.win.contentView().addSubview_(s)
            return s

        self.buf_tf = textf(BUFFER_SIZE, y)
        label("Buffer size:", y)
        y -= SPY
        self.th_tf = textf(SWITCH_THRESHOLD, y)
        label("Switch threshold:", y)
        y -= SPY
        self.min_tf = textf(MIN_WORD_LENGTH, y)
        label("Min word length:", y)
        y -= SPY
        self.fb_sw = sw(FALLBACK_TO_BUFFER_ON_AMBIGUOUS, y)
        label("Fallback to buffer:", y)
        y -= SPY
        self.db_sw = sw(DISPLAY_DEBUG_CONSOLE, y)
        label("Display debug console:", y)
        y -= SPY

        langs = ", ".join(DETECTION_LANGS)
        dicts_s = ", ".join(DICT_LANGS[l] for l in DETECTION_LANGS)
        label(f"Detection languages: {langs}", y)
        y -= CH + 10
        label(f"Dictionaries: {dicts_s}", y)
        y -= SPY

        bw, bh = 100, 32
        bx = (W - bw) / 2
        by = y - 10
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(bx, by, bw, bh))
        btn.setTitle_("Save")
        btn.setBezelStyle_(1)
        btn.setTarget_(self)
        btn.setAction_("savePrefs:")
        self.win.contentView().addSubview_(btn)

        return self

    def savePrefs_(self, _):
        try:
            new = {
                "BUFFER_SIZE": int(self.buf_tf.stringValue()),
                "SWITCH_THRESHOLD": int(self.th_tf.stringValue()),
                "MIN_WORD_LENGTH": int(self.min_tf.stringValue()),
                "FALLBACK_TO_BUFFER_ON_AMBIGUOUS": bool(self.fb_sw.state()),
                "DISPLAY_DEBUG_CONSOLE": bool(self.db_sw.state()),
            }
            _conf_path.write_text(json.dumps(new, indent=2))
            NSApp.stop_(None)
            notify = 'tell application \"System Events\" to display dialog \"Settings saved; restarting...\" buttons {\"OK\"}'
            subprocess.Popen(
                ["osascript", "-e", notify],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            err = f'tell application \"System Events\" to display dialog \"Error: {e}\" buttons {{\"OK\"}}'
            subprocess.Popen(
                ["osascript", "-e", err],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def run(self):
        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps
        )
        self.win.makeKeyAndOrderFront_(None)
        NSApp.run()


class LangSwitcherApp(rumps.App):
    def __init__(self):
        icon_emoji = LAYOUTS[DETECTION_LANGS[0]][1]
        version = rumps.MenuItem(f"Lang Switcher {VERSION} by pza", callback=lambda _: None)
        super().__init__(
            name="LangSwitcher",
            icon=None,
            title=icon_emoji,
            menu=["Toggle Detection", "Settings…", "Quit", None, version],
            quit_button=None
        )

        self.detecting = True
        self.word_buffer = ""
        self.lang_buffer = []
        self.current_lang = DETECTION_LANGS[0]
        
        # Frustration pattern detection
        self.key_history = []  # Track recent key events for frustration detection
        self.frustration_window = 3.0  # Max time window for pattern detection (seconds)

        open_debug_console()
        threading.Thread(target=self.start_listener, daemon=True).start()

    @rumps.clicked("Settings…")
    def settings(self, _):
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        pw = PrefsWindow.alloc().init()
        pw.run()

    @rumps.clicked("Toggle Detection")
    def toggle(self, _):
        self.detecting = not self.detecting
        state = "ON" if self.detecting else "OFF"
        rumps.notification("LangSwitcher", "", f"Detection is now {state}")
        logging.info(f"Detection toggled {state}")

    @rumps.clicked("Quit")
    def quit(self, _):
        rumps.quit_application()

    def track_key_event(self, vk_code, event_type):
        """Track physical key presses for frustration detection"""
        now = time.time()
        
        # Clean old events (keep only recent events within time window)
        self.key_history = [e for e in self.key_history 
                           if now - e['timestamp'] < self.frustration_window]
        
        # Add new event
        self.key_history.append({
            'timestamp': now, 
            'vk_code': vk_code, 
            'type': event_type
        })
        
        # Check for frustration pattern
        self.check_frustration_pattern()

    def check_frustration_pattern(self):
        """Detect Key -> Backspace -> Same Key pattern"""
        if len(self.key_history) < 3:
            return
            
        # Check last 3 events for the frustration pattern
        recent = self.key_history[-3:]
        
        if (recent[0]['type'] == 'key' and 
            recent[1]['type'] == 'backspace' and 
            recent[2]['type'] == 'key' and
            recent[0]['vk_code'] == recent[2]['vk_code']):
            
            logging.info(f"[FRUSTRATION] Pattern detected! Key {recent[0]['vk_code']} -> Backspace -> Key {recent[2]['vk_code']}")
            self.switch_keyboard_immediately()

    def switch_keyboard_immediately(self):
        """Immediately switch to the other keyboard layout"""
        # Toggle to opposite language
        current = self.current_lang
        target = "fr" if current == "en" else "en"
        
        layout_id, icon = LAYOUTS[target]
        try:
            subprocess.run([IM_SELECT, layout_id], check=True)
            self.current_lang = target
            self.title = icon
            logging.info(f"[FRUSTRATION] Switched {current} → {target}")
#            rumps.notification("LangSwitcher", "", f"Frustration detected! Switched to {target.upper()}")
        except Exception as e:
            logging.error(f"Frustration switch failed: {e}")

    def start_listener(self):
        def on_press(key):
            if not self.detecting:
                return
            
            # Track physical keys for frustration pattern detection
            vk_code = getattr(key, 'vk', None)
            if vk_code is not None:
                if key in BACKSPACE_KEYS:
                    self.track_key_event(vk_code, 'backspace')
                else:
                    self.track_key_event(vk_code, 'key')
            else:
                # Try alternative key identification for special keys
                key_name = str(key)
                if key in BACKSPACE_KEYS:
                    self.track_key_event(key_name, 'backspace')
                elif hasattr(key, 'char') and key.char:
                    # For regular character keys, use a fallback identifier
                    self.track_key_event(key_name, 'key')
            
            # Existing language detection logic
            try:
                ch = key.char
                if ch and (ch.isalpha() or ch in VALID_PUNCT):
                    self.word_buffer += ch
                    return
                if ch and ch.isspace():
                    self.process_buffer()
                    return
            except AttributeError:
                pass

            if key in WORD_BOUNDARY_KEYS:
                self.process_buffer()
            elif key in BACKSPACE_KEYS:
                self.word_buffer = self.word_buffer[:-1]
                logging.debug(f"[DEBUG] Buffer after backspace: '{self.word_buffer}'")

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

    def process_buffer(self):
        txt = self.word_buffer
        self.word_buffer = ""
        if not txt or len(txt) < MIN_WORD_LENGTH:
            return
        logging.debug(f"[DEBUG] Word typed: {txt}")
        self.detect_and_update_language(txt)

    def detect_and_update_language(self, text):
        try:
            probs = detect_langs(text)
        except LangDetectException:
            probs = []
        scores = {lang: next((p.prob for p in probs if p.lang == lang), 0.0)
                  for lang in DETECTION_LANGS}
        logging.debug(f"[DETECT] probs = {scores}")

        if max(scores.values(), default=0.0) < MODEL_CONFIDENCE_THRESHOLD:
            chosen = None
            for lang in DETECTION_LANGS:
                d = dicts.get(lang)
                if d and d.check(text) and not any(
                    dicts[o].check(text) for o in DETECTION_LANGS if o != lang
                ):
                    chosen = lang
                    logging.debug(f"[DETECT] Dict fallback → {lang}")
                    break
        else:
            chosen = max(scores, key=scores.get)

        if chosen is None:
            if FALLBACK_TO_BUFFER_ON_AMBIGUOUS and self.lang_buffer:
                chosen = self.lang_buffer[-1]
                logging.debug(f"[LANG] Ambiguous '{text}', inheriting '{chosen}'")
            else:
                chosen = self.current_lang
                logging.debug(f"[LANG] Ambiguous '{text}', staying '{chosen}'")

        self.lang_buffer.append(chosen)
        if len(self.lang_buffer) > BUFFER_SIZE:
            self.lang_buffer.pop(0)
        logging.debug(f"[BUFFER] {self.lang_buffer}")

        recent = self.lang_buffer[-SWITCH_THRESHOLD:]
        if (
            len(recent) == SWITCH_THRESHOLD
            and all(l == chosen for l in recent)
            and chosen != self.current_lang
        ):
            layout_id, icon = LAYOUTS[chosen]
            try:
                subprocess.run([IM_SELECT, layout_id], check=True)
                logging.info(f"[INPUT] Switched layout → {layout_id}")
            except Exception as e:
                logging.error(f"im-select failed: {e}")
                return
            self.current_lang = chosen
            self.title = icon
            logging.info(f"[LANG] Confirmed switch to {chosen.upper()} → '{text}'")


if __name__ == "__main__":
    LangSwitcherApp().run()