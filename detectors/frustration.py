"""
Frustration Pattern Detection Module

Detects deletion of a layout-specific key, including after deleting a word suffix.
An eligible deletion lets the caller arm a retry; it does not switch the layout.
The caller switches only when the same physical key is retried within 2.5 seconds.
This detector never injects keystrokes.
"""

import time
import logging
import math
from typing import Optional, Dict, Any, List


class FrustrationDetector:
    """Detects eligible deletions that can arm a same-key retry correction."""

    WORD_BOUNDARY_KEYS = {49, 36, 76}  # Space, Return, keypad Enter.
    
    # VK codes for keys that produce DIFFERENT characters in US vs French layouts
    # Only deletion of these keys can arm a same-key retry correction.
    # Letters are NOT included - they're the same in both layouts
    FRUSTRATION_ELIGIBLE_KEYS = {
        # Punctuation/special keys (VK_code: description)
        44: "/ key (US: / ? | FR: é É)",
        47: "/ key variant (same as above)",
        33: "[ key (US: [ { | FR: ^ ^)",
        30: "] key (US: ] } | FR: $ ¤)",
        50: "` key (US: ` ~ | FR: #/@ \\|)",
        43: ", key (US: , < | FR: , ')",
        41: ";",
        39: "'",
        42: "|",
        22: "^",
        # Add more as discovered using vk_discovery.py
    }
    
    def __init__(
        self,
        time_window: float = 1.5,
        cooldown: float = 0.0,
        correction_timeout: float = 2.5
    ):
        """
        Initialize frustration detector
        
        Args:
            time_window: Legacy configuration value; no longer gates gestures.
            cooldown: Legacy configuration value; no longer gates gestures.
            correction_timeout: Maximum idle time while typing or deleting toward an eligible key.
        """
        correction_timeout = float(correction_timeout)
        if not math.isfinite(correction_timeout) or correction_timeout <= 0:
            raise ValueError('correction_timeout must be positive and finite')
        self.time_window = time_window
        self.cooldown = cooldown
        self.correction_timeout = correction_timeout
        
        self.key_history: List[Dict[str, Any]] = []
        self._suffix_length = 0
        self._last_activity_time: Optional[float] = None
        # Legacy diagnostic name: this records a deletion, not a layout switch.
        self.last_switch_time: Optional[float] = None
        self._last_triggered_key: Optional[Any] = None
    
    def track_key_event(self, vk_code: Any, event_type: str, text: Optional[str] = None) -> bool:
        """
        Track a key event and check whether an eligible character was deleted.
        
        Remember the most recent eligible key and how many characters follow
        it within the current word. Deleting that key lets the caller arm a
        retry; a later same-key press confirms the switch in the caller.
        Text is inspected for boundaries but never retained.
        
        Args:
            vk_code: Virtual key code or key identifier
            event_type: Either 'key' for regular key press or 'backspace'
            text: Optional printable text, used only to recognize boundaries
            
        Returns:
            True if an eligible key was deleted and a retry can be armed; False otherwise.
        """
        # After an idle pause, Backspace is an ordinary edit. Typing or deleting
        # the suffix keeps an active correction alive; there is no cooldown.
        now = time.monotonic()
        if (self.key_history and self._last_activity_time is not None and
                now - self._last_activity_time >= self.correction_timeout):
            self.clear_history()
        event = {
            'timestamp': now,
            'vk_code': vk_code,
            'type': event_type
        }
        if event_type == 'key':
            if (vk_code in self.WORD_BOUNDARY_KEYS or
                    (text is not None and (not text.isprintable() or any(ch.isspace() for ch in text))) or
                    (vk_code is None and text is None)):
                self.clear_history()
                return False
            self._last_triggered_key = None
            if vk_code in self.FRUSTRATION_ELIGIBLE_KEYS:
                # Only the latest eligible key can be reached first. The first
                # eligible deletion consumes the run, so older candidates
                # never need to be stored.
                self.key_history = [event]
                self._suffix_length = 0
                self._last_activity_time = now
            elif self.key_history:
                self._suffix_length += 1
                self._last_activity_time = now
        elif event_type == 'backspace':
            if not self.key_history:
                return False
            if self._suffix_length:
                self._suffix_length -= 1
                self._last_activity_time = now
                return False
            deleted = self.key_history.pop()
            vk_code = deleted['vk_code']
            # Consume the deletion run: held/repeated Backspace cannot arm
            # another retry on an eligible key deeper in the same word.
            self.clear_history()
            logging.info(f"[FRUSTRATION] Eligible deletion for same-key retry VK={vk_code}")
            self.last_switch_time = now
            self._last_triggered_key = vk_code
            return True
        else:
            self.clear_history()
        return False
    
    def get_last_triggered_key(self) -> Optional[Any]:
        """
        Get the physical key code for the most recent eligible deletion.
        
        Returns:
            VK code to match on the confirming retry, or None if no eligible deletion.
        """
        return self._last_triggered_key
    
    def clear_history(self):
        """Clear deletion history so stale characters cannot arm another retry."""
        self.key_history.clear()
        self._suffix_length = 0
        self._last_activity_time = None
        self._last_triggered_key = None
        logging.debug("[FRUSTRATION] History cleared")

