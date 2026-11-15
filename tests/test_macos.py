"""Native-boundary tests without changing the user's keyboard layout."""

import ctypes
import unittest

from switchers.macos import NativeInputSources, _CarbonAPI, _carbon_modifiers


EN = 'com.apple.keylayout.US'
FR = 'com.apple.keylayout.Canadian-CSA'


class FakeCarbonAPI:
    def __init__(self):
        self.sources = {11: EN, 12: FR, 13: 'unrelated.input'}
        self.source_list = object()
        self.retained = []
        self.released = []
        self.selections = []
        self.translations = []
        self.snapshots = 0
        self.current = 11
        self.status = 0

    def create_source_list(self):
        self.snapshots += 1
        return self.source_list

    def source_count(self, _):
        return len(self.sources)

    def source_at(self, _, index):
        return list(self.sources)[index]

    def source_id(self, source):
        return self.sources[source]

    def retain(self, source):
        self.retained.append(source)
        return source

    def release(self, source):
        self.released.append(source)

    def copy_current(self):
        return self.current

    def select_source(self, source):
        self.selections.append(source)
        return self.status

    def translate(self, source, vk, modifiers):
        self.translations.append((source, vk, modifiers))
        return 'é'


class NativeInputSourcesTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeCarbonAPI()
        self.on_main = True
        self.backend = NativeInputSources([EN, FR], api=self.api,
                                          is_main_thread=lambda: self.on_main)
        self.addCleanup(self.cleanup_backend)

    def cleanup_backend(self):
        self.on_main = True
        self.backend.close()

    def test_only_configured_sources_are_retained_after_snapshot_release(self):
        self.assertEqual(self.api.retained, [11, 12])
        self.assertEqual(self.api.released, [self.api.source_list])

    def test_queries_actual_current_source_each_time_and_releases_copy(self):
        self.assertEqual(self.backend.get_current_layout_id(), EN)
        self.api.current = 12
        self.assertEqual(self.backend.get_current_layout_id(), FR)
        self.assertEqual(self.api.released[-2:], [11, 12])

    def test_null_current_source_returns_none_without_release(self):
        self.api.current = None
        before = self.api.released[:]
        self.assertIsNone(self.backend.get_current_layout_id())
        self.assertEqual(self.api.released, before)

    def test_current_source_copy_is_released_on_property_failure(self):
        self.api.current = 999
        with self.assertRaises(KeyError):
            self.backend.get_current_layout_id()
        self.assertEqual(self.api.released[-1], 999)

    def test_selection_reuses_cache_without_enumeration(self):
        self.assertTrue(self.backend.select(FR))
        self.assertTrue(self.backend.select(EN))
        self.assertEqual(self.api.selections, [12, 11])
        self.assertEqual(self.api.snapshots, 1)

    def test_unconfigured_layout_is_not_selected(self):
        self.assertFalse(self.backend.select('unrelated.input'))
        self.assertEqual(self.api.selections, [])

    def test_native_selection_failure_is_not_reported_as_success(self):
        self.api.status = -50
        self.assertFalse(self.backend.select(FR))

    def test_missing_required_source_fails_startup_and_releases_cache(self):
        api = FakeCarbonAPI()
        del api.sources[12]
        with self.assertRaisesRegex(RuntimeError, 'Enable Canadian – CSA.*Keyboard > Input Sources'):
            NativeInputSources([EN, FR], api=api)
        self.assertEqual(api.retained, [11])
        self.assertEqual(api.released, [api.source_list, 11])
        self.assertEqual(api.selections, [])

    def test_unknown_missing_required_layout_has_actionable_error(self):
        api = FakeCarbonAPI()
        with self.assertRaisesRegex(RuntimeError, 'Enable custom.missing.*Input Sources'):
            NativeInputSources(['custom.missing'], api=api)
        self.assertEqual(api.retained, [])
        self.assertEqual(api.released, [api.source_list])

    def test_unrestricted_backend_can_discover_newly_enabled_sources(self):
        api = FakeCarbonAPI()
        with NativeInputSources(api=api) as backend:
            api.sources[14] = 'custom.new'
            self.assertTrue(backend.select('custom.new'))
            self.assertEqual(api.selections, [14])

    def test_thread_check_prevents_all_native_operations_on_worker(self):
        self.on_main = False
        calls = [self.backend.get_current_layout_id,
                 lambda: self.backend.select(FR),
                 lambda: self.backend.translate_key(FR, 44, 0), self.backend.close]
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaisesRegex(RuntimeError, 'main thread'):
                    call()
        self.assertEqual(self.api.selections, [])
        self.assertEqual(self.api.translations, [])

    def test_constructor_rejects_worker_before_loading_native_api(self):
        with self.assertRaisesRegex(RuntimeError, 'main thread'):
            NativeInputSources([EN], is_main_thread=lambda: False)

    def test_close_releases_each_cached_source_once(self):
        self.backend.close()
        self.backend.close()
        self.assertEqual(self.api.released.count(11), 1)
        self.assertEqual(self.api.released.count(12), 1)
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            self.backend.get_current_layout_id()

    def test_translate_uses_requested_layout_and_quartz_modifiers(self):
        self.assertEqual(self.backend.translate_key(FR, 44, (1 << 17) | (1 << 19)), 'é')
        self.assertEqual(self.api.translations, [(12, 44, 10)])
        self.assertEqual(self.api.selections, [])

    def test_translation_of_unknown_layout_or_invalid_key_is_unavailable(self):
        for layout, vk in [('unknown', 44), (EN, -1), (EN, 65536)]:
            self.assertIsNone(self.backend.translate_key(layout, vk, 0))
        self.assertEqual(self.api.translations, [])

    def test_modifier_conversion_uses_carbon_values(self):
        self.assertEqual(_carbon_modifiers(0), 0)
        self.assertEqual(_carbon_modifiers(1 << 17), 2)  # Shift
        self.assertEqual(_carbon_modifiers(1 << 16), 4)  # Caps Lock
        self.assertEqual(_carbon_modifiers(1 << 19), 8)  # Option
        self.assertEqual(_carbon_modifiers((1 << 17) | (1 << 16) | (1 << 19)), 14)
        self.assertEqual(_carbon_modifiers((1 << 18) | (1 << 20)), 0)  # Control/Command

    def test_failed_cache_initialization_releases_already_retained_sources(self):
        api = FakeCarbonAPI()
        def fail_on_second_source(source):
            if source == 12:
                raise RuntimeError('property unavailable')
            return api.sources[source]
        api.source_id = fail_on_second_source
        with self.assertRaisesRegex(RuntimeError, 'property unavailable'):
            NativeInputSources([EN, FR], api=api)
        self.assertEqual(api.retained, [11])
        self.assertEqual(api.released, [11, api.source_list])


