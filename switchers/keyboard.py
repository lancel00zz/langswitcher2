"""
Keyboard Layout Switcher

Handles switching between keyboard layouts using im-select.
"""

import os
import subprocess
import logging
from shutil import which
from typing import Optional, Dict, Tuple


class KeyboardSwitcher:
    """Manages keyboard layout switching"""
    
    def __init__(self, layouts: Dict[str, Tuple[str, str]], script_dir: str = None):
        """
        Initialize keyboard switcher
        
        Args:
            layouts: Dictionary mapping language codes to (layout_id, icon)
            script_dir: Directory containing bundled im-select (optional)
        """
        self.layouts = layouts
        self.im_select = self._find_im_select(script_dir)
        self._current_lang = None
        
        if not self.im_select:
            logging.warning("im-select not found - keyboard switching will fail")
    
    def _find_im_select(self, script_dir: str = None) -> Optional[str]:
        """Find im-select executable"""
        # Try bundled version first
        if script_dir:
            bundled_im = os.path.join(script_dir, 'im-select')
            if os.path.isfile(bundled_im) and os.access(bundled_im, os.X_OK):
                logging.debug(f"Using bundled im-select: {bundled_im}")
                return bundled_im
        
        # Try system PATH
        system_im = which('im-select')
        if system_im:
            logging.debug(f"Using system im-select: {system_im}")
            return system_im
        
        return None
    
    def get_current_layout(self) -> Optional[str]:
        """
        Query the actual current macOS keyboard layout
        
        Returns:
            Language code of current layout, or None if detection fails
        """
        if not self.im_select:
            return None
        
        try:
            result = subprocess.run(
                [self.im_select],
                capture_output=True,
                text=True,
                check=True,
                timeout=1.0
            )
            current_layout_id = result.stdout.strip()
            
            # Map layout ID back to language
            for lang, (layout_id, _icon) in self.layouts.items():
                if layout_id == current_layout_id:
                    self._current_lang = lang
                    return lang
            
            logging.warning(f"Unknown layout ID: {current_layout_id}")
            return None
        except subprocess.TimeoutExpired:
            logging.error("im-select timed out")
            return None
        except Exception as e:
            logging.error(f"Failed to get current layout: {e}")
            return None
    
    def switch_to(self, target_lang: str) -> bool:
        """
        Switch to specified language layout
        
        Args:
            target_lang: Target language code
            
        Returns:
            True if successful, False otherwise
        """
        if not self.im_select:
            logging.error("Cannot switch: im-select not available")
            return False
        
        if target_lang not in self.layouts:
            logging.error(f"Unknown language: {target_lang}")
            return False
        
        layout_id, _icon = self.layouts[target_lang]
        
        try:
            subprocess.run(
                [self.im_select, layout_id],
                check=True,
                timeout=1.0,
                capture_output=True
            )
            self._current_lang = target_lang
            logging.info(f"Switched to layout: {layout_id} ({target_lang})")
            return True
        except subprocess.TimeoutExpired:
            logging.error(f"Layout switch timed out for {target_lang}")
            return False
        except Exception as e:
            logging.error(f"Failed to switch to {target_lang}: {e}")
            return False
    
    def toggle(self, current_lang: str, available_langs: list) -> Optional[str]:
        """
        Toggle to the next available language
        
        Args:
            current_lang: Current language code
            available_langs: List of available language codes
            
        Returns:
            New language code if successful, None otherwise
        """
        if current_lang not in available_langs:
            logging.warning(f"Current lang {current_lang} not in available langs")
            return None
        
        # Get next language in cycle
        current_idx = available_langs.index(current_lang)
        next_idx = (current_idx + 1) % len(available_langs)
        target_lang = available_langs[next_idx]
        
        if self.switch_to(target_lang):
            return target_lang
        return None
    
    def sync_state(self, app_lang: str) -> Optional[str]:
        """
        Synchronize app state with actual macOS layout
        
        Args:
            app_lang: What the app thinks the current language is
            
        Returns:
            Actual current language, or None if detection fails
        """
        actual_lang = self.get_current_layout()
        
        if actual_lang is None:
            return None
        
        if actual_lang != app_lang:
            logging.info(f"Detected desync: app={app_lang}, macOS={actual_lang}")
            logging.info(f"App state should be updated to {actual_lang}")
        
        return actual_lang
    
    def get_icon(self, lang: str) -> Optional[str]:
        """Get the icon/emoji for a language"""
        if lang in self.layouts:
            return self.layouts[lang][1]
        return None

