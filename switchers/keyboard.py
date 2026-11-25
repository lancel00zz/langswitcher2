"""Switch and translate keyboard layouts through native macOS input sources."""

from typing import Optional, Dict, Tuple

from .macos import NativeInputSources


class KeyboardSwitcher:
    """Main-thread native keyboard operations; no subprocess in the event tap."""

    def __init__(self, layouts: Dict[str, Tuple[str, str]], script_dir: str = None):
        self.layouts = layouts
        self.native = NativeInputSources([item[0] for item in layouts.values()])
        self._current_lang = None

    def get_current_layout(self) -> Optional[str]:
        layout_id = self.native.get_current_layout_id()
        for lang, (candidate, _) in self.layouts.items():
            if layout_id == candidate:
                self._current_lang = lang
                return lang
        return None

    def switch_to(self, target_lang: str) -> bool:
        if target_lang not in self.layouts:
            return False
        if self.native.select(self.layouts[target_lang][0]):
            self._current_lang = target_lang
            return True
        return False

    def translate_key(self, vk_code: int, flags: int, lang: str) -> Optional[str]:
        """Translate the confirming retry key in the newly selected layout."""
        if lang not in self.layouts:
            return None
        return self.native.translate_key(self.layouts[lang][0], vk_code, flags)

    def toggle(self, current_lang: str, available_langs: list) -> Optional[str]:
        if current_lang not in available_langs:
            return None
        current_index = available_langs.index(current_lang)
        target = available_langs[(current_index + 1) % len(available_langs)]
        return target if self.switch_to(target) else None

    def sync_state(self, app_lang: str) -> Optional[str]:
        return self.get_current_layout()

    def get_icon(self, lang: str) -> Optional[str]:
        return self.layouts[lang][1] if lang in self.layouts else None

    def close(self):
        self.native.close()
