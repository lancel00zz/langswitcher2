from setuptools import setup, find_packages
import glob, os
from version import __version__, __app_name__, __author__

# ———————————————————————————————
# 1) Auto-find libenchant dylib (optional)
candidates = glob.glob('/opt/homebrew/lib/libenchant-*.dylib') + \
             glob.glob('/usr/local/lib/libenchant-*.dylib')
LIBENCHANT = candidates[0] if candidates else None

# 2) Auto-find enchant dict folder (optional)
share_candidates = glob.glob('/opt/homebrew/share/enchant-2') + \
                   glob.glob('/opt/homebrew/share/enchant') + \
                   glob.glob('/usr/local/share/enchant') + \
                   glob.glob('/usr/share/enchant')
ENCHANT_SHARE = share_candidates[0] if share_candidates else None

print(f"Enchant library: {'Found' if LIBENCHANT else 'Not found'}")
print(f"Enchant config: {'Found' if ENCHANT_SHARE else 'Not found'}")

APP = ['main.py']
DATA_FILES = [
    'main.conf.json',
    'im-select',
]

# DON'T bundle enchant library to avoid GLib conflicts
# The app will use system enchant from Homebrew
# if LIBENCHANT:
#     DATA_FILES.append(LIBENCHANT)
#     print(f"Bundling enchant library: {LIBENCHANT}")
if LIBENCHANT:
    print(f"Found enchant library: {LIBENCHANT} (using system version)")

if ENCHANT_SHARE and os.path.exists(ENCHANT_SHARE + '/AppleSpell.config'):
    DATA_FILES.append(('share/enchant', [ENCHANT_SHARE + '/AppleSpell.config', ENCHANT_SHARE + '/enchant.ordering']))
    print(f"Bundling enchant config from: {ENCHANT_SHARE}")
else:
    print("Enchant config not found - app will work without spell-check fallback")

# Don't bundle enchant providers to avoid GLib conflicts
# The app will use system enchant providers from Homebrew
# enchant_providers = []
# for path in ['/opt/homebrew/lib/enchant-2', '/usr/local/lib/enchant-2']:
#     providers = glob.glob(path + '/*.dylib')
#     if providers:
#         enchant_providers = providers
#         break
# 
# if enchant_providers:
#     DATA_FILES.append(('lib/enchant-2', enchant_providers))

OPTIONS = {
    # App icon
    'iconfile': 'icon.icns',
    
    # Metadata visible in Finder "Get Info"
    'plist': {
        'CFBundleName': __app_name__,
        'CFBundleDisplayName': __app_name__,
        'CFBundleIdentifier': 'com.lanceloz.langswitcher',
        'CFBundleVersion': __version__,
        'CFBundleShortVersionString': __version__,
        'NSHumanReadableCopyright': f'© 2025 {__author__}',
        'LSUIElement': True,  # Makes it a menu bar app (no Dock icon)
        'LSMinimumSystemVersion': '10.13',
        'NSHighResolutionCapable': True,
    },
    
    # standalone bundles Python runtime by default
    # Note: Not bundling enchant to avoid GLib conflicts - use system version
    'resources': ['im-select'],
    'packages': ['detectors', 'switchers', 'ui', 'WebKit'],
    'includes': [
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'Quartz',
        'WebKit',
        'objc',
        'Foundation',
        'AppKit',
        'config',
        'version',
        'detectors',
        'detectors.language',
        'detectors.frustration',
        'switchers',
        'switchers.keyboard',
        'switchers.macos',
        'switchers.input_observer',
        'keyboard_events',
        'keyboard_access',
        'ui',
        'ui.menubar',
        'ui.settings',
        'ui.permissions_window',
        'ui.layout_overlay',
    ],
    'excludes': [
        'test', 'tkinter', 'unittest', 'pydoc', 'distutils'
    ],
    # Exclude glib libraries to prevent conflicts with system versions
    'dylib_excludes': [
        'libglib-2.0.0.dylib',
        'libgio-2.0.0.dylib',
        'libgobject-2.0.0.dylib',
        'libgthread-2.0.0.dylib',
        'libgmodule-2.0.0.dylib',
        'libintl.8.dylib',
        'libffi.8.dylib',
    ],
    
    # Use system enchant instead of bundled one to avoid GLib conflicts
    'frameworks': [],
}

setup(
    name=__app_name__,
    version=__version__,
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
