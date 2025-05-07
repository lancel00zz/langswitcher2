from setuptools import setup

APP = ['main95.py']
DATA_FILES = [
    'main95.conf.json',
    'im-select',
]
OPTIONS = {
    # fully standalone (bundles Python runtime by default)
    'resources': ['im-select'],

    # force-include the macOS backends for both keyboard and mouse,
    # plus the Quartz bridge
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