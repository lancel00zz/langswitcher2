"""Observe selected input-source changes without touching keyboard input."""

import logging
import threading

import objc
from Cocoa import (
    NSDistributedNotificationCenter,
    NSNotificationSuspensionBehaviorDeliverImmediately,
    NSObject,
)
from PyObjCTools import AppHelper


logger = logging.getLogger(__name__)

# kTISNotifySelectedKeyboardInputSourceChanged from Carbon's TextInputSources.h.
SELECTED_INPUT_SOURCE_CHANGED = "com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged"


def _require_main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Input-source observer must run on the main thread")


class InputSourceObserver(NSObject):
    """Bridge distributed notifications to a retained, deferred Python callback.

    The owner must retain this object until ``close()`` removes its registration.
    Notification payloads are deliberately ignored: the callback should query
    the current native input source and deduplicate against its own state.
    """

    def initWithCallback_(self, callback):
        self = objc.super(InputSourceObserver, self).init()
        if self:
            if not callable(callback):
                raise TypeError("Input-source callback must be callable")
            self._callback = callback
            self._center = None
            self._started = False
            self._closed = False
        return self

    def start(self):
        """Register once on the main thread, including while the app is inactive."""
        _require_main_thread()
        if self._closed:
            raise RuntimeError("Input-source observer is closed")
        if self._started:
            return self
        center = NSDistributedNotificationCenter.defaultCenter()
        center.addObserver_selector_name_object_suspensionBehavior_(
            self,
            "inputSourceChanged:",
            SELECTED_INPUT_SOURCE_CHANGED,
            None,
            NSNotificationSuspensionBehaviorDeliverImmediately,
        )
        self._center = center
        self._started = True
        return self

    def inputSourceChanged_(self, _notification):
        """Defer even main-thread delivery until an in-flight switch has finished."""
        if not self._started or self._closed:
            return
        try:
            AppHelper.callAfter(self._deliver)
        except Exception:
            logger.exception("Could not schedule the input-source change callback")

    @objc.python_method
    def _deliver(self):
        if self._closed or not self._started:
            return
        try:
            self._callback()
        except Exception:
            logger.exception("Input-source change callback failed")

    def close(self):
        """Stop delivery, cancel queued callbacks, and remove our registration."""
        _require_main_thread()
        self._closed = True
        self._callback = None
        if self._center is not None:
            # Keep the center if removal raises, so another close can retry.
            self._center.removeObserver_name_object_(
                self, SELECTED_INPUT_SOURCE_CHANGED, None,
            )
            self._center = None
        self._started = False
