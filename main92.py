#!/usr/bin/env python3
import os
import sys
import json
import threading
import logging
import pathlib
import subprocess

import rumps
import enchant
from pynput import keyboard
from langdetect import detect_langs, LangDetectException

# PyObjC imports — make sure these are here so NSObject is defined!
from Cocoa import (
    NSApp,
    NSWindow,
    NSBackingStoreBuffered,
    NSTextField,
    NSButton,
    NSSwitch,
    NSRunningApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSObject,
    NSApplication,
    NSMakeRect,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
)
import objc

# ——— START CONFIGURATION ———
VERSION = "2.0"
DETECTION_LANGS = ["en", "fr"]
LAYOUTS = {
    "en": ("com.apple.keylayout.US",           "🇺🇸"),
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
}
DICT_LANGS = {
    "en": "en_US",
    "fr": "fr_FR",
}
BUFFER_SIZE      = 4
SWITCH_THRESHOLD = 3
MIN_WORD_LENGTH  = 2
MODEL_CONFIDENCE_THRESHOLD = 0.5
FALLBACK_TO_BUFFER_ON_AMBIGUOUS = True
DISPLAY_DEBUG_CONSOLE          = False
DEBUG_LOG_PATH = os.path.expanduser("~/langswitcher.log")
VALID_PUNCT = ("'", "’", "-")
WORD_BOUNDARY_KEYS = { keyboard.Key.space, keyboard.Key.enter }
BACKSPACE_KEYS     = { keyboard.Key.backspace, keyboard.Key.delete }
# ——— END CONFIGURATION ———

# Load overrides from JSON config (if present)
_conf_path = pathlib.Path(__file__).with_suffix(".conf.json")
if _conf_path.exists():
    try:
        overrides = json.loads(_conf_path.read_text())
        globals().update(overrides)
    except Exception:
        pass

# Setup logging
logging.basicConfig(
    filename=DEBUG_LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s %(message)s"
)

# Prepare enchant dictionaries
dicts = {lang: enchant.Dict(code) for lang, code in DICT_LANGS.items()}


