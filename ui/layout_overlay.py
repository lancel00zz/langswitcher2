"""A brief, mouse-transparent native flag when the keyboard layout changes."""

import math
import threading

import objc
from Cocoa import (
    NSBackingStoreBuffered, NSBezierPath, NSColor,
    NSMakeRect, NSObject, NSPanel, NSRunLoop, NSRunLoopCommonModes, NSScreen,
    NSStatusWindowLevel, NSTimer, NSView, NSWindowAnimationBehaviorNone,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
)


PANEL_SIZE = (390, 234)
FLAG_PADDING = 15.6
PANEL_OPACITY = 0.5
DEFAULT_SIZE_PERCENT = 160
SCREEN_MARGIN = 24
DISPLAY_SECONDS = 0.5
SUPPORTED_LANGUAGES = frozenset(("en", "fr"))


def _frame_parts(visible_frame):
    try:
        x, y = visible_frame.origin.x, visible_frame.origin.y
        width, height = visible_frame.size.width, visible_frame.size.height
    except AttributeError:
        (x, y), (width, height) = visible_frame
    return x, y, width, height


def fitted_panel_size(visible_frame, size_percent=DEFAULT_SIZE_PERCENT):
    """Scale from the 100% preview, preserving ratio inside screen margins."""
    _, _, width, height = _frame_parts(visible_frame)
    scale = min(size_percent / 100,
                max(1, width - SCREEN_MARGIN * 2) / PANEL_SIZE[0],
                max(1, height - SCREEN_MARGIN * 2) / PANEL_SIZE[1])
    return PANEL_SIZE[0] * scale, PANEL_SIZE[1] * scale


def positioned_origin(visible_frame, panel_size, position='center'):
    """Anchor in usable screen coordinates, including negative screen origins."""
    x, y, width, height = _frame_parts(visible_frame)
    if position == 'center':
        return x + (width - panel_size[0]) / 2, y + (height - panel_size[1]) / 2
    if position not in {'top_left', 'top_right', 'bottom_left', 'bottom_right'}:
        raise ValueError(f'Unknown overlay position: {position}')
    margin_x = min(SCREEN_MARGIN, max(0, (width - panel_size[0]) / 2))
    margin_y = min(SCREEN_MARGIN, max(0, (height - panel_size[1]) / 2))
    return (x + width - panel_size[0] - margin_x if position.endswith('right') else x + margin_x,
            y + height - panel_size[1] - margin_y if position.startswith('top') else y + margin_y)


def centered_origin(visible_frame, panel_size=PANEL_SIZE):
    """Center the panel in this screen's usable area, including negative origins."""
    return positioned_origin(visible_frame, panel_size)


def star_points(x, y, radius):
    """Ten alternating vertices form one upright, five-point star."""
    inner = radius * math.sin(math.pi / 10) / math.sin(3 * math.pi / 10)
    return [
        (x + (radius if index % 2 == 0 else inner) * math.cos(math.pi / 2 + index * math.pi / 5),
         y + (radius if index % 2 == 0 else inner) * math.sin(math.pi / 2 + index * math.pi / 5))
        for index in range(10)
    ]


def flag_shapes(lang, width=PANEL_SIZE[0], height=PANEL_SIZE[1], padding=FLAG_PADDING):
    """Return vector shapes, preserving French and US flag proportions."""
    if lang not in SUPPORTED_LANGUAGES:
        return []
    ratio = 1.5 if lang == "fr" else 1.9
    flag_width = min(width - padding * 2, (height - padding * 2) * ratio)
    flag_height = flag_width / ratio
    x, y = (width - flag_width) / 2, (height - flag_height) / 2
    if lang == "fr":
        return [
            ("rect", color, (x + index * flag_width / 3, y, flag_width / 3, flag_height))
            for index, color in enumerate(((0, 0.15, 0.33), (1, 1, 1), (0.93, 0.16, 0.22)))
        ]
    stripe = flag_height / 13
    red, white, blue = (0.7, 0.13, 0.2), (1, 1, 1), (0.235, 0.23, 0.43)
    shapes = [
        ("rect", red if row % 2 == 0 else white,
         (x, y + flag_height - (row + 1) * stripe, flag_width, stripe))
        for row in range(13)
    ]
    canton_width, canton_height = flag_width * 0.4, stripe * 7
    canton_y = y + flag_height - canton_height
    shapes.append(("rect", blue, (x, canton_y, canton_width, canton_height)))
    cell_x, cell_y = canton_width / 12, canton_height / 10
    for row in range(9):
        for column in range(6 if row % 2 == 0 else 5):
            center_x = x + (1 + column * 2 + row % 2) * cell_x
            center_y = y + flag_height - (row + 1) * cell_y
            shapes.append(("star", white, star_points(center_x, center_y, stripe * 0.4)))
    return shapes


