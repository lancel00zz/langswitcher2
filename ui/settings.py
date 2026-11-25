"""
Settings Window UI

HTML/WebView-based preferences window with collapsible table sections.
"""

import os
import sys
import subprocess
import json
import logging
from Cocoa import (
    NSAlert,
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
from version import __version__, __build__, __app_name__, __author__


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
        
        self.on_save = None
        self.on_flag_preview = None
        self._flag_preview_active = False
        self._preview_session = 0
        self._window_open = False
        self._saving = False
        self._webview_loaded = False
        self._pending_flag_enabled = None

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
        self.win.setReleasedWhenClosed_(False)
        self.win.setDelegate_(self)
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
        self.webview.setNavigationDelegate_(self)
        
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
        positions = (
            ("center", "Center"), ("top_left", "Top left"),
            ("top_right", "Top right"), ("bottom_left", "Bottom left"),
            ("bottom_right", "Bottom right"),
        )
        position_options = "\n".join(
            f'<option value="{value}"{" selected" if self.config.flag_overlay.position == value else ""}>{label}</option>'
            for value, label in positions
        )
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

.slider-control {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 0;
}}

.slider-control input[type="range"] {{
    flex: 1;
    min-width: 0;
    width: 100%;
}}

.slider-control output {{
    min-width: 42px;
    text-align: right;
    font-variant-numeric: tabular-nums;
}}

select {{
    width: 95%;
    font: inherit;
    margin: 3px 0;
}}

