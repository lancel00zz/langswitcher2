"""
Settings Window UI

Preferences window for configuring LangSwitcher settings.
"""

import os
import sys
import subprocess
from Cocoa import (
    NSApp,
    NSApplication,
    NSWindow,
    NSBackingStoreBuffered,
    NSTextField,
    NSButton,
    NSSwitch,
    NSRunningApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSObject,
    NSMakeRect,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
)
import objc

from config import Config


class PrefsWindow(NSObject):
    """Preferences window for LangSwitcher"""
    
    def initWithConfig_(self, config: Config):
        """
        Initialize with configuration object
        
        Args:
            config: Configuration instance
        """
        self = objc.super(PrefsWindow, self).init()
        if not self:
            return None
        
        self.config = config
        
        WIDTH, HEIGHT = 360, 500
        rect = NSMakeRect(0, 0, WIDTH, HEIGHT)
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )
        self.win.setTitle_("Lang Switcher Preferences")
        self.win.center()
        
        cf = self.win.contentView().frame()
        W, H = cf.size.width, cf.size.height
        
        LABEL_X = W * 0.05
        FIELD_X = W * 0.60
        CW, CH = W * 0.35, 24
        SPY = 50
        y = H - CH - 30
        
        def label(txt, yy):
            l = NSTextField.alloc().initWithFrame_(NSMakeRect(LABEL_X, yy, CW + 60, CH))
            l.setStringValue_(txt)
            l.setBezeled_(False)
            l.setDrawsBackground_(False)
            l.setEditable_(False)
            self.win.contentView().addSubview_(l)
        
        def textf(val, yy):
            t = NSTextField.alloc().initWithFrame_(NSMakeRect(FIELD_X, yy, CW, CH))
            t.setStringValue_(str(val))
            self.win.contentView().addSubview_(t)
            return t
        
        def sw(val, yy):
            s = NSSwitch.alloc().initWithFrame_(NSMakeRect(FIELD_X, yy, 40, CH))
            s.setState_(1 if val else 0)
            self.win.contentView().addSubview_(s)
            return s
        
        # Create fields
        self.buf_tf = textf(config.detection.buffer_size, y)
        label("Buffer size:", y)
        y -= SPY
        
        self.th_tf = textf(config.detection.switch_threshold, y)
        label("Switch threshold:", y)
        y -= SPY
        
        self.min_tf = textf(config.detection.min_word_length, y)
        label("Min word length:", y)
        y -= SPY
        
        self.conf_tf = textf(config.detection.model_confidence_threshold, y)
        label("Model confidence:", y)
        y -= SPY
        
        self.fb_sw = sw(config.detection.fallback_to_buffer_on_ambiguous, y)
        label("Fallback to buffer:", y)
        y -= SPY
        
        self.db_sw = sw(config.app.display_debug_console, y)
        label("Display debug console:", y)
        y -= SPY
        
        # Info labels
        langs = ", ".join(config.language.detection_langs)
        dicts_s = ", ".join(
            config.language.dict_langs[l]
            for l in config.language.detection_langs
        )
        label(f"Detection languages: {langs}", y)
        y -= CH + 10
        label(f"Dictionaries: {dicts_s}", y)
        y -= SPY
        
        # Save button
        bw, bh = 100, 32
        bx = (W - bw) / 2
        by = y - 10
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(bx, by, bw, bh))
        btn.setTitle_("Save")
        btn.setBezelStyle_(1)
        btn.setTarget_(self)
        btn.setAction_("savePrefs:")
        self.win.contentView().addSubview_(btn)
        
        return self
    
    def savePrefs_(self, _):
        """Save preferences and restart application"""
        try:
            # Update configuration
            self.config.detection.buffer_size = int(self.buf_tf.stringValue())
            self.config.detection.switch_threshold = int(self.th_tf.stringValue())
            self.config.detection.min_word_length = int(self.min_tf.stringValue())
            self.config.detection.model_confidence_threshold = float(self.conf_tf.stringValue())
            self.config.detection.fallback_to_buffer_on_ambiguous = bool(self.fb_sw.state())
            self.config.app.display_debug_console = bool(self.db_sw.state())
            
            # Validate
            self.config.validate()
            
            # Save to file
            self.config.save(detection_only=True)
            
            # Close window
            NSApp.stop_(None)
            
            # Notify and restart
            notify = (
                'tell application "System Events" to display dialog '
                '"Settings saved; restarting..." buttons {"OK"}'
            )
            subprocess.Popen(
                ["osascript", "-e", notify],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            
            # Restart app
            os.execv(sys.executable, [sys.executable] + sys.argv)
            
        except ValueError as e:
            # Validation error
            err = (
                f'tell application "System Events" to display dialog '
                f'"Invalid value: {e}" buttons {{"OK"}}'
            )
            subprocess.Popen(
                ["osascript", "-e", err],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            # Other error
            err = (
                f'tell application "System Events" to display dialog '
                f'"Error: {e}" buttons {{"OK"}}'
            )
            subprocess.Popen(
                ["osascript", "-e", err],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    
    def run(self):
        """Show window and run modal"""
        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps
        )
        self.win.makeKeyAndOrderFront_(None)
        NSApp.run()

