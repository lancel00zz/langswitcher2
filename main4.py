#!/usr/bin/env python3
import rumps
from pynput import keyboard
import threading
from langdetect import detect_langs, LangDetectException
import enchant
import subprocess

# 📌 Exact im-select IDs
LAYOUTS = {
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
    "en": ("com.apple.keylayout.US",           "🇺🇸"),
}

BUFFER_SIZE      = 4   # N
SWITCH_THRESHOLD = 3   # K

# Create English and French dictionaries
dict_en = enchant.Dict("en_US")
dict_fr = enchant.Dict("fr_FR")

class LangSwitcherApp(rumps.App):
    def __init__(self):
        super().__init__("🇺🇸", menu=["Toggle Detection"])
        self.detecting    = True
        self.word_buffer  = ""
        self.lang_buffer  = []      # holds recent 'fr'/'en'
        self.current_lang = "en"    # assume English to start
        threading.Thread(target=self.start_listener, daemon=True).start()

    @rumps.clicked("Toggle Detection")
    def toggle_detection(self, _):
        self.detecting = not self.detecting
        rumps.notification(
            "LangSwitcher", "",
            f"Detection is now {'ON' if self.detecting else 'OFF'}"
        )

    def start_listener(self):
        def on_press(key):
            if not self.detecting:
                return
            try:
                if key.char and key.char.isalpha():
                    self.word_buffer += key.char
                elif key.char == " ":
                    self.process_buffer()
            except AttributeError:
                if key == keyboard.Key.space:
                    self.process_buffer()

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
        """Return 'en' or 'fr' by ML probability, then fallback to dict."""
        try:
            probs = detect_langs(text)
        except LangDetectException:
            p_en = p_fr = 0.0
        else:
            # extract probabilities
            p_fr = next((p.prob for p in probs if p.lang == "fr"), 0.0)
            p_en = next((p.prob for p in probs if p.lang == "en"), 0.0)

        # If neither model is confident, use dictionary fallback
        if max(p_en, p_fr) < 0.5:
            en_valid = dict_en.check(text)
            fr_valid = dict_fr.check(text)
            # if only one dictionary accepts it, choose that
            if fr_valid and not en_valid:
                return "fr"
            if en_valid and not fr_valid:
                return "en"
            # else leave to model below

        # Otherwise pick the higher-prob one (if >0)
        if p_fr >= p_en and p_fr > 0:
            return "fr"
        if p_en > p_fr:
            return "en"
        # No clear signal
        return None

    def detect_and_update_language(self, text):
        # 1) force to fr/en only
        lang = self.detect_en_or_fr(text)
        if lang is None:
            print(f"[LANG] No clear EN/FR for '{text}', keeping '{self.current_lang}'")
            return

        # 2) update rolling buffer
        self.lang_buffer.append(lang)
        if len(self.lang_buffer) > BUFFER_SIZE:
            self.lang_buffer.pop(0)
        print(f"[BUFFER] {self.lang_buffer}")

        # 3) switch if last K are the same & different from current
        recent = self.lang_buffer[-SWITCH_THRESHOLD:]
        if (len(recent) == SWITCH_THRESHOLD
            and all(l == lang for l in recent)
            and lang != self.current_lang):
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