.flag-preview-link {{
    margin-left: 10px;
    font-size: 12px;
    color: #1769aa;
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
<summary>Keyboard switch flag</summary>
<table>
<tr>
    <td><label for="flag_overlay.enabled">Show flag on keyboard switch</label></td>
    <td><input type="checkbox" id="flag_overlay.enabled" {'checked' if self.config.flag_overlay.enabled else ''}>
        <a href="#" id="flag-preview-link" class="flag-preview-link" onclick="toggleFlagPreview(); return false;">Display flag</a></td>
</tr>
<tr>
    <td><label for="flag_overlay.size_percent">Flag size</label></td>
    <td><div class="slider-control">
        <input type="range" id="flag_overlay.size_percent" min="50" max="250" step="5" value="{self.config.flag_overlay.size_percent}"
            oninput="document.getElementById('flag-size-value').textContent = this.value + '%'; updateFlagPreview();">
        <output id="flag-size-value" for="flag_overlay.size_percent">{self.config.flag_overlay.size_percent}%</output>
    </div></td>
</tr>
<tr>
    <td><label for="flag_overlay.position">Position</label></td>
    <td><select id="flag_overlay.position" onchange="updateFlagPreview();">
        {position_options}
    </select></td>
</tr>
<tr>
    <td><label for="flag_overlay.opacity_percent">Opacity</label></td>
    <td><div class="slider-control">
        <input type="range" id="flag_overlay.opacity_percent" min="20" max="100" step="5" value="{self.config.flag_overlay.opacity_percent}"
            oninput="document.getElementById('flag-opacity-value').textContent = this.value + '%'; updateFlagPreview();">
        <output id="flag-opacity-value" for="flag_overlay.opacity_percent">{self.config.flag_overlay.opacity_percent}%</output>
    </div></td>
</tr>
</table>
</details>

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
<p>To change <code>/</code> to <code>é</code>, delete it with Backspace, then press the same physical key within 2.5 seconds. The retry switches the layout and shows the flag. For <code>/c</code>, delete both characters before retrying. A space, Enter, or 2.5 seconds of inactivity cancels the correction.</p>
<table>
<tr>
    <td>Enable Frustration detection</td>
    <td><input type="checkbox" id="frustration.enabled" {'checked' if self.config.frustration.enabled else ''}></td>
</tr>
<tr>
    <td>Eligible physical keys (US labels)</td>
    <td class="readonly">/ . [ ] ` , ; ' &#92; 6</td>
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
    <td class="readonly">{__version__}</td>
</tr>
<tr>
    <td>Build</td>
    <td class="readonly">{__build__}</td>
</tr>
<tr>
    <td>Author</td>
    <td class="readonly">{__author__}</td>
</tr>
</table>
</details>

<script>
let flagPreviewActive = false;
let flagPreviewSession = 0;

function setFlagPreviewState(active, session) {{
    flagPreviewActive = active;
    flagPreviewSession = session;
    document.getElementById('flag-preview-link').textContent = active ? 'Hide flag' : 'Display flag';
}}

function flagPreviewValues() {{
    return {{
        'flag_overlay.enabled': document.getElementById('flag_overlay.enabled').checked,
        'flag_overlay.size_percent': document.getElementById('flag_overlay.size_percent').value,
        'flag_overlay.position': document.getElementById('flag_overlay.position').value,
        'flag_overlay.opacity_percent': document.getElementById('flag_overlay.opacity_percent').value,
    }};
}}

function toggleFlagPreview() {{
    setFlagPreviewState(!flagPreviewActive, flagPreviewSession);
    window.webkit.messageHandlers.saveHandler.postMessage({{
        action: 'flag_preview_toggle', active: flagPreviewActive,
        session: flagPreviewSession, values: flagPreviewValues(),
    }});
}}

function updateFlagPreview() {{
    if (!flagPreviewActive) return;
    window.webkit.messageHandlers.saveHandler.postMessage({{
        action: 'flag_preview_update', session: flagPreviewSession, values: flagPreviewValues(),
    }});
}}

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
        'flag_overlay.enabled': getValue('flag_overlay.enabled'),
        'flag_overlay.size_percent': getValue('flag_overlay.size_percent'),
        'flag_overlay.position': getValue('flag_overlay.position'),
        'flag_overlay.opacity_percent': getValue('flag_overlay.opacity_percent'),
        'detection.buffer_size': getValue('detection.buffer_size'),
        'detection.switch_threshold': getValue('detection.switch_threshold'),
        'detection.min_word_length': getValue('detection.min_word_length'),
        'detection.model_confidence_threshold': getValue('detection.model_confidence_threshold'),
        'detection.fallback_to_buffer_on_ambiguous': getValue('detection.fallback_to_buffer_on_ambiguous'),
        'frustration.enabled': getValue('frustration.enabled'),
    }};
}}
</script>

</body>
</html>
"""

    @objc.python_method
    def set_flag_enabled(self, enabled):
        """Mirror a menu toggle without replacing unsaved form values."""
        enabled = bool(enabled)
        self.config.flag_overlay.enabled = enabled
        self._pending_flag_enabled = enabled
        if self._webview_loaded:
            self._apply_pending_flag_enabled()

    @objc.python_method
    def _apply_pending_flag_enabled(self):
        enabled = self._pending_flag_enabled
        if enabled is None:
            return
        script = (
            "document.getElementById('flag_overlay.enabled').checked = "
            + json.dumps(enabled)
        )
        self.webview.evaluateJavaScript_completionHandler_(script, None)
        self._pending_flag_enabled = None

    def webView_didFinishNavigation_(self, _webview, _navigation):
        self._webview_loaded = True
        self._apply_pending_flag_enabled()
        self._sync_flag_preview_link()

    @objc.python_method
    def is_flag_preview_active(self):
        return self._flag_preview_active and self._window_open and not self._saving

    @objc.python_method
    def _sync_flag_preview_link(self):
        if self._webview_loaded:
            script = f"setFlagPreviewState({json.dumps(self._flag_preview_active)}, {self._preview_session})"
            try:
                self.webview.evaluateJavaScript_completionHandler_(script, None)
            except Exception:
                # Closing a stale WebView must not prevent preview cleanup.
                logging.exception("Could not refresh the flag preview link")

    @objc.python_method
    def _hide_flag_preview(self):
        was_active = self._flag_preview_active
        self._flag_preview_active = False
        if was_active and self.on_flag_preview is not None:
            try:
                self.on_flag_preview(None)
            except Exception:
                logging.exception("Could not close the flag preview")
        self._sync_flag_preview_link()

    @objc.python_method
    def stop_flag_preview(self):
        """Stop preview and invalidate bridge messages queued before this stop."""
        self._preview_session += 1
        self._hide_flag_preview()

    @objc.python_method
    def handle_save(self, data):
        """Handle live preview messages without changing or saving config."""
        if not self._window_open or self._saving:
            return
        try:
            data = dict(data)
            if data.get('session', self._preview_session) != self._preview_session:
                return
            action = data.get('action')
            if action == 'flag_preview_toggle':
                active = data.get('active', not self._flag_preview_active)
                if not active:
                    self._hide_flag_preview()
                    return
            elif action == 'flag_preview_update':
                if not self._flag_preview_active:
                    return
            else:
                return
            if self.on_flag_preview is None:
                self._sync_flag_preview_link()
                return
            values = dict(data.get('values') or {})
            flag_values = {
                key: values[key] for key in (
                    'flag_overlay.enabled', 'flag_overlay.size_percent',
                    'flag_overlay.position', 'flag_overlay.opacity_percent',
                )
            }
            # The app's ownership guard checks this before displaying a preview.
            self._flag_preview_active = True
            self.on_flag_preview(flag_values)
        except Exception:
            logging.exception("Could not update the flag preview")
            self.stop_flag_preview()
    
    def save_(self, _):
        """Save settings"""
        if not self._window_open or self._saving:
            return
        self._saving = True
        self.stop_flag_preview()
        # Get values from HTML form via JavaScript
        script = "JSON.stringify(getFormValues())"
        try:
            self.webview.evaluateJavaScript_completionHandler_(script, self.process_save)
        except Exception as exc:
            self.process_save(None, exc)
    
    def process_save(self, result, error):
        """Process the form values from JavaScript"""
        if not self._window_open:
            self._saving = False
            return
        try:
            if error:
                raise ValueError("Could not read the settings form")
            values = json.loads(result)
            if self.on_save is None:
                raise RuntimeError("Settings callback is not available")
            self.on_save(values)
            self._window_open = False
            self.win.orderOut_(None)
        except Exception as exc:
            # Keep the form open and retain the previous live settings on failure.
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Settings could not be saved")
            alert.setInformativeText_(str(exc))
            alert.runModal()
        finally:
            self._saving = False

    def cancel_(self, _):
        """Close without saving"""
        self._window_open = False
        self.stop_flag_preview()
        self.win.orderOut_(None)

    def windowWillClose_(self, _notification):
        self._window_open = False
        self.stop_flag_preview()
    
    def show(self):
        """Show window (non-modal)"""
        self._window_open = True
        self._saving = False
        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps
        )
        self.win.makeKeyAndOrderFront_(None)
