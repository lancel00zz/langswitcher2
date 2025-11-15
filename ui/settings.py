"""
Settings Window UI

HTML/WebView-based preferences window with collapsible table sections.
"""

import os
import sys
import subprocess
import json
from Cocoa import (
    NSApp,
    NSWindow,
    NSBackingStoreBuffered,
    NSButton,
    NSRunningApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSObject,
    NSMakeRect,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSURL,
)
import objc
from WebKit import WKWebView

from config import Config
from version import __version__, __app_name__, __author__


class MessageHandler(NSObject):
    """Handles JavaScript messages from WebView"""
    
    def initWithCallback_(self, callback):
        self = objc.super(MessageHandler, self).init()
        if self:
            self.callback = callback
        return self
    
    def userContentController_didReceiveScriptMessage_(self, controller, message):
        """Called when JavaScript sends a message"""
        self.callback(message.body())


class PrefsWindow(NSObject):
    """WebView-based preferences window"""
    
    def initWithConfig_(self, config: Config):
        """Initialize with configuration"""
        self = objc.super(PrefsWindow, self).init()
        if not self:
            return None
        
        self.config = config
        
        # Store original values to detect changes
        self.original_values = {
            'detection.buffer_size': config.detection.buffer_size,
            'detection.switch_threshold': config.detection.switch_threshold,
            'detection.min_word_length': config.detection.min_word_length,
            'detection.model_confidence_threshold': config.detection.model_confidence_threshold,
            'detection.fallback_to_buffer_on_ambiguous': config.detection.fallback_to_buffer_on_ambiguous,
            'frustration.enabled': config.frustration.enabled,
            'frustration.time_window': config.frustration.time_window,
            'frustration.cooldown': config.frustration.cooldown,
        }
        
        # Create window
        WIDTH, HEIGHT = 600, 650
        rect = NSMakeRect(0, 0, WIDTH, HEIGHT)
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )
        self.win.setTitle_("Settings")
        self.win.center()
        
        self.__build_ui()
        
        return self
    
    def __build_ui(self):
        """Build WebView UI"""
        content = self.win.contentView()
        W, H = content.frame().size.width, content.frame().size.height
        
        # Create WebView
        webview_rect = NSMakeRect(0, 60, W, H - 60)
        self.webview = WKWebView.alloc().initWithFrame_(webview_rect)
        
        # Setup message handler for JavaScript communication
        message_handler = MessageHandler.alloc().initWithCallback_(self.handle_save)
        self.webview.configuration().userContentController().addScriptMessageHandler_name_(
            message_handler, "saveHandler"
        )
        
        # Load HTML
        html = self.__generate_html()
        self.webview.loadHTMLString_baseURL_(html, None)
        
        content.addSubview_(self.webview)
        
        # Bottom buttons
        save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 110, 14, 90, 32))
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(1)
        save_btn.setKeyEquivalent_("\r")
        save_btn.setTarget_(self)
        save_btn.setAction_("save:")
        content.addSubview_(save_btn)
        
        cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 210, 14, 90, 32))
        cancel_btn.setTitle_("Cancel")
        cancel_btn.setBezelStyle_(1)
        cancel_btn.setKeyEquivalent_("\x1b")
        cancel_btn.setTarget_(self)
        cancel_btn.setAction_("cancel:")
        content.addSubview_(cancel_btn)
    
    def __generate_html(self):
        """Generate HTML content for settings"""
        return f"""
<!DOCTYPE html>
<html>
<head>
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 13px;
    margin: 10px;
    background: #f5f5f5;
}}

details {{
    margin-bottom: 8px;
}}

summary {{
    font-weight: bold;
    font-size: 12px;
    padding: 5px 8px;
    background: #e0e0e0;
    cursor: pointer;
    border: 1px solid #ccc;
    user-select: none;
}}

summary::-webkit-details-marker {{
    margin-right: 5px;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    background: white;
    margin-top: 0px;
    border: 1px solid #ccc;
}}

td {{
    padding: 1px 8px;
    border: 1px solid #ddd;
    height: 22px;
    line-height: 1.0;
    vertical-align: middle;
}}

td:first-child {{
    width: 45%;
    font-weight: normal;
}}

td:nth-child(2) {{
    width: 55%;
}}

input[type="text"], input[type="number"] {{
    width: 95%;
    padding: 0px 4px;
    border: none;
    background: transparent;
    font-size: 12px;
    color: #000;  /* Black for editable */
    height: 18px;
    line-height: 1.0;
    margin: 0;
}}

input[type="text"]:focus, input[type="number"]:focus {{
    outline: 1px solid #4A90E2;
    background: white;
}}

input[type="checkbox"] {{
    width: 18px;
    height: 18px;
    margin: 0;
    vertical-align: middle;
}}

.readonly {{
    color: #888;  /* Grey for read-only */
    font-style: italic;
    background: #f8f8f8;  /* Subtle background hint */
}}
</style>
</head>
<body>

<details open>
<summary>detection settings</summary>
<table>
<tr>
    <td>Buffer Size</td>
    <td><input type="number" id="detection.buffer_size" value="{self.config.detection.buffer_size}"></td>
</tr>
<tr>
    <td>Switch threshold</td>
    <td><input type="number" id="detection.switch_threshold" value="{self.config.detection.switch_threshold}"></td>
</tr>
<tr>
    <td>Minimum Word Length</td>
    <td><input type="number" id="detection.min_word_length" value="{self.config.detection.min_word_length}"></td>
</tr>
<tr>
    <td>Model Confidence Threshold</td>
    <td><input type="number" step="0.01" id="detection.model_confidence_threshold" value="{self.config.detection.model_confidence_threshold}"></td>
</tr>
<tr>
    <td>Fallback to buffer on ambiguous</td>
    <td><input type="checkbox" id="detection.fallback_to_buffer_on_ambiguous" {'checked' if self.config.detection.fallback_to_buffer_on_ambiguous else ''}></td>
</tr>
</table>
</details>

<details open>
<summary>frustration detection</summary>
<table>
<tr>
    <td>Enable Frustration detection</td>
    <td><input type="checkbox" id="frustration.enabled" {'checked' if self.config.frustration.enabled else ''}></td>
</tr>
<tr>
    <td>Time Window (seconds)</td>
    <td><input type="number" step="0.1" id="frustration.time_window" value="{self.config.frustration.time_window}"></td>
</tr>
<tr>
    <td>Cooldown Period (seconds)</td>
    <td><input type="number" step="0.1" id="frustration.cooldown" value="{self.config.frustration.cooldown}"></td>
</tr>
<tr>
    <td>Eligible keys</td>
    <td class="readonly">/ [ ] ` , .</td>
</tr>
</table>
</details>

<details open>
<summary>application</summary>
<table>
<tr>
    <td>Debug log path</td>
    <td><span class="readonly">{self.config.app.debug_log_path}</span></td>
</tr>
</table>
</details>

<details open>
<summary>languages</summary>
<table>
<tr>
    <td>Detection languages</td>
    <td class="readonly">{', '.join(self.config.language.detection_langs)}</td>
</tr>
<tr>
    <td>EN dictionary</td>
    <td class="readonly">{self.config.language.dict_langs.get('en', 'N/A')}</td>
</tr>
<tr>
    <td>EN layout</td>
    <td class="readonly">{self.config.language.layouts['en'][0]}</td>
</tr>
<tr>
    <td>FR dictionary</td>
    <td class="readonly">{self.config.language.dict_langs.get('fr', 'N/A')}</td>
</tr>
<tr>
    <td>FR layout</td>
    <td class="readonly">{self.config.language.layouts['fr'][0]}</td>
</tr>
</table>
</details>

<details open>
<summary>about</summary>
<table>
<tr>
    <td>Version</td>
    <td class="readonly">{__app_name__} {__version__}</td>
</tr>
<tr>
    <td>Author</td>
    <td class="readonly">{__author__}</td>
</tr>
</table>
</details>

<script>
function getFormValues() {{
    const getValue = (id) => {{
        const el = document.getElementById(id);
        if (!el) {{
            console.log('Element not found:', id);
            return null;
        }}
        if (el.type === 'checkbox') {{
            console.log('Checkbox', id, '=', el.checked);
            return el.checked;
        }}
        console.log('Field', id, '=', el.value);
        return el.value;
    }};
    
    return {{
        'detection.buffer_size': getValue('detection.buffer_size'),
        'detection.switch_threshold': getValue('detection.switch_threshold'),
        'detection.min_word_length': getValue('detection.min_word_length'),
        'detection.model_confidence_threshold': getValue('detection.model_confidence_threshold'),
        'detection.fallback_to_buffer_on_ambiguous': getValue('detection.fallback_to_buffer_on_ambiguous'),
        'frustration.enabled': getValue('frustration.enabled'),
        'frustration.time_window': getValue('frustration.time_window'),
        'frustration.cooldown': getValue('frustration.cooldown'),
    }};
}}
</script>

</body>
</html>
"""
    
    def handle_save(self, data):
        """Handle save message from JavaScript"""
        # This is called by JavaScript, not used currently
        pass
    
    def save_(self, _):
        """Save settings"""
        # Get values from HTML form via JavaScript
        script = "JSON.stringify(getFormValues())"
        self.webview.evaluateJavaScript_completionHandler_(script, self.process_save)
    
    def process_save(self, result, error):
        """Process the form values from JavaScript"""
        if error:
            self.win.orderOut_(None)
            subprocess.Popen(
                ["osascript", "-e", f'tell application "System Events" to display dialog "Error reading form" buttons {{"OK"}}'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        
        try:
            # Parse JSON result
            values = json.loads(result)
            
            import logging
            logging.info(f"[SETTINGS] Received values: {values}")
            
            # Helper to convert boolean values properly
            def to_bool(val):
                if val is None:
                    return False
                if isinstance(val, bool):
                    return val
                if isinstance(val, str):
                    return val.lower() in ('true', '1', 'yes')
                return bool(val)
            
            # Check if any values changed
            changed = False
            for key in self.original_values:
                new_val = values.get(key)
                old_val = self.original_values[key]
                
                # Convert types for comparison
                if isinstance(old_val, bool):
                    new_val = to_bool(new_val)
                elif isinstance(old_val, int):
                    new_val = int(new_val)
                elif isinstance(old_val, float):
                    new_val = float(new_val)
                
                if new_val != old_val:
                    logging.info(f"[SETTINGS] Changed: {key} = {old_val} → {new_val}")
                    changed = True
                    break
            
            # Only update if changes detected
            if not changed:
                logging.info("[SETTINGS] No changes detected, closing window")
                self.win.orderOut_(None)
                return
            
            # Update config IN MEMORY ONLY (no file save, no restart)
            self.config.detection.buffer_size = int(values['detection.buffer_size'])
            self.config.detection.switch_threshold = int(values['detection.switch_threshold'])
            self.config.detection.min_word_length = int(values['detection.min_word_length'])
            self.config.detection.model_confidence_threshold = float(values['detection.model_confidence_threshold'])
            self.config.detection.fallback_to_buffer_on_ambiguous = to_bool(values['detection.fallback_to_buffer_on_ambiguous'])
            
            self.config.frustration.enabled = to_bool(values['frustration.enabled'])
            self.config.frustration.time_window = float(values['frustration.time_window'])
            self.config.frustration.cooldown = float(values['frustration.cooldown'])
            
            # Validate
            self.config.validate()
            
            # Log success and close (changes take effect immediately, no restart)
            logging.info("[SETTINGS] Config updated in memory - changes active immediately")
            logging.info(f"[SETTINGS] Frustration detection: {self.config.frustration.enabled}")
            self.win.orderOut_(None)
            
        except Exception as e:
            self.win.orderOut_(None)
            subprocess.Popen(
                ["osascript", "-e", f'tell application "System Events" to display dialog "Error: {e}" buttons {{"OK"}}'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    
    def cancel_(self, _):
        """Close without saving"""
        self.win.orderOut_(None)
    
    def show(self):
        """Show window (non-modal)"""
        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps
        )
        self.win.makeKeyAndOrderFront_(None)
