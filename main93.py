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
VERSION = "2.0"
DETECTION_LANGS = ["en", "fr"]
LAYOUTS = {
    "en": ("com.apple.keylayout.US",           "🇺🇸"),
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
}
DICT_LANGS = {"en": "en_US", "fr": "fr_FR"}
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

        # Window size & center
        Ww, Wh = 320, 450
        rect = NSMakeRect(0, 0, Ww, Wh)
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )
        self.win.setTitle_("Lang Switcher Preferences")
        self.win.center()

        # Content dims
        cf = self.win.contentView().frame()
        W, H = cf.size.width, cf.size.height

        # Layout parameters
        LABEL_X = W * 0.05
        FIELD_X = W * 0.55
        CW, CH  = W * 0.40, 24
        SPY     = 50
        y       = H - CH - 30

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

        # Rows
        self.buf_tf  = textf(BUFFER_SIZE,      y); label("Buffer size:",      y)
        y -= SPY
        self.th_tf   = textf(SWITCH_THRESHOLD, y); label("Switch threshold:", y)
        y -= SPY
        self.min_tf  = textf(MIN_WORD_LENGTH,  y); label("Min word length:",  y)
        y -= SPY
        self.fb_sw   = sw(FALLBACK_TO_BUFFER_ON_AMBIGUOUS, y); label("Fallback to buffer:", y)
        y -= SPY
        self.db_sw   = sw(DISPLAY_DEBUG_CONSOLE,           y); label("Display debug console:", y)
        y -= SPY

        # Status lines
        langs   = ", ".join(DETECTION_LANGS)
        dicts_s = ", ".join(DICT_LANGS[l] for l in DETECTION_LANGS)
        label(f"Detection languages: {langs}", y)
        y -= CH + 10
        label(f"Dictionaries: {dicts_s}", y)
        y -= SPY

        # Save button
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
            notify = 'tell application "System Events" to display dialog "Settings saved; restarting..." buttons {"OK"}'
            subprocess.Popen(
                ["osascript", "-e", notify],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            err = f'tell application "System Events" to display dialog "Error: {e}" buttons {{"OK"}}'
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
        self.buffer    = ""
        self.langbuf   = []
        self.current   = DETECTION_LANGS[0]

        open_debug_console()
        threading.Thread(target=self._listen, daemon=True).start()

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
        logging.info(f"Toggled {state}")

    @rumps.clicked("Quit")
    def quit(self, _):
        rumps.quit_application()

    def _listen(self):
        def on_press(key):
            if not self.detecting:
                return
            try:
                ch = key.char
                if ch and (ch.isalpha() or ch in VALID_PUNCT):
                    self.buffer += ch
                    return
                if ch and ch.isspace():
                    self._proc()
                    return
            except:
                pass
            if key in WORD_BOUNDARY_KEYS:
                self._proc()
            elif key in BACKSPACE_KEYS:
                self.buffer = self.buffer[:-1]

        # <<-- corrected here: capture the listener as `listener`
        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

    def _proc(self):
        word, self.buffer = self.buffer, ""
        if len(word) < MIN_WORD_LENGTH:
            return
        logging.debug(f"Word: {word}")
        self._detect(word)

    def _detect(self, txt):
        try:
            probs = detect_langs(txt)
        except LangDetectException:
            probs = []
        scores = {l: next((p.prob for p in probs if p.lang == l), 0) for l in DETECTION_LANGS}
        if max(scores.values(), default=0) < MODEL_CONFIDENCE_THRESHOLD:
            lang = None
            for l in DETECTION_LANGS:
                d = dicts[l]
                if d.check(txt) and not any(dicts[o].check(txt) for o in DETECTION_LANGS if o != l):
                    lang = l
                    break
        else:
            lang = max(scores, key=scores.get)

        if lang is None:
            lang = (
                self.langbuf[-1]
                if FALLBACK_TO_BUFFER_ON_AMBIGUOUS and self.langbuf
                else self.current
            )

        self.langbuf.append(lang)
        if len(self.langbuf) > BUFFER_SIZE:
            self.langbuf.pop(0)

        recent = self.langbuf[-SWITCH_THRESHOLD:]
        if (
            len(recent) == SWITCH_THRESHOLD
            and all(r == lang for r in recent)
            and lang != self.current
        ):
            layout, emoji = LAYOUTS[lang]
            try:
                subprocess.run(["im-select", layout], check=True)
            except Exception:
                return
            self.current = lang
            self.title   = emoji
            logging.info(f"Switched to {lang}")


if __name__ == "__main__":
    LangSwitcherApp().run()