def open_debug_console():
    """If enabled, open a Terminal window tailing the log file."""
    if not DISPLAY_DEBUG_CONSOLE:
        return
    script = f'''
    tell application "Terminal"
      activate
      do script "tail -f {DEBUG_LOG_PATH}"
    end tell
    '''
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class PrefsWindow(NSObject):
    """A Cocoa window whose controls are laid out relative to the window size."""
    def init(self):
        self = objc.super(PrefsWindow, self).init()
        if not self:
            return None

        # ─── Window setup ───
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

        # Get dynamic content area size
        content_frame = self.win.contentView().frame()
        W, H = content_frame.size.width, content_frame.size.height

        # Layout constants
        LEFT_LABEL_X  = W * 0.05
        LEFT_FIELD_X  = W * 0.55
        CONTROL_W     = W * 0.40
        CONTROL_H     = 24
        SPACING_Y     = 50
        TOP_MARGIN    = H - CONTROL_H - 30

        # Helpers
        def add_label(text, y):
            lbl = NSTextField.alloc().initWithFrame_(
                NSMakeRect(LEFT_LABEL_X, y, CONTROL_W, CONTROL_H)
            )
            lbl.setStringValue_(text)
            lbl.setBezeled_(False)
            lbl.setDrawsBackground_(False)
            lbl.setEditable_(False)
            self.win.contentView().addSubview_(lbl)

        def add_textfield(default, y):
            tf = NSTextField.alloc().initWithFrame_(
                NSMakeRect(LEFT_FIELD_X, y, CONTROL_W, CONTROL_H)
            )
            tf.setStringValue_(str(default))
            self.win.contentView().addSubview_(tf)
            return tf

        def add_switch(default, y):
            sw = NSSwitch.alloc().initWithFrame_(
                NSMakeRect(LEFT_FIELD_X, y, 40, CONTROL_H)
            )
            sw.setState_(1 if default else 0)
            self.win.contentView().addSubview_(sw)
            return sw

        # ─── Build controls ───
        y = TOP_MARGIN
        self.buf_size_tf  = add_textfield(BUFFER_SIZE,      y); add_label("Buffer size:",      y)
        y -= SPACING_Y
        self.threshold_tf = add_textfield(SWITCH_THRESHOLD, y); add_label("Switch threshold:", y)
        y -= SPACING_Y
        self.minlen_tf    = add_textfield(MIN_WORD_LENGTH,  y); add_label("Min word length:",  y)
        y -= SPACING_Y
        self.fb_switch    = add_switch(FALLBACK_TO_BUFFER_ON_AMBIGUOUS, y); add_label("Fallback to buffer:", y)
        y -= SPACING_Y
        self.dbg_switch   = add_switch(DISPLAY_DEBUG_CONSOLE, y);          add_label("Display debug console:", y)
        y -= SPACING_Y

        # ─── Status labels ───
        langs  = ", ".join(DETECTION_LANGS)
        dicts_ = ", ".join(DICT_LANGS[lang] for lang in DETECTION_LANGS)
        add_label(f"Detection languages: {langs}", y)
        y -= CONTROL_H + 10
        add_label(f"Dictionaries: {dicts_}", y)
        y -= SPACING_Y

        # ─── Save button ───
        btn_w, btn_h = 100, 32
        btn_x = (W - btn_w) / 2
        btn_y = y - 10
        btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(btn_x, btn_y, btn_w, btn_h)
        )
        btn.setTitle_("Save")
        btn.setBezelStyle_(1)
        btn.setTarget_(self)
        btn.setAction_("savePrefs:")
        self.win.contentView().addSubview_(btn)

        return self

    def savePrefs_(self, _):
        try:
            new = {
                "BUFFER_SIZE": int(self.buf_size_tf.stringValue()),
                "SWITCH_THRESHOLD": int(self.threshold_tf.stringValue()),
                "MIN_WORD_LENGTH": int(self.minlen_tf.stringValue()),
                "FALLBACK_TO_BUFFER_ON_AMBIGUOUS": bool(self.fb_switch.state()),
                "DISPLAY_DEBUG_CONSOLE": bool(self.dbg_switch.state()),
            }
            _conf_path.write_text(json.dumps(new, indent=2))
            NSApp.stop_(None)
            subprocess.Popen(
                ["osascript", "-e",
                 'tell application "System Events" to display dialog "Settings saved; restarting..." buttons {"OK"}'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            subprocess.Popen(
                ["osascript", "-e",
                 f'tell application "System Events" to display dialog "Error: {e}" buttons {{"OK"}}'],
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
        lang_icon = LAYOUTS[DETECTION_LANGS[0]][1]
        version_item = rumps.MenuItem(f"Lang Switcher {VERSION} by pza", callback=lambda _: None)

        super().__init__(
            name="LangSwitcher",
            icon=None,
            title=lang_icon,
            menu=[
                "Toggle Detection",
                "Settings…",
                "Quit",
                None,
                version_item
            ],
            quit_button=None
        )

        self.detecting    = True
        self.word_buffer  = ""
        self.lang_buffer  = []
        self.current_lang = DETECTION_LANGS[0]

        open_debug_console()
        threading.Thread(target=self.start_listener, daemon=True).start()

    @rumps.clicked("Settings…")
    def open_settings(self, _):
        app = NSApplication.sharedApplication()
        pw = PrefsWindow.alloc().init()
        pw.run()

    @rumps.clicked("Toggle Detection")
    def toggle_detection(self, _):
        self.detecting = not self.detecting
        state = "ON" if self.detecting else "OFF"
        rumps.notification("LangSwitcher", "", f"Detection is now {state}")
        logging.info(f"Detection toggled {state}")

    @rumps.clicked("Quit")
    def quit_app(self, _):
        rumps.quit_application()

    def start_listener(self):
        def on_press(key):
            if not self.detecting:
                return
            try:
                ch = key.char
                if ch is not None:
                    if ch.isalpha() or ch in VALID_PUNCT:
                        self.word_buffer += ch
                        return
                    if ch.isspace():
                        self.process_buffer()
                        return
            except AttributeError:
                pass

            if key in WORD_BOUNDARY_KEYS:
                self.process_buffer()
            elif key in BACKSPACE_KEYS:
                self.word_buffer = self.word_buffer[:-1]
                logging.debug(f"Backspace → buffer now: '{self.word_buffer}'")

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

    def process_buffer(self):
        txt = self.word_buffer
        self.word_buffer = ""
        if not txt or len(txt) < MIN_WORD_LENGTH:
            return
        logging.debug(f"[DEBUG] Word typed: {txt}")
        self.detect_and_update_language(txt)

    def detect_en_or_fr(self, text):
        try:
            probs = detect_langs(text)
        except LangDetectException:
            probs = []
        scores = {lang: next((p.prob for p in probs if p.lang == lang), 0.0)
                  for lang in DETECTION_LANGS}
        if max(scores.values(), default=0.0) < MODEL_CONFIDENCE_THRESHOLD:
            for lang in DETECTION_LANGS:
                d = dicts.get(lang)
                if d and d.check(text) and not any(
                        dicts[o].check(text) for o in DETECTION_LANGS if o != lang):
                    return lang
        best = max(scores, key=lambda k: scores[k])
        return best if scores[best] > 0 else None

    def detect_and_update_language(self, text):
        lang = self.detect_en_or_fr(text)
        if lang is None:
            if FALLBACK_TO_BUFFER_ON_AMBIGUOUS and self.lang_buffer:
                lang = self.lang_buffer[-1]
                logging.debug(f"[LANG] Ambiguous '{text}', inheriting '{lang}'")
            else:
                lang = self.current_lang
                logging.debug(f"[LANG] Ambiguous '{text}', staying '{lang}'")

        self.lang_buffer.append(lang)
        if len(self.lang_buffer) > BUFFER_SIZE:
            self.lang_buffer.pop(0)
        logging.debug(f"[BUFFER] {self.lang_buffer}")

        recent = self.lang_buffer[-SWITCH_THRESHOLD:]
        if len(recent) == SWITCH_THRESHOLD and all(l == lang for l in recent) and lang != self.current_lang:
            layout_id, icon = LAYOUTS[lang]
            try:
                subprocess.run(["im-select", layout_id], check=True)
                logging.info(f"[INPUT] Switched layout → {layout_id}")
            except Exception as e:
                logging.error(f"im-select failed: {e}")
                return
            self.current_lang = lang
            self.title = icon
            logging.info(f"[LANG] Confirmed switch to {lang.upper()} → '{text}'")


if __name__ == "__main__":
    LangSwitcherApp().run()