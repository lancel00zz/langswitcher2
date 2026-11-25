"""Flag geometry and native overlay lifecycle without creating a window."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui import layout_overlay as overlay


class FlagGeometryTests(unittest.TestCase):
    def test_position_respects_visible_frame_and_menu_dock_insets(self):
        self.assertEqual(overlay.centered_origin(((0, 60), (1440, 810))), (525, 348))

    def test_position_supports_screen_left_of_or_above_main_screen(self):
        self.assertEqual(overlay.centered_origin(((-1920, 200), (1920, 1080))), (-1155, 623))

    def test_position_accepts_named_native_struct(self):
        frame = SimpleNamespace(origin=SimpleNamespace(x=-100, y=-900),
                                size=SimpleNamespace(width=1600, height=900))
        self.assertEqual(overlay.centered_origin(frame), (505, -567))

    def test_all_anchors_respect_negative_screen_origin(self):
        frame, size = ((-1200, -700), (1200, 700)), (390, 234)
        for anchor, expected in {
            'center': (-795, -467), 'top_left': (-1176, -258),
            'top_right': (-414, -258), 'bottom_left': (-1176, -676),
            'bottom_right': (-414, -676),
        }.items():
            with self.subTest(anchor=anchor):
                self.assertEqual(overlay.positioned_origin(frame, size, anchor), expected)

    def test_scaled_size_is_sixty_percent_bigger_and_fits_small_displays(self):
        width, height = overlay.fitted_panel_size(((0, 0), (1440, 900)))
        self.assertAlmostEqual(width, 624)
        self.assertAlmostEqual(height, 374.4)
        width, height = overlay.fitted_panel_size(((0, 0), (300, 200)), 250)
        self.assertLessEqual(width, 252)
        self.assertLessEqual(height, 152)
        self.assertAlmostEqual(width / height, 390 / 234)

    def test_french_flag_has_equal_blue_white_red_columns_and_correct_ratio(self):
        shapes = overlay.flag_shapes('fr')
        self.assertEqual(len(shapes), 3)
        rectangles = [shape[2] for shape in shapes]
        for index, rect in enumerate(rectangles):
            self.assertAlmostEqual(rect[2], 78 * 1.3)
            self.assertAlmostEqual(rect[3], 156 * 1.3)
            self.assertAlmostEqual(rect[0], (33 + index * 78) * 1.3)
        self.assertEqual(shapes[1][1], (1, 1, 1))
        self.assertGreater(shapes[0][1][2], shapes[0][1][0])
        self.assertGreater(shapes[2][1][0], shapes[2][1][2])

    def test_us_flag_has_thirteen_stripes_fifty_stars_and_seven_stripe_canton(self):
        shapes = overlay.flag_shapes('en')
        stripes, canton = shapes[:13], shapes[13]
        self.assertEqual(len(stripes), 13)
        self.assertEqual(sum(shape[0] == 'star' for shape in shapes), 50)
        self.assertEqual(stripes[0][1], stripes[-1][1])
        self.assertNotEqual(stripes[0][1], stripes[1][1])
        self.assertAlmostEqual(stripes[0][2][2] / (13 * stripes[0][2][3]), 1.9)
        self.assertAlmostEqual(canton[2][3], 7 * stripes[0][2][3])
        for kind, _color, points in shapes[14:]:
            self.assertEqual(kind, 'star')
            self.assertEqual(len(points), 10)
            for x, y in points:
                self.assertGreaterEqual(x, canton[2][0])
                self.assertLessEqual(x, canton[2][0] + canton[2][2])
                self.assertGreaterEqual(y, canton[2][1])
                self.assertLessEqual(y, canton[2][1] + canton[2][3])

    def test_unsupported_language_has_no_flag(self):
        for lang in ('de', '', None):
            self.assertEqual(overlay.flag_shapes(lang), [])


class OverlayLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.overlay = overlay.LayoutOverlay.alloc().init()
        self.overlay._panel = Mock()
        self.overlay._view = Mock()
        self.screen_patch = patch.object(overlay, 'NSScreen')
        self.screen = self.screen_patch.start()
        self.addCleanup(self.screen_patch.stop)
        self.screen.mainScreen.return_value.visibleFrame.return_value = ((0, 0), (1440, 900))
        self.timer_patch = patch.object(overlay, 'NSTimer')
        self.timer = self.timer_patch.start()
        self.addCleanup(self.timer_patch.stop)
        self.loop_patch = patch.object(overlay, 'NSRunLoop')
        self.loop = self.loop_patch.start()
        self.addCleanup(self.loop_patch.stop)

    def test_show_uses_one_shot_half_second_timer_in_common_modes(self):
        self.assertTrue(self.overlay.show_language('fr'))
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.assert_called_once_with(
            0.5, self.overlay, 'hide:', None, False,
        )
        self.loop.mainRunLoop.return_value.addTimer_forMode_.assert_called_once_with(
            self.overlay._timer, overlay.NSRunLoopCommonModes,
        )
        self.assertEqual(self.overlay._view.language, 'fr')
        x, y = self.overlay._panel.setFrameOrigin_.call_args.args[0]
        self.assertAlmostEqual(x, 408)
        self.assertAlmostEqual(y, 262.8)
        width, height = self.overlay._panel.setContentSize_.call_args.args[0]
        self.assertAlmostEqual(width, 624)
        self.assertAlmostEqual(height, 374.4)
        self.overlay._panel.orderFrontRegardless.assert_called_once_with()
        self.overlay._panel.makeKeyAndOrderFront_.assert_not_called()

    def test_rapid_changes_replace_flag_restart_timer_and_ignore_old_callback(self):
        first, second = Mock(), Mock()
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.side_effect = [first, second]
        self.overlay.show_language('fr')
        self.overlay.show_language('en')
        first.invalidate.assert_called_once()
        self.assertEqual(self.overlay._view.language, 'en')
        self.overlay.hide_(first)
        self.overlay._panel.orderOut_.assert_not_called()
        self.assertIs(self.overlay._timer, second)
        self.overlay.hide_(second)
        self.overlay._panel.orderOut_.assert_called_once_with(None)
        self.assertIsNone(self.overlay._timer)

    def test_close_invalidates_timer_and_late_callback_cannot_hide_a_new_show(self):
        first, second = Mock(), Mock()
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.side_effect = [first, second]
        self.overlay.show_language('en')
        self.overlay.close()
        first.invalidate.assert_called_once()
        self.overlay._panel.orderOut_.reset_mock()
        self.overlay.show_language('fr')
        self.overlay.hide_(first)
        self.overlay._panel.orderOut_.assert_not_called()

    def test_unknown_language_clears_existing_flag_without_starting_timer(self):
        self.assertFalse(self.overlay.show_language('de'))
        self.overlay._panel.orderOut_.assert_called_once_with(None)
        self.overlay._panel.orderFrontRegardless.assert_not_called()
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.assert_not_called()

    def test_no_display_does_not_show_panel(self):
        self.screen.mainScreen.return_value = None
        self.assertFalse(self.overlay.show_language('en'))
        self.overlay._panel.orderFrontRegardless.assert_not_called()

    def test_background_thread_is_rejected_before_ui_calls(self):
        errors = []
        def show():
            try:
                self.overlay.show_language('fr')
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=show)
        thread.start()
        thread.join()
        self.assertEqual(errors, ['Layout overlay must run on the main thread'])
        self.screen.mainScreen.assert_not_called()

    def test_lazy_panel_is_nonactivating_and_mouse_transparent(self):
        self.overlay._panel = None
        with patch.object(overlay, '_FlagPanel') as panel_class, \
                patch.object(overlay, '_FlagView') as view_class:
            panel = panel_class.alloc.return_value.initWithContentRect_styleMask_backing_defer_.return_value
            self.overlay.show_language('fr')
            args = panel_class.alloc.return_value.initWithContentRect_styleMask_backing_defer_.call_args.args
            self.assertTrue(args[1] & overlay.NSWindowStyleMaskNonactivatingPanel)
            panel.setIgnoresMouseEvents_.assert_called_once_with(True)
            panel.setAlphaValue_.assert_called_once_with(0.5)
            panel.setHidesOnDeactivate_.assert_called_once_with(False)
            panel.setCollectionBehavior_.assert_called_once_with(
                overlay.NSWindowCollectionBehaviorCanJoinAllSpaces
                | overlay.NSWindowCollectionBehaviorFullScreenAuxiliary
                | overlay.NSWindowCollectionBehaviorIgnoresCycle,
            )
            panel.makeKeyAndOrderFront_.assert_not_called()
            view_class.alloc.assert_called_once()

    def test_disabling_live_overlay_hides_it_and_prevents_future_shows(self):
        self.overlay.show_language('fr')
        timer = self.overlay._timer
        self.overlay.configure(SimpleNamespace(enabled=False, size_percent=160,
                                               position='center', opacity_percent=50))
        timer.invalidate.assert_called_once()
        self.overlay._panel.orderOut_.assert_called_once_with(None)
        self.assertIsNone(self.overlay._timer)
        self.overlay._panel.orderFrontRegardless.reset_mock()
        self.assertFalse(self.overlay.show_language('en'))
        self.overlay._panel.orderFrontRegardless.assert_not_called()

    def test_live_preferences_update_without_restarting_flash_or_changing_language(self):
        self.overlay.show_language('fr')
        timer = self.overlay._timer
        settings = SimpleNamespace(enabled=True, size_percent=100,
                                   position='bottom_right', opacity_percent=80)
        self.overlay.configure(settings)
        settings.size_percent = 250
        self.assertEqual(self.overlay._size_percent, 100)
        self.overlay._panel.setContentSize_.assert_called_with((390, 234))
        self.overlay._panel.setFrameOrigin_.assert_called_with((1026, 24))
        self.overlay._panel.setAlphaValue_.assert_called_with(0.8)
        self.assertEqual(self.overlay._view.language, 'fr')
        self.assertIs(self.overlay._timer, timer)
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.assert_called_once()
        self.overlay._panel.orderFrontRegardless.assert_called_once()
        timer.invalidate.assert_not_called()

    def test_preview_stays_visible_without_timer_or_focus(self):
        self.assertTrue(self.overlay.show_preview('fr'))
        self.assertTrue(self.overlay._visible)
        self.assertIsNone(self.overlay._timer)
        self.assertEqual(self.overlay._view.language, 'fr')
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.assert_not_called()
        self.overlay._panel.orderFrontRegardless.assert_called_once_with()
        self.overlay._panel.makeKeyAndOrderFront_.assert_not_called()
        self.overlay.hide_(None)
        self.overlay._panel.orderOut_.assert_not_called()

    def test_preview_cancels_old_timer_and_live_updates_remain_persistent(self):
        self.overlay.show_language('en')
        old_timer = self.overlay._timer
        self.overlay.show_preview('fr')
        old_timer.invalidate.assert_called_once()
        self.overlay.configure(SimpleNamespace(enabled=True, size_percent=100,
                                               position='top_left', opacity_percent=80))
        self.overlay._panel.setContentSize_.assert_called_with((390, 234))
        self.overlay._panel.setFrameOrigin_.assert_called_with((24, 642))
        self.overlay._panel.setAlphaValue_.assert_called_with(0.8)
        self.assertEqual(self.overlay._view.language, 'fr')
        self.assertIsNone(self.overlay._timer)
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.assert_called_once()
        self.overlay.hide_(old_timer)
        self.overlay._panel.orderOut_.assert_not_called()

    def test_close_hides_preview_and_normal_feedback_still_uses_timer(self):
        self.overlay.show_preview('fr')
        self.overlay.close()
        self.assertFalse(self.overlay._visible)
        self.overlay._panel.orderOut_.assert_called_once_with(None)
        self.overlay.show_language('en')
        self.timer.timerWithTimeInterval_target_selector_userInfo_repeats_.assert_called_once_with(
            0.5, self.overlay, 'hide:', None, False,
        )

    def test_native_panel_can_never_become_key_or_main(self):
        # These policy methods do not need to instantiate an NSPanel.
        self.assertFalse(overlay._FlagPanel.canBecomeKeyWindow.callable(None))
        self.assertFalse(overlay._FlagPanel.canBecomeMainWindow.callable(None))


if __name__ == '__main__':
    unittest.main()
