"""
Frustration Pattern Detection Module

Detects user frustration patterns like: Key → Backspace → Same Key
and triggers automatic keyboard layout switching with keystroke replay.
"""

import time
import logging
from typing import Optional, Dict, Any, List
from pynput.keyboard import Controller, KeyCode


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
        # Add more as discovered using vk_discovery.py
    }
    
    def __init__(
        self,
        time_window: float = 2.0,
        cooldown: float = 3.0,
        enable_replay: bool = True
    ):
        """
        Initialize frustration detector
        
        Args:
            time_window: Maximum time window for pattern detection (seconds)
            cooldown: Minimum time between consecutive switches (seconds)
            enable_replay: Whether to automatically replay keystrokes
        """
        self.time_window = time_window
        self.cooldown = cooldown
        self.enable_replay = enable_replay
        
        self.key_history: List[Dict[str, Any]] = []
        self.last_switch_time = 0.0
        self.keyboard_controller = Controller()
    
    def track_key_event(self, vk_code: Any, event_type: str) -> bool:
        """
        Track a key event and check for frustration pattern
        
        Only tracks frustration-eligible keys (special punctuation that differs
        between US and French layouts). Regular letters are ignored.
        
        Args:
            vk_code: Virtual key code or key identifier
            event_type: Either 'key' for regular key press or 'backspace'
            
        Returns:
            True if frustration pattern detected on eligible key, False otherwise
        """
        # FILTER: Only track frustration-eligible keys
        # Letters like 'a', 's', etc. are ignored - they're the same in both layouts
        if event_type == 'key' and vk_code not in self.FRUSTRATION_ELIGIBLE_KEYS:
            # This is a letter or safe key - don't track for frustration
            logging.debug(f"[FRUSTRATION] Ignoring non-eligible key VK={vk_code}")
            return False
        
        # Log tracking for eligible keys
        if event_type == 'key':
            logging.info(f"[FRUSTRATION] Tracking eligible key VK={vk_code}")
        else:
            logging.info(f"[FRUSTRATION] Tracking backspace")
        
        now = time.time()
        
        # Clean old events
        self.key_history = [
            e for e in self.key_history
            if now - e['timestamp'] < self.time_window
        ]
        
        # Add new event
        event = {
            'timestamp': now,
            'vk_code': vk_code,
            'type': event_type
        }
        self.key_history.append(event)
        
        # Check for pattern
        return self._check_pattern()
    
    def _check_pattern(self) -> bool:
        """
        Check if frustration pattern exists in recent history
        
        Pattern: Eligible Key → Backspace (within time window)
        
        When user types a special punctuation key (like [, /, etc.) and immediately
        backspaces, we assume they got the wrong character due to wrong layout.
        We switch layouts immediately so they can retype correctly.
        
        Returns:
            True if pattern detected and not in cooldown
        """
        if len(self.key_history) < 2:
            return False
        
        # Check last 2 events: Eligible Key → Backspace
        recent = self.key_history[-2:]
        
        pattern_match = (
            recent[0]['type'] == 'key' and
            recent[1]['type'] == 'backspace'
        )
        
        if not pattern_match:
            return False
        
        vk_code = recent[0]['vk_code']
        logging.info(
            f"[FRUSTRATION] ✨ PATTERN DETECTED! "
            f"VK {vk_code} → Backspace"
        )
        
        # Check cooldown
        now = time.time()
        time_since_last = now - self.last_switch_time
        
        if time_since_last < self.cooldown:
            logging.info(
                f"[FRUSTRATION] ⏸️  Cooldown active "
                f"({time_since_last:.1f}s ago) - ignoring"
            )
            return False
        
        logging.info(f"[FRUSTRATION] 🚀 TRIGGERING LAYOUT SWITCH!")
        self.last_switch_time = now
        return True
    
    def get_last_triggered_key(self) -> Optional[Any]:
        """
        Get the VK code of the key that triggered the last frustration pattern
        
        Returns:
            VK code or None if no recent pattern
        """
        if len(self.key_history) >= 2:
            recent = self.key_history[-2:]
            if (recent[0]['type'] == 'key' and
                recent[1]['type'] == 'backspace'):
                return recent[0]['vk_code']
        return None
    
    def clear_history(self):
        """Clear key history (useful after a switch to prevent double-triggering)"""
        self.key_history.clear()
        logging.debug("[FRUSTRATION] History cleared")

