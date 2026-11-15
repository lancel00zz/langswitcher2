"""Deliver keyboard events through an active tap on the macOS main run loop.

The callback can normalize the original event before returning it to the
system. This wrapper never posts additional events or suppresses input.
"""

import logging
import os
import threading

from keyboard_access import KeyboardAccessError, collect_access_report

from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFMachPortInvalidate,
    CFRunLoopAddSource,
    CFRunLoopGetMain,
    CFRunLoopRemoveSource,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    CGGetEventTapList,
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
        self.report = None
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
        # CGEventTapCreate may silently remove unauthorized keyboard bits and
        # still return a working modifier-only tap. Compare complete snapshots
        # so another process's tap (or an older tap of ours) cannot prove access.
        before = self._snapshot_taps()
        pid = os.getpid()
        previous_ids = {info.eventTapID for info in before if info.tappingProcess == pid}
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
            raise self._access_error('tap_missing', 'macOS did not create the keyboard event tap')

        try:
            self._source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            if self._source is None:
                raise RuntimeError("Could not create the keyboard event run-loop source")
            self._run_loop = CFRunLoopGetMain()
            CFRunLoopAddSource(self._run_loop, self._source, kCFRunLoopCommonModes)
            CGEventTapEnable(self._tap, True)
            self._verify_tap(previous_ids, pid, event_mask)
        except Exception:
            self.stop()
            raise
        return self

    def _access_error(self, reason, details):
        self.report = collect_access_report(reason=reason, details=details)
        logger.warning('Keyboard access unavailable: %s; %s', reason, details)
        return KeyboardAccessError(self.report)

    def _snapshot_taps(self):
        try:
            # There are usually only tens of taps. Reject a truncated result
            # rather than incorrectly treating an unlisted old tap as new.
            maximum = 1024
            status, taps, count = CGGetEventTapList(maximum, None, None)
            if status != 0 or count != len(taps) or count >= maximum:
                raise RuntimeError(f'CGGetEventTapList status={status}, count={count}, returned={len(taps)}')
            # Read the fields needed for identification while still inside the
            # diagnostic boundary; malformed metadata is never proof of access.
            for info in taps:
                int(info.eventTapID)
                int(info.tappingProcess)
                int(info.tapPoint)
                int(info.options)
                int(info.eventsOfInterest)
                bool(info.enabled)
            return taps
        except Exception as error:
            raise self._access_error('verification_unavailable', str(error)) from error

    def _verify_tap(self, previous_ids, pid, expected_mask):
        candidates = [
            info for info in self._snapshot_taps()
            if info.tappingProcess == pid and info.eventTapID not in previous_ids
        ]
        if len(candidates) != 1:
            raise self._access_error(
                'verification_unavailable',
                f'Could not identify one newly created tap for this process (found {len(candidates)})',
            )
        info = candidates[0]
        if info.tapPoint != kCGSessionEventTap or info.options != kCGEventTapOptionDefault:
            raise self._access_error('verification_unavailable', 'New tap metadata does not match the requested keyboard filter')
        actual_mask = int(info.eventsOfInterest)
        details = f'tap={info.eventTapID}, requested_mask={expected_mask:#x}, actual_mask={actual_mask:#x}, enabled={bool(info.enabled)}'
        if actual_mask & expected_mask != expected_mask:
            raise self._access_error('keyboard_events_filtered', details)
        if not info.enabled:
            raise self._access_error('tap_disabled', details)
        self.report = collect_access_report(keyboard_access=True, reason='verified', details=details)
        logger.info('Keyboard access verified: %s', details)

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
