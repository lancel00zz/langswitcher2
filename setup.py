from setuptools import setup
import glob, os

# — Find the libenchant dylib automatically —
candidates = glob.glob('/opt/homebrew/lib/libenchant-*.dylib')
if not candidates:
    raise RuntimeError("Could not find libenchant library in /opt/homebrew/lib")
LIBENCHANT = candidates[0]

APP = ['main95.py']
DATA_FILES = [
    'main95.conf.json',
    'im-select',
    LIBENCHANT,
]
OPTIONS = {
    # fully standalone (default bundles Python runtime)
    'resources': ['im-select', LIBENCHANT],

    # include required backends & frameworks
    'includes': [
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'Quartz',
    ],
    'excludes': [
        'test',
        'tkinter',
        'unittest',
        'pydoc',
        'distutils',
    ],
}

setup(
    name='LangSwitcherPza2.0',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