class _FlagPanel(NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


class _FlagView(NSView):
    def drawRect_(self, _dirty_rect):
        bounds = self.bounds()
        scale = bounds.size.width / PANEL_SIZE[0]
        NSColor.windowBackgroundColor().colorWithAlphaComponent_(0.94).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 16 * scale, 16 * scale).fill()
        for kind, color, geometry in flag_shapes(
                getattr(self, "language", None), bounds.size.width, bounds.size.height,
                padding=FLAG_PADDING * scale):
            NSColor.colorWithSRGBRed_green_blue_alpha_(*color, 1).setFill()
            if kind == "rect":
                NSBezierPath.bezierPathWithRect_(NSMakeRect(*geometry)).fill()
            else:
                path = NSBezierPath.bezierPath()
                path.moveToPoint_(geometry[0])
                for point in geometry[1:]:
                    path.lineToPoint_(point)
                path.closePath()
                path.fill()


class LayoutOverlay(NSObject):
    """Show a flag for half a second without activating or focusing a window."""

    def init(self):
        self = objc.super(LayoutOverlay, self).init()
        if self:
            self._panel = None
            self._view = None
            self._timer = None
            self._visible = False
            self._enabled = True
            self._size_percent = DEFAULT_SIZE_PERCENT
            self._position = 'center'
            self._opacity_percent = PANEL_OPACITY * 100
        return self

    @staticmethod
    @objc.python_method
    def _require_main_thread():
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Layout overlay must run on the main thread")

    @objc.python_method
    def _ensure_panel(self):
        if self._panel is not None:
            return
        frame = NSMakeRect(0, 0, *PANEL_SIZE)
        self._panel = _FlagPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False,
        )
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setHasShadow_(True)
        self._panel.setIgnoresMouseEvents_(True)
        self._panel.setFloatingPanel_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setLevel_(NSStatusWindowLevel)
        self._panel.setAnimationBehavior_(NSWindowAnimationBehaviorNone)
        self._panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        self._view = _FlagView.alloc().initWithFrame_(frame)
        self._panel.setContentView_(self._view)

    @objc.python_method
    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    @objc.python_method
    def configure(self, settings):
        """Apply a copy of validated preferences without replaying feedback."""
        self._require_main_thread()
        self._enabled = bool(settings.enabled)
        self._size_percent = int(settings.size_percent)
        self._position = str(settings.position)
        self._opacity_percent = int(settings.opacity_percent)
        if not self._enabled:
            self.close()
        elif self._visible:
            screen = NSScreen.mainScreen()
            if screen is None:
                self.close()
            else:
                self._apply_layout(screen.visibleFrame())

    @objc.python_method
    def _apply_layout(self, visible_frame):
        size = fitted_panel_size(visible_frame, self._size_percent)
        self._panel.setContentSize_(size)
        self._view.setFrame_(NSMakeRect(0, 0, *size))
        self._panel.setFrameOrigin_(positioned_origin(visible_frame, size, self._position))
        self._panel.setAlphaValue_(self._opacity_percent / 100)
        self._view.setNeedsDisplay_(True)

    @objc.python_method
    def show_language(self, lang):
        """Show normal layout-change feedback for half a second."""
        return self._show(lang, persistent=False)

    @objc.python_method
    def show_preview(self, lang):
        """Show a Settings preview until explicitly closed or disabled."""
        return self._show(lang, persistent=True)

    @objc.python_method
    def _show(self, lang, persistent):
        self._require_main_thread()
        if not self._enabled or lang not in SUPPORTED_LANGUAGES:
            self.close()
            return False
        screen = NSScreen.mainScreen()
        if screen is None:
            self.close()
            return False
        self._cancel_timer()
        self._ensure_panel()
        self._view.language = lang
        self._apply_layout(screen.visibleFrame())
        # This orders across apps without changing the key/main window.
        # Never call makeKey/activate APIs for feedback while someone is typing.
        self._panel.orderFrontRegardless()
        self._visible = True
        if not persistent:
            self._timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                DISPLAY_SECONDS, self, "hide:", None, False,
            )
            NSRunLoop.mainRunLoop().addTimer_forMode_(self._timer, NSRunLoopCommonModes)
        return True

    def hide_(self, timer):
        self._require_main_thread()
        if self._timer is None or timer != self._timer:
            return
        self._timer = None
        self._visible = False
        if self._panel is not None:
            self._panel.orderOut_(None)

    @objc.python_method
    def close(self):
        self._require_main_thread()
        self._cancel_timer()
        self._visible = False
        if self._panel is not None:
            self._panel.orderOut_(None)
