"""Native guidance for repairing keyboard access without changing permissions."""

import logging
import sys

import objc
from Cocoa import (
    NSApplicationActivateIgnoringOtherApps,
    NSBackingStoreBuffered,
    NSBundle,
    NSButton,
    NSColor,
    NSFont,
    NSLineBreakByWordWrapping,
    NSMakeRect,
    NSObject,
    NSProcessInfo,
    NSRunningApplication,
    NSTextField,
    NSURL,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)


logger = logging.getLogger(__name__)

SETTINGS_LINKS = {
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
}


def control_permission_label(major_version=None):
    """Use the permission name displayed by this version of macOS."""
    if major_version is None:
        version = NSProcessInfo.processInfo().operatingSystemVersion()
        # PyObjC may expose NSOperatingSystemVersion as a named struct or as a
        # plain tuple, depending on the bundled bridge/runtime combination.
        major_version = getattr(version, "majorVersion", None)
        if major_version is None:
            major_version = version[0]
    return "Device Control and Data Access" if major_version >= 27 else "Accessibility"


def running_application_path():
    """Return the actual app bundle, without misidentifying a source-run Python."""
    if not getattr(sys, "frozen", False):
        return None
    path = str(NSBundle.mainBundle().bundlePath() or "")
    return path if path.lower().endswith(".app") else None


def permission_status(value):
    if value is True:
        return "Allowed"
    if value is False:
        return "Not allowed"
    return "Not confirmed"


def window_copy(report, app_path, control_label):
    """Build user guidance independently of Cocoa controls and diagnostic masks."""
    ready = bool(report.keyboard_access)
    if app_path:
        location = app_path
        recovery = (
            f"1. Open Input Monitoring and {control_label} using the buttons above.\n\n"
            "2. In each list, select LangSwitcher and click the minus (−) button to remove its entry. "
            "If no entry is listed, continue to the next step.\n\n"
            "3. In each list, click the plus (+) button, add the exact running app shown above, "
            "and turn its switch on.\n\n"
            "4. Quit LangSwitcher from its menu bar menu, then reopen that same app."
        )
    else:
        location = "Source mode (Python): no packaged LangSwitcher.app is running."
        recovery = (
            "1. Quit this source or test copy of LangSwitcher.\n\n"
            "2. Open the built LangSwitcher.app you intend to use, then open Keyboard Access from its menu.\n\n"
            f"3. In Input Monitoring and {control_label}, remove any old LangSwitcher entry, "
            "add the exact app shown by that copy, and turn it on.\n\n"
            "4. Quit and reopen that app. Permission granted to Terminal or Python may not apply to the app."
        )
    explanations = {
        "tap_missing": "LangSwitcher could not connect to keyboard input.",
        "keyboard_events_filtered": "macOS connected LangSwitcher without allowing keyboard input.",
        "tap_disabled": "macOS paused LangSwitcher's keyboard connection.",
        "verification_unavailable": "LangSwitcher could not verify its keyboard connection.",
        "check_failed": "LangSwitcher could not finish checking keyboard access.",
    }
    problem = explanations.get(
        report.reason, "LangSwitcher could not confirm keyboard access."
    )
    summary = problem + " Automatic switching is unavailable. Use the steps below to reconnect it."
    if (report.reason == "keyboard_events_filtered"
            and report.accessibility is True and report.input_monitoring is True):
        summary = (
            "macOS may still be using an approval from an older app version, even when both switches are on. "
            "Automatic switching is unavailable. Remove and re-add this copy using the steps below."
        )
    steps_title = "Reconnect keyboard access"
    if report.reason == "check_failed":
        summary = "LangSwitcher could not finish checking keyboard access. Quit and reopen it, then check again."
        steps_title = "Try the check again"
        recovery = (
            "1. Quit LangSwitcher from its menu bar menu, then reopen the same copy.\n\n"
            "2. If the check still fails, choose Open Debug Console from the menu to see why it could not finish.\n\n"
            "3. Keep your existing permission settings. An incomplete check does not mean permissions need to be reset."
        )
    input_status = permission_status(report.input_monitoring)
    if ready and report.input_monitoring is False:
        # Accessibility can cover listening without a separate grant. The
        # effective event-tap check, rather than this preflight, decides readiness.
        input_status = "Not granted separately; keyboard access is working"
    return {
        "title": "Keyboard access is ready" if ready else "Keyboard access needs attention",
        "summary": (
            "LangSwitcher can receive keyboard input. No permission setup is needed."
            if ready else
            summary
        ),
        "statuses": (
            f"Input Monitoring: {input_status}\n"
            f"{control_label}: {permission_status(report.accessibility)}"
        ),
        "location": location,
        "steps_title": "You are ready to type" if ready else steps_title,
        "steps": (
            "Close this window and use LangSwitcher normally.\n\n"
            "If an update stops responding to typing, reopen Keyboard Access from the menu. "
            "Only remove and re-add permissions when access needs attention."
            if ready else recovery
        ),
        "footer": "Check Again checks access without resetting your macOS permissions.",
    }


