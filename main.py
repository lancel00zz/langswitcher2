import rumps
from pynput import keyboard
import threading
from langdetect import detect

class LangSwitcherApp(rumps.App):
    def __init__(self):
        super().__init__("🇺🇸", menu=["Toggle Detection"])
        self.detecting = True
        self.word_buffer = ""
        self.listener_thread = threading.Thread(target=self.start_listener, daemon=True)
        self.listener_thread.start()

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
                if key.char.isalpha():
                    self.word_buffer += key.char
                elif key.char == ' ':
                    if self.word_buffer:
                        print(f"[DEBUG] Word typed: {self.word_buffer}")
                        self.detect_and_update_language(self.word_buffer)
                        self.word_buffer = ""
            except AttributeError:
                if key == keyboard.Key.space:
                    if self.word_buffer:
                        print(f"[DEBUG] Word typed: {self.word_buffer}")
                        self.detect_and_update_language(self.word_buffer)
                        self.word_buffer = ""

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

    def detect_and_update_language(self, text):
        try:
            lang = detect(text)
            if lang == "fr":
                self.title = "🇫🇷"
                print(f"[LANG] French detected → '{text}'")
            elif lang == "en":
                self.title = "🇺🇸"
                print(f"[LANG] English detected → '{text}'")
            else:
                print(f"[LANG] Unknown or other language → '{text}'")
        except Exception as e:
            print(f"[ERROR] Language detection failed: {e}")

if __name__ == "__main__":
    LangSwitcherApp().run()