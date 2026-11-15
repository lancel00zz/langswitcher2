"""Native input-source access for the macOS main run loop.

Apple's TextInputSources.h explicitly requires UI applications to call TIS
on the main thread. The event tap must therefore run on that same run loop;
calling this backend from a pynput worker is deliberately rejected.
"""

import ctypes
import logging
import sys
import threading
from typing import Iterable, Optional


def _carbon_modifiers(flags: int) -> int:
    """Convert Quartz shift/caps/option flags to UCKeyTranslate's modifiers."""
    # Carbon EventRecord modifier bits are shifted right eight positions for
    # UCKeyTranslate (UnicodeUtilities.h). Quartz uses different bit positions.
    result = 0
    for quartz_mask, carbon_state in ((1 << 17, 2), (1 << 16, 4), (1 << 19, 8)):
        if flags & quartz_mask:
            result |= carbon_state
    return result


class _CarbonAPI:
    """Small ctypes boundary; objects returned by Copy/Create are owned."""

    def __init__(self):
        self.carbon = ctypes.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        pointer = ctypes.c_void_p
        index = ctypes.c_long

        def bind(library, name, arguments, result):
            function = getattr(library, name)
            function.argtypes = arguments
            function.restype = result
            return function

        self._create_list = bind(self.carbon, 'TISCreateInputSourceList', [pointer, ctypes.c_ubyte], pointer)
        self._copy_current = bind(self.carbon, 'TISCopyCurrentKeyboardInputSource', [], pointer)
        self._property = bind(self.carbon, 'TISGetInputSourceProperty', [pointer, pointer], pointer)
        self._select = bind(self.carbon, 'TISSelectInputSource', [pointer], ctypes.c_int32)
        self._count = bind(self.cf, 'CFArrayGetCount', [pointer], index)
        self._item = bind(self.cf, 'CFArrayGetValueAtIndex', [pointer, index], pointer)
        self._retain = bind(self.cf, 'CFRetain', [pointer], pointer)
        self._release = bind(self.cf, 'CFRelease', [pointer], None)
        self._string_length = bind(self.cf, 'CFStringGetLength', [pointer], index)
        self._string_bytes = bind(self.cf, 'CFStringGetCString',
                                  [pointer, pointer, index, ctypes.c_uint32], ctypes.c_ubyte)
        self._data_bytes = bind(self.cf, 'CFDataGetBytePtr', [pointer], pointer)
        self._keyboard_type = bind(self.carbon, 'LMGetKbdType', [], ctypes.c_ubyte)
        self._translate = bind(self.carbon, 'UCKeyTranslate', [
            pointer, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_uint16),
        ], ctypes.c_int32)
        self._id_key = pointer.in_dll(self.carbon, 'kTISPropertyInputSourceID')
        self._layout_data_key = pointer.in_dll(self.carbon, 'kTISPropertyUnicodeKeyLayoutData')

    def create_source_list(self):
        # False limits the snapshot to sources already enabled by the user.
        return self._create_list(None, False)

    def source_count(self, source_list):
        return self._count(source_list)

    def source_at(self, source_list, index):
        return self._item(source_list, index)

    def retain(self, value):
        return self._retain(value)

    def release(self, value):
        self._release(value)

    def source_id(self, source) -> Optional[str]:
        # TISGetInputSourceProperty follows the Get rule: do not release it.
        value = self._property(source, self._id_key)
        if not value:
            return None
        buffer = ctypes.create_string_buffer(self._string_length(value) * 4 + 1)
        if not self._string_bytes(value, buffer, len(buffer), 0x08000100):  # UTF-8
            return None
        return buffer.value.decode('utf-8')

    def copy_current(self):
        return self._copy_current()

    def select_source(self, source):
        return self._select(source)

    def translate(self, source, vk: int, modifiers: int) -> Optional[str]:
        data = self._property(source, self._layout_data_key)
        if not data:
            return None
        layout = self._data_bytes(data)
        if not layout:
            return None
        # This is a local translation only. Dead-key state is never injected
        # into the system or carried between calls.
        dead_state = ctypes.c_uint32(0)
        actual_count = ctypes.c_ulong(0)  # UniCharCount is unsigned long.
        output = (ctypes.c_uint16 * 255)()
        status = self._translate(layout, vk, 0, modifiers, self._keyboard_type(),
                                 1, ctypes.byref(dead_state), len(output),
                                 ctypes.byref(actual_count), output)
        if status != 0 or not 0 < actual_count.value <= len(output):
            return None
        encoding = 'utf-16-le' if sys.byteorder == 'little' else 'utf-16-be'
        return ctypes.string_at(output, actual_count.value * 2).decode(encoding)