def open_permission_settings(pane):
    """Open the requested system pane; never grant or reset a permission."""
    url = NSURL.URLWithString_(SETTINGS_LINKS[pane])
    return bool(NSWorkspace.sharedWorkspace().openURL_(url))


class KeyboardAccessWindow(NSObject):
    """Show status and recovery instructions while leaving consent to the user."""

    def initWithReport_(self, report):
        self = objc.super(KeyboardAccessWindow, self).init()
        if not self:
            return None
        self.on_retry = None
        self.report = report
        self._control_label = control_permission_label()
        self._app_path = running_application_path()
        width, height = 720, 730
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self.win.setTitle_("LangSwitcher — Keyboard Access")
        self.win.setReleasedWhenClosed_(False)
        self.win.center()
        content = self.win.contentView()
        self._title_field = self._text(content, (24, 676, 672, 30), 21, bold=True)
        self._summary_field = self._text(content, (24, 620, 672, 48), 13)
        self._statuses_field = self._text(content, (24, 558, 672, 52), 13)
        self._button(content, "Open Input Monitoring", (24, 510, 246, 34), "openInputMonitoring:")
        self._button(content, f"Open {self._control_label}", (282, 510, 414, 34), "openControlSettings:")
        self._text(content, (24, 470, 672, 22), 13, "Current copy", bold=True)
        self._location_field = self._text(content, (24, 420, 672, 46), 12, selectable=True)
        self._location_field.setFont_(NSFont.userFixedPitchFontOfSize_(12))
        self._steps_title_field = self._text(content, (24, 380, 672, 26), 15, bold=True)
        self._steps_field = self._text(content, (24, 150, 672, 220), 13)
        self._footer_field = self._text(content, (24, 84, 672, 56), 12)
        self._footer_field.setTextColor_(NSColor.secondaryLabelColor())
        self._retry_button = self._button(content, "Check Again", (428, 28, 148, 34), "retry:")
        self._retry_button.setKeyEquivalent_("\r")
        close_button = self._button(content, "Close", (588, 28, 108, 34), "close:")
        close_button.setKeyEquivalent_("\x1b")
        self.set_report(report)
        return self

    @objc.python_method
    def _text(self, content, frame, size, value="", bold=False, selectable=False):
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
        field.setEditable_(False)
        field.setSelectable_(selectable)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setUsesSingleLineMode_(False)
        field.setMaximumNumberOfLines_(0)
        field.cell().setWraps_(True)
        field.cell().setScrollable_(False)
        field.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
        field.setFont_(font)
        field.setStringValue_(value)
        content.addSubview_(field)
        return field

    @objc.python_method
    def _button(self, content, title, frame, action):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(*frame))
        button.setTitle_(title)
        button.setBezelStyle_(1)
        button.setTarget_(self)
        button.setAction_(action)
        content.addSubview_(button)
        return button

    @objc.python_method
    def set_report(self, report):
        self.report = report
        copy = window_copy(report, self._app_path, self._control_label)
        for key, field in (
            ("title", self._title_field),
            ("summary", self._summary_field),
            ("statuses", self._statuses_field),
            ("location", self._location_field),
            ("steps_title", self._steps_title_field),
            ("steps", self._steps_field),
            ("footer", self._footer_field),
        ):
            field.setStringValue_(copy[key])
        color = NSColor.systemGreenColor() if report.keyboard_access else NSColor.labelColor()
        self._title_field.setTextColor_(color)

    def openInputMonitoring_(self, _sender):
        self._open_settings("input_monitoring")

    def openControlSettings_(self, _sender):
        self._open_settings("accessibility")

    @objc.python_method
    def _open_settings(self, pane):
        try:
            opened = open_permission_settings(pane)
        except Exception:
            logger.exception("Could not open the keyboard permission settings")
            opened = False
        if not opened:
            self._footer_field.setStringValue_(
                "System Settings could not be opened. Open Privacy & Security from the Apple menu."
            )

    def retry_(self, _sender):
        self._retry_button.setEnabled_(False)
        try:
            if self.on_retry is None:
                raise RuntimeError("Keyboard access retry callback is not available")
            self.set_report(self.on_retry())
        except Exception:
            logger.exception("Could not refresh keyboard access status")
            self._footer_field.setStringValue_(
                "The check could not finish. Quit and reopen LangSwitcher, then try again."
            )
        finally:
            self._retry_button.setEnabled_(True)

    def close_(self, _sender):
        self.win.orderOut_(None)

    def show(self):
        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps
        )
        self.win.makeKeyAndOrderFront_(None)