class NativeTranslationBufferTests(unittest.TestCase):
    def test_utf16_output_decodes_accents_and_surrogate_pairs(self):
        # Exercise ctypes output ownership/width without calling system APIs.
        for text in ('é', 'É', '😀'):
            with self.subTest(text=text):
                api = _CarbonAPI.__new__(_CarbonAPI)
                api._layout_data_key = object()
                api._property = lambda *_: 7
                api._data_bytes = lambda _: 8
                api._keyboard_type = lambda: 40
                def translate(layout, vk, action, modifiers, keyboard, options,
                              dead_state, maximum, actual, output):
                    self.assertEqual((layout, vk, action, modifiers, keyboard, options),
                                     (8, 44, 0, 2, 40, 1))
                    self.assertEqual(ctypes.cast(dead_state, ctypes.POINTER(ctypes.c_uint32))[0], 0)
                    data = text.encode('utf-16-le')
                    units = [int.from_bytes(data[i:i + 2], 'little') for i in range(0, len(data), 2)]
                    for index, unit in enumerate(units):
                        output[index] = unit
                    ctypes.cast(actual, ctypes.POINTER(ctypes.c_ulong))[0] = len(units)
                    return 0
                api._translate = translate
                self.assertEqual(api.translate(11, 44, 2), text)

    def test_missing_unicode_layout_data_is_unavailable(self):
        api = _CarbonAPI.__new__(_CarbonAPI)
        api._layout_data_key = object()
        api._property = lambda *_: None
        self.assertIsNone(api.translate(11, 44, 0))


if __name__ == '__main__':
    unittest.main()
