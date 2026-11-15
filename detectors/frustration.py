"""
Frustration Pattern Detection Module

Detects an immediate correction gesture: layout-specific key -> Backspace.
The caller switches the layout; this detector never injects keystrokes.
"""

import time
import logging
from typing import Optional, Dict, Any, List


class FrustrationDetector:
    """Detects frustration patterns in typing behavior"""
    
    # VK codes for keys that produce DIFFERENT characters in US vs French layouts
    # Only these keys trigger automatic layout switching on frustration pattern
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
        cooldown: float = 0.0
    ):
        """
        Initialize frustration detector
        
        Args:
            time_window: Legacy configuration value; no longer gates gestures.
            cooldown: Legacy configuration value; no longer gates gestures.
        """
        self.time_window = time_window
        self.cooldown = cooldown
        
        self.key_history: List[Dict[str, Any]] = []
        self.last_switch_time: Optional[float] = None
        self._last_triggered_key: Optional[Any] = None
    
    def track_key_event(self, vk_code: Any, event_type: str) -> bool:
        """
        Track a key event and check for frustration pattern
        
        Only an eligible key immediately followed by Backspace can trigger.
        Other input cancels the gesture instead of being hidden from history.
        
        Args:
            vk_code: Virtual key code or key identifier
            event_type: Either 'key' for regular key press or 'backspace'
            
        Returns:
            True if frustration pattern detected on eligible key, False otherwise
        """
        # Timing is diagnostic only. Adjacency decides whether this Backspace
        # corrects an eligible key, regardless of typing speed or prior switches.
        now = time.monotonic()
        event = {
            'timestamp': now,
            'vk_code': vk_code,
            'type': event_type
        }
        if event_type == 'key':
            if vk_code not in self.FRUSTRATION_ELIGIBLE_KEYS:
                self.clear_history()
                return False

            # Remember only the immediately preceding physical key.
            self.key_history = [event]
        elif event_type == 'backspace':
            if len(self.key_history) == 1:
                self.key_history.append(event)
                return self._check_pattern(now)
            else:
                # Holding Backspace or deleting several characters is editing,
                # not confirmation of a wrong keyboard layout.
                self.clear_history()
        else:
            self.clear_history()
        return False
    
    def _check_pattern(self, now: Optional[float] = None) -> bool:
        """
        Check if frustration pattern exists in recent history
        
        Pattern: Eligible Key -> Backspace, with no intervening physical input.
        
        Returns:
            True if the immediately preceding key is eligible
        """
        if len(self.key_history) != 2:
            return False
        
        recent = self.key_history
        
        pattern_match = (
            recent[0]['type'] == 'key' and
            recent[1]['type'] == 'backspace'
        )
        
        if not pattern_match:
            return False
        
        vk_code = recent[0]['vk_code']
        now = time.monotonic() if now is None else now
        # Consume the gesture so an extra or held Backspace cannot toggle again.
        # Every new key -> Backspace pair is eligible, even at the same timestamp.
        self.clear_history()
        logging.info(f"[FRUSTRATION] Immediate correction gesture for VK={vk_code}")
        self.last_switch_time = now
        self._last_triggered_key = vk_code
        return True
    
    def get_last_triggered_key(self) -> Optional[Any]:
        """
        Get the VK code of the key that triggered the last frustration pattern
        
        Returns:
            VK code or None if no recent pattern
        """
        return self._last_triggered_key
    
    def clear_history(self):
        """Clear key history (useful after a switch to prevent double-triggering)"""
        self.key_history.clear()
        self._last_triggered_key = None
        logging.debug("[FRUSTRATION] History cleared")

