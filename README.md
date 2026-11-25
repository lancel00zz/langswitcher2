# LangSwitcher 🇺🇸 ↔ 🇨🇦

A macOS menu bar app that switches between **U.S.** and **French Canadian–CSA** keyboard layouts as you type.

**[Download the latest release](https://github.com/lancel00zz/langswitcher2/releases/latest)**

## A simple correction

Typed `/` but wanted `é`?

1. Press **Backspace** to delete `/`. LangSwitcher immediately changes the keyboard layout.
2. Press the same physical key again to get **`é`**.

Only supported keys that differ between the two layouts trigger this Backspace behaviour. The correction expires after **2.5 seconds of inactivity**.

## Features

- Automatic English/French language detection.
- Backspace corrections, including when you have already typed more characters.
- A brief flag showing the selected layout.
- Adjustable flag size, opacity, and screen position, with a live preview.
- Menu bar controls to pause switching or hide the flag.
- Built-in keyboard permission checks and recovery instructions.

## Installation

Prebuilt downloads are for **Apple silicon Macs**.

1. Download the release ZIP, extract it, and move **LangSwitcher.app** into **Applications**.
2. In **System Settings → Keyboard**, enable **U.S.** and **Canadian–CSA** input sources.
3. Launch LangSwitcher and follow its **Keyboard Access…** guide.

Quit the previous copy before updating.

Current releases are not Apple-notarized. If macOS blocks the app, see [Apple’s guidance](https://support.apple.com/en-us/102445).

## Privacy

Language detection runs locally. The debug log at `~/langswitcher.log` can contain typed words—review and redact it before sharing.

## Build from source

With Homebrew installed:

```bash
brew install python@3.13 enchant
git clone https://github.com/lancel00zz/langswitcher2.git
cd langswitcher2
bash rebuild_app.sh
```

## Feedback

[Report a bug or suggest an improvement](https://github.com/lancel00zz/langswitcher2/issues). Include your macOS version, starting layout, and the keys you pressed.
