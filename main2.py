#!/usr/bin/env python3
import rumps
from pynput import keyboard
import threading
from langdetect import detect
import subprocess

# Map language codes to im-select IDs and icons
LAYOUTS = {
    "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
    "en": ("com.apple.keylayout.US",           "🇺🇸"),
}

class LangSwitcherApp(rumps.App):
    def __init__(self):
        super().__init__("🇺🇸", menu=["Toggle Detection"])
        self.detecting = True
        self.word_buffer = ""
        # Start listener in background
        threading.Thread(target=self.start_listener, daemon=True).start()

    @rumps.clicked("Toggle Detection")
    def toggle_detection(self, _):
        self.detecting = not self.detecting
        state = "ON" if self.detecting else "OFF"
        rumps.notification("LangSwitcher", "", f"Detection is now {state}")

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
                # space (and ignore all other special keys)
                if key == keyboard.Key.space:
                    self.process_buffer()

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

    def process_buffer(self):
        if not self.word_buffer:
            return
        txt = self.word_buffer
        self.word_buffer = ""
        print(f"[DEBUG] Word typed: {txt}")
        self.detect_and_update_language(txt)

    def detect_and_update_language(self, text):
        try:
            lang = detect(text)
        except Exception as e:
            print(f"[ERROR] Lang detect failed: {e}")
            return

        # Only proceed if we have a mapping
        if lang in LAYOUTS:
            layout_id, icon = LAYOUTS[lang]
            # Switch OS keyboard layout
            try:
                subprocess.run(["im-select", layout_id], check=True)
                print(f"[INPUT] Switched layout → {layout_id}")
            except Exception as e:
                print(f"[ERROR] im-select failed: {e}")

            # Update menu-bar icon
            self.title = icon
            print(f"[LANG] { 'French' if lang=='fr' else 'English' } detected → '{text}'")

        else:
            print(f"[LANG] Other/unknown language ({lang}) → '{text}'")
            # Optionally, you could set a neutral icon here

if __name__ == "__main__":
    LangSwitcherApp().run()