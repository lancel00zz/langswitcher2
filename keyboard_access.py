"""Nonprompting keyboard-access diagnostics for the current app process."""

from dataclasses import dataclass
import logging
from typing import Optional

from ApplicationServices import AXIsProcessTrusted
from Quartz import CGPreflightListenEventAccess


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccessReport:
    keyboard_access: bool
    accessibility: Optional[bool] = None
    input_monitoring: Optional[bool] = None
    reason: str = ''
    details: str = ''


def _probe(check, label):
    try:
        return bool(check())
    except Exception:
        logger.warning('Could not check %s permission', label, exc_info=True)
        return None


def collect_access_report(keyboard_access=False, reason='', details='') -> AccessReport:
    """Check this process only; never request permission or generate events.

    Permission preflights can disagree with the actual tap after a grant or
    signature change. Only verified native tap metadata establishes that the
    app currently has the keyboard events it needs.
    """
    return AccessReport(
        keyboard_access=bool(keyboard_access),
        accessibility=_probe(AXIsProcessTrusted, 'Device Control and Data Access'),
        input_monitoring=_probe(CGPreflightListenEventAccess, 'Input Monitoring'),
        reason=reason,
        details=details,
    )


class KeyboardAccessError(RuntimeError):
    """A recoverable keyboard-access failure with nonprompting diagnostics."""

    def __init__(self, report: AccessReport):
        self.report = report
        super().__init__(
            'LangSwitcher could not verify keyboard access. In System Settings > '
            'Privacy & Security, check Input Monitoring and Device Control and '
            'Data Access (Accessibility on older macOS), then quit and reopen '
            'LangSwitcher.'
        )