class NativeInputSources:
    """Cache enabled layout references and access them on the main thread.

    ``close()`` must be called on the main thread when the app quits. Tests can
    inject the native boundary and thread check without accessing macOS input.
    """

    def __init__(self, layout_ids: Iterable[str] = (), *, api=None, is_main_thread=None):
        self._is_main_thread = is_main_thread or (
            lambda: threading.current_thread() is threading.main_thread()
        )
        self._require_main_thread()
        self._api = api if api is not None else _CarbonAPI()
        self._layout_ids = frozenset(layout_ids)
        self._sources = {}
        self._closed = False
        self._refresh_sources()
        missing = self._layout_ids.difference(self._sources)
        if missing:
            # Do not leave a partially usable switcher, or leak references
            # retained while validating the enabled-source snapshot.
            self.close()
            labels = {
                'com.apple.keylayout.US': 'U.S.',
                'com.apple.keylayout.Canadian-CSA': 'Canadian – CSA',
            }
            names = ', '.join(labels.get(layout_id, layout_id) for layout_id in sorted(missing))
            raise RuntimeError(
                f'Required keyboard input sources are not enabled. Enable {names} '
                'in System Settings > Keyboard > Input Sources, then relaunch LangSwitcher.'
            )

    def _require_main_thread(self):
        if not self._is_main_thread():
            raise RuntimeError('macOS input-source APIs must run on the main thread')

    def _require_open(self):
        self._require_main_thread()
        if self._closed:
            raise RuntimeError('Native input-source backend is closed')

    def _refresh_sources(self):
        source_list = self._api.create_source_list()
        if not source_list:
            raise RuntimeError('macOS did not return enabled input sources')
        sources = {}
        try:
            for index in range(self._api.source_count(source_list)):
                source = self._api.source_at(source_list, index)
                layout_id = self._api.source_id(source)
                if (layout_id and layout_id not in sources and
                        (not self._layout_ids or layout_id in self._layout_ids)):
                    sources[layout_id] = self._api.retain(source)
        except Exception:
            for source in sources.values():
                self._api.release(source)
            raise
        finally:
            self._api.release(source_list)
        for source in self._sources.values():
            self._api.release(source)
        self._sources = sources

    def get_current_layout_id(self) -> Optional[str]:
        self._require_open()
        source = self._api.copy_current()
        if not source:
            return None
        try:
            return self._api.source_id(source)
        finally:
            self._api.release(source)

    def select(self, layout_id: str) -> bool:
        self._require_open()
        if self._layout_ids and layout_id not in self._layout_ids:
            return False
        source = self._sources.get(layout_id)
        if source is None:
            self._refresh_sources()
            source = self._sources.get(layout_id)
        if source is None:
            return False
        status = self._api.select_source(source)
        if status != 0:
            logging.warning('Native input-source selection failed for %s (status %s)', layout_id, status)
            return False
        return True

    def translate_key(self, layout_id: str, vk: int, flags: int) -> Optional[str]:
        """Translate a physical key for a chosen layout without generating input.

        This stateless helper is for direct characters such as Canadian ``é``.
        It does not emulate a user's multi-key accent composition sequence.
        """
        self._require_open()
        source = self._sources.get(layout_id)
        if source is None or not 0 <= vk <= 0xFFFF:
            return None
        return self._api.translate(source, vk, _carbon_modifiers(flags))

    def close(self):
        self._require_main_thread()
        if not self._closed:
            for source in self._sources.values():
                self._api.release(source)
            self._sources.clear()
            self._closed = True

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *_):
        self.close()
