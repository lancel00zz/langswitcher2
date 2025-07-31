from setuptools import setup
import glob, os

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

# Add enchant files if available
if LIBENCHANT:
    DATA_FILES.append(LIBENCHANT)
    print(f"Bundling enchant library: {LIBENCHANT}")

if ENCHANT_SHARE and os.path.exists(ENCHANT_SHARE + '/AppleSpell.config'):
    DATA_FILES.append(('share/enchant', [ENCHANT_SHARE + '/AppleSpell.config', ENCHANT_SHARE + '/enchant.ordering']))
    print(f"Bundling enchant config from: {ENCHANT_SHARE}")
else:
    print("Enchant config not found - app will work without spell-check fallback")

# Try to find and bundle enchant providers
enchant_providers = []
for path in ['/opt/homebrew/lib/enchant-2', '/usr/local/lib/enchant-2']:
    providers = glob.glob(path + '/*.dylib')
    if providers:
        enchant_providers = providers
        break

if enchant_providers:
    DATA_FILES.append(('lib/enchant-2', enchant_providers))

OPTIONS = {
    # standalone bundles Python runtime by default
    'resources': ['im-select'] + ([LIBENCHANT] if LIBENCHANT else []),
    'includes': [
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'Quartz',
    ],
    'excludes': [
        'test', 'tkinter', 'unittest', 'pydoc', 'distutils'
    ],
    # Exclude glib libraries to prevent conflicts with system versions
    'dylib_excludes': [
        'libglib-2.0.0.dylib',
        'libgio-2.0.0.dylib',
        'libgobject-2.0.0.dylib',
        'libgthread-2.0.0.dylib'
    ],
}

setup(
    name='LangSwitcher',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
