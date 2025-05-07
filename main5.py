#!/usr/bin/env python3
import rumps
from pynput import keyboard
import threading
from langdetect import detect_langs, LangDetectException
import enchant
import subprocess

# ——— Configuration ———
LAYOUTS = {
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
    "en": ("com.apple.keylayout.US",           "🇺🇸"),
}
BUFFER_SIZE      = 4   # N
SWITCH_THRESHOLD = 3   # K
VALID_PUNCT      = ("'", "’")  # Allow these in words

# Prepare dictionaries
dict_en = enchant.Dict("en_US")
dict_fr = enchant.Dict("fr_FR")


class LangSwitcherApp(rumps.App):
    def __init__(self):
        super().__init__("🇺🇸", menu=["Toggle Detection"])
        self.detecting    = True
        self.word_buffer  = ""
        self.lang_buffer  = []      # only 'en'/'fr'
        self.current_lang = "en"    # assume U.S. start
        threading.Thread(target=self.start_listener, daemon=True).start()

    @rumps.clicked("Toggle Detection")
    def toggle_detection(self, _):
        self.detecting = not self.detecting
        rumps.notification("LangSwitcher", "",
            f"Detection is now {'ON' if self.detecting else 'OFF'}"
        )

    def start_listener(self):
        def on_press(key):
            if not self.detecting:
                return

            # Handle normal character input
            try:
                ch = key.char
                if ch is not None:
                    if ch.isalpha() or ch in VALID_PUNCT:
                        # add letter or apostrophe
                        self.word_buffer += ch
                        return
                    if ch.isspace():
                        # space key via char → end of word
                        self.process_buffer()
                        return
            except AttributeError:
                # special keys fall here
                pass

            # Handle non-char keys
            if key == keyboard.Key.space:
                self.process_buffer()
            elif key in (keyboard.Key.backspace, keyboard.Key.delete):
                # remove last character
                self.word_buffer = self.word_buffer[:-1]
                print(f"[DEBUG] Backspace → buffer now: '{self.word_buffer}'")

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

    def process_buffer(self):
        txt = self.word_buffer
        self.word_buffer = ""
        if not txt:
            return
        print(f"[DEBUG] Word typed: {txt}")
        self.detect_and_update_language(txt)

    def detect_en_or_fr(self, text):
        """Return 'en' or 'fr' by ML probabilities, then dict fallback."""
        try:
            probs = detect_langs(text)
        except LangDetectException:
            p_en = p_fr = 0.0
        else:
            p_fr = next((p.prob for p in probs if p.lang=="fr"), 0.0)
            p_en = next((p.prob for p in probs if p.lang=="en"), 0.0)

        # if neither confident, use dictionaries
        if max(p_en, p_fr) < 0.5:
            en_ok = dict_en.check(text)
            fr_ok = dict_fr.check(text)
            if fr_ok and not en_ok:
                return "fr"
            if en_ok and not fr_ok:
                return "en"

        if p_fr >= p_en and p_fr>0:
            return "fr"
        if p_en > p_fr:
            return "en"
        return None

    def detect_and_update_language(self, text):
        lang = self.detect_en_or_fr(text)
        if lang is None:
            print(f"[LANG] No clear EN/FR for '{text}', keeping '{self.current_lang}'")
            return

        # update buffer and show
        self.lang_buffer.append(lang)
        if len(self.lang_buffer) > BUFFER_SIZE:
            self.lang_buffer.pop(0)
        print(f"[BUFFER] {self.lang_buffer}")

        # switch if last K consistent and differ from current
        recent = self.lang_buffer[-SWITCH_THRESHOLD:]
        if (len(recent)==SWITCH_THRESHOLD
            and all(l==lang for l in recent)
            and lang!=self.current_lang):
            layout_id, icon = LAYOUTS[lang]
            try:
                subprocess.run(["im-select", layout_id], check=True)
                print(f"[INPUT] Switched layout → {layout_id}")
            except Exception as e:
                print(f"[ERROR] im-select failed: {e}")
                return
            self.current_lang = lang
            self.title = icon
            print(f"[LANG] Confirmed switch to {lang.upper()} → '{text}'")


if __name__ == "__main__":
    LangSwitcherApp().run()