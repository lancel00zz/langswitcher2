#!/usr/bin/env python3
"""
VK Code Discovery Script

Use this script to discover the VK (Virtual Key) codes for keys that differ
between US and French keyboard layouts.

Run this script and press keys to see their VK codes.
Then add the VK codes to FRUSTRATION_ELIGIBLE_KEYS in detectors/frustration.py
"""

from pynput import keyboard

print("=" * 70)
print("VK CODE DISCOVERY FOR FRUSTRATION DETECTION")
print("=" * 70)
print()
print("Press keys to discover their VK codes.")
print("Focus on punctuation keys that differ between US and French:")
print("  /  [  ]  `  ,  .  ;  '  and their Shift versions")
print()
print("Press Ctrl+C to exit.")
print("-" * 70)
print()

discovered_vks = set()

def on_press(key):
    """Handle key press events"""
    vk = getattr(key, 'vk', None)
    
    if vk is None:
        # Special key without VK code
        try:
            name = str(key).replace('Key.', '')
            print(f"Special key: {name:15} (no VK code)")
        except:
            pass
        return
    
    try:
        # Regular character key
        char = key.char
        if char:
            # Track unique VKs
            if vk not in discovered_vks:
                discovered_vks.add(vk)
                print(f"Character: '{char}'  →  VK Code: {vk:3}  ⭐ NEW!")
            else:
                print(f"Character: '{char}'  →  VK Code: {vk:3}")
    except AttributeError:
        # Special key (backspace, shift, etc.)
        name = str(key).replace('Key.', '')
        print(f"Special: {name:15}  →  VK Code: {vk:3}")

def on_release(key):
    """Handle key release - stop on Ctrl+C"""
    # Stop listener on Ctrl+C
    if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
        pass  # Allow Ctrl through
    
try:
    print("Listening for keypresses...\n")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
except KeyboardInterrupt:
    print("\n" + "=" * 70)
    print("DISCOVERED VK CODES:")
    print("=" * 70)
    print(f"Unique VK codes found: {sorted(discovered_vks)}")
    print()
    print("Add these to FRUSTRATION_ELIGIBLE_KEYS in detectors/frustration.py")
    print("=" * 70)

