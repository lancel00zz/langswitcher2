#!/usr/bin/env python3
import rumps
from pynput import keyboard
import threading
from langdetect import detect, LangDetectException
import subprocess

# ⚠️ Case-sensitive IDs exactly as reported by `im-select list`
LAYOUTS = {
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
    "en": ("com.apple.keylayout.US",           "🇺🇸"),
}

BUFFER_SIZE = 4    # N
SWITCH_THRESHOLD = 3  # K

class LangSwitcherApp(rumps.App):
    def __init__(self):
        super().__init__("🇺🇸", menu=["Toggle Detection"])
        self.detecting    = True
        self.word_buffer  = ""
        self.lang_buffer  = []     # rolling buffer of recent detections
        self.current_lang = "en"   # assume starting in English
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
                elif key.char == ' ':
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

    def detect_and_update_language(self, text):
        # 1) Attempt language detection
        try:
            lang = detect(text)
        except LangDetectException:
            print(f"[ERROR] Lang detect failed on '{text}'")
            return

        # 2) Only buffer if it's a language we care about
        if lang not in LAYOUTS:
            print(f"[LANG] Skipping unknown/unsupported ({lang}) → '{text}'")
            return

        # 3) Update rolling buffer
        self.lang_buffer.append(lang)
        if len(self.lang_buffer) > BUFFER_SIZE:
            self.lang_buffer.pop(0)

        print(f"[BUFFER] {self.lang_buffer}")

        # 4) Check last K entries
        recent = self.lang_buffer[-SWITCH_THRESHOLD:]
        if len(recent) == SWITCH_THRESHOLD and all(l == lang for l in recent):
            # Only switch if different from current
            if lang != self.current_lang:
                layout_id, icon = LAYOUTS[lang]
                try:
                    subprocess.run(["im-select", layout_id], check=True)
                    print(f"[INPUT] Switched layout → {layout_id}")
                except Exception as e:
                    print(f"[ERROR] im-select failed: {e}")
                    return
                self.current_lang = lang
                self.title = icon
                print(f"[LANG] Confirmed {lang.upper()} → '{text}'")

if __name__ == "__main__":
    LangSwitcherApp().run()