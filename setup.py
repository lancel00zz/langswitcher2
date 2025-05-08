from setuptools import setup
import glob, os

# ———————————————————————————————
# 1) Auto-find libenchant dylib
candidates = glob.glob('/opt/homebrew/lib/libenchant-*.dylib') + \
             glob.glob('/usr/local/lib/libenchant-*.dylib')
if not candidates:
    raise RuntimeError("libenchant dylib not found in /opt/homebrew/lib or /usr/local/lib")
LIBENCHANT = candidates[0]

# 2) Auto-find enchant dict folder
share_candidates = glob.glob('/opt/homebrew/share/enchant') + \
                   glob.glob('/usr/local/share/enchant') + \
                   glob.glob('/usr/share/enchant')
if not share_candidates:
    raise RuntimeError("Enchant dict folder not found in Homebrew or system paths")
ENCHANT_SHARE = share_candidates[0]

APP = ['main95.py']
DATA_FILES = [
    'main95.conf.json',
    'im-select',
    LIBENCHANT,
    # bundle entire enchant share folder
    (ENCHANT_SHARE, 'share/enchant'),
]

OPTIONS = {
    # standalone bundles Python runtime by default
    'resources': ['im-select', LIBENCHANT, ENCHANT_SHARE],
    'includes': [
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'Quartz',
    ],
    'excludes': [
        'test', 'tkinter', 'unittest', 'pydoc', 'distutils'
    ],
}

setup(
    name='LangSwitcherPza2.0',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
