"""Deliver keyboard events through an active tap on the macOS main run loop.

The callback can normalize the original event before returning it to the
system. This wrapper never posts additional events or suppresses input.
"""

import logging
import threading

from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFMachPortInvalidate,
    CFRunLoopAddSource,
    CFRunLoopGetMain,
    CFRunLoopRemoveSource,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
)


logger = logging.getLogger(__name__)


class KeyboardEventTap:
    """Run ``callback(event_type, event)`` before forwarding each keyboard event.

    Call ``start`` before entering the application's main event loop. Both
    lifecycle methods must run on the main thread. The callback also runs on
    that thread and should finish promptly to keep the event tap responsive.
    """

    def __init__(self, callback):
        if not callable(callback):
            raise TypeError("Keyboard event callback must be callable")
        self._callback = callback
        self._tap = None
        self._source = None
        self._run_loop = None
        # Retain the exact bound callback supplied to Quartz for the tap's life.
        self._native_callback = self._handle_event

    @staticmethod
    def _require_main_thread():
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Keyboard event tap must run on the main thread")

    def start(self):
        """Attach an active keyboard filter to the main run loop once."""
        self._require_main_thread()
        if self._tap is not None:
            return self

        event_mask = (
            CGEventMaskBit(kCGEventKeyDown)
            | CGEventMaskBit(kCGEventKeyUp)
            | CGEventMaskBit(kCGEventFlagsChanged)
        )
        try:
            self._tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionDefault,
                event_mask,
                self._native_callback,
                None,
            )
        except Exception as error:
            raise RuntimeError("Could not create the keyboard event tap") from error
        if self._tap is None:
            raise RuntimeError(
                "Could not start the keyboard event tap. Enable LangSwitcher "
                "in System Settings > Privacy & Security > Accessibility, "
                "then relaunch the app."
            )

        try:
            self._source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            if self._source is None:
                raise RuntimeError("Could not create the keyboard event run-loop source")
            self._run_loop = CFRunLoopGetMain()
            CFRunLoopAddSource(self._run_loop, self._source, kCFRunLoopCommonModes)
            CGEventTapEnable(self._tap, True)
        except Exception:
            self.stop()
            raise
        return self

    def stop(self):
        """Disable and detach the native tap, retaining no run-loop resources."""
        self._require_main_thread()
        tap, source, run_loop = self._tap, self._source, self._run_loop
        self._tap = self._source = self._run_loop = None
        if tap is None:
            return
        try:
            CGEventTapEnable(tap, False)
        except Exception:
            logger.exception("Could not disable the keyboard event tap")
        if source is not None and run_loop is not None:
            try:
                CFRunLoopRemoveSource(run_loop, source, kCFRunLoopCommonModes)
            except Exception:
                logger.exception("Could not detach the keyboard event run-loop source")
        try:
            CFMachPortInvalidate(tap)
        except Exception:
            logger.exception("Could not invalidate the keyboard event tap")

    def _handle_event(self, _proxy, event_type, event, _refcon):
        if self._tap is None:
            return event
        try:
            if event_type in (
                kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput,
            ):
                # Disabled notifications can contain no keyboard event at all.
                CGEventTapEnable(self._tap, True)
                return event
            result = self._callback(event_type, event)
            # Forgetting a return must never drop a user's real keystroke.
            return event if result is None else result
        except Exception:
            logger.exception("Keyboard event handling failed; passing input through")
            return event
