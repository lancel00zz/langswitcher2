#!/usr/bin/env python3
# =============================================================================
# Language Switcher App
#
# 📋 Requirements:
#   • Python 3.10+ (tested on 3.11)
#   • rumps        – macOS menu bar application framework
#   • pynput       – global keyboard listener
#   • langdetect   – probabilistic language detection
#   • pyenchant    – spell‐checker / dictionary for fallback
#   • im-select    – CLI to switch macOS input sources
#
# 💾 Installation (run in your Terminal, outside any venv):
#   brew install enchant
#   pip3 install --break-system-packages rumps pynput langdetect pyenchant
#   curl -Ls -o /opt/homebrew/bin/im-select \
#     https://raw.githubusercontent.com/daipeihust/im-select/master/macOS/out/apple/im-select \
#     && chmod 755 /opt/homebrew/bin/im-select
#   export PATH="/opt/homebrew/bin:$PATH"
# =============================================================================

import os
import logging
import subprocess
import threading

import rumps
import enchant
from pynput import keyboard
from langdetect import detect_langs, LangDetectException

# ——— START CONFIGURATION ———

# 1) Which languages to detect (order matters for tie-break)
DETECTION_LANGS = ["en", "fr"]

# 2) Map each language → (im-select layout ID, menu-bar icon)
LAYOUTS = {
    "en": ("com.apple.keylayout.US",           "🇺🇸"),
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
}

# 3) Which enchant dictionaries to load
DICT_LANGS = {
    "en": "en_US",
    "fr": "fr_FR",
}

# 4) Rolling-buffer size (N) and switch threshold (K)
BUFFER_SIZE      = 4
SWITCH_THRESHOLD = 3

# 5) Minimum model confidence before falling back to dictionary
MODEL_CONFIDENCE_THRESHOLD = 0.5

# 6) Which punctuation / special chars to keep in words
VALID_PUNCT = ("'", "’", "-")

# 7) Which keys terminate a word
WORD_BOUNDARY_KEYS = {
    keyboard.Key.space,
    keyboard.Key.enter,
    # keyboard.Key.tab,  # enable if you want Tab to flush the word
}

# 8) Which keys mutate your buffer (backspace/delete)
BACKSPACE_KEYS = {
    keyboard.Key.backspace,
    keyboard.Key.delete,
}

# 9) Minimum word length to attempt detection
MIN_WORD_LENGTH = 2

# 10) How to handle ambiguous/unknown words:
#     True  → inherit the last buffered language
#     False → keep the current system layout
FALLBACK_TO_BUFFER_ON_AMBIGUOUS = True

# 11) Debug console:
#     False → no external console
#     True  → open Terminal and tail the debug log
DISPLAY_DEBUG_CONSOLE = True

# 12) Path for debug log file
DEBUG_LOG_PATH = os.path.expanduser("~/langswitcher.log")

# ——— END CONFIGURATION ———


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
    subprocess.Popen(["osascript", "-e", script])


class LangSwitcherApp(rumps.App):
    def __init__(self):
        super().__init__(LAYOUTS[DETECTION_LANGS[0]][1], menu=["Toggle Detection"])
        self.detecting    = True
        self.word_buffer  = ""
        self.lang_buffer  = []
        self.current_lang = DETECTION_LANGS[0]
        open_debug_console()
        threading.Thread(target=self.start_listener, daemon=True).start()

    @rumps.clicked("Toggle Detection")
    def toggle_detection(self, _):
        self.detecting = not self.detecting
        state = "ON" if self.detecting else "OFF"
        rumps.notification("LangSwitcher", "", f"Detection is now {state}")
        logging.info(f"Detection toggled {state}")

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

        if max(scores.values(), default=0) < MODEL_CONFIDENCE_THRESHOLD:
            for lang in DETECTION_LANGS:
                en_ok = dicts[lang].check(text)
                other_ok = any(dicts[o].check(text) for o in DETECTION_LANGS if o != lang)
                if en_ok and not other_ok:
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
        if (len(recent) == SWITCH_THRESHOLD
            and all(l == lang for l in recent)
            and lang != self.current_lang):
            layout_id, icon = LAYOUTS[lang]
            try:
                subprocess.run(["im-select", layout_id], check=True)
                logging.info(f"[INPUT] Switched layout → {layout_id}")
            except Exception as e:
                logging.error(f"[ERROR] im-select failed: {e}")
                return
            self.current_lang = lang
            self.title = icon
            logging.info(f"[LANG] Confirmed switch to {lang.upper()} → '{text}'")


if __name__ == "__main__":
    LangSwitcherApp().run()