# Music to Mic

Play music from your browser (or any app) into a voice call, together with your mic, on Windows.
A simple alternative to Voicemeeter: one window, one Start button.

A quality-of-life project by **Mondcrest Automations**.

## What it does

- Captures the sound of **one app only** (e.g. Brave, Chrome, Spotify) using Windows per-app audio capture.
  Your call audio is never sent back, so callers don't hear an echo of themselves.
- Mixes it with your mic and sends both into a virtual cable. Your call app uses that cable as its mic.
- **Preview**: hear exactly what callers hear. While on, the app turns the music app's own speaker
  output down and boosts the capture to match, so you don't hear the music twice and callers hear no change.
- **Clarity**: an EQ that cuts boomy bass and lifts treble so music survives voice-call codecs better.
- Volume up to 300% (music) and 1000% (mic) with limiters, so loud doesn't mean distorted.
- Level meter showing what callers hear.

Works with any call app that lets you pick a microphone (WhatsApp Desktop, Discord, Zoom, Teams...).
Call apps still apply their own noise suppression, so music will never sound studio-perfect in a call.

## Requirements

- Windows 10 version 2004 or newer, or Windows 11
- Python 3.10+ ([python.org](https://www.python.org/downloads/))
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (free donationware driver, not included)
- Microsoft Edge (comes with Windows; used to show the app window)

## Install

1. Install VB-Cable: download the driver pack from [vb-audio.com/Cable](https://vb-audio.com/Cable/),
   right-click `VBCABLE_Setup_x64.exe` and run it as administrator, then restart.
2. After restarting, check **Settings > System > Sound**. The installer may have made the cable your
   default speaker and mic. Set them back to your real headset.
3. Download this repo, open a terminal in the folder and run:

   ```
   pip install -r requirements.txt
   ```

4. Double-click `music_to_mic.pyw` to open the app (or run `pythonw music_to_mic.pyw`).

## Use

1. Open the music app (e.g. your browser) first.
2. In Music to Mic, open **Devices** and check:
   - **Music from app**: your browser, e.g. `brave.exe`
   - **Your mic**: your real microphone
   - **Send to**: `CABLE Input (VB-Audio Virtual Cable)`
3. Press **Start**.
4. In your call app, set the microphone to **CABLE Output (VB-Audio Virtual Cable)**.
   The **Open settings** button opens the Windows volume mixer, where you can also set it per app.
5. Turn on **Preview**, play music, and set the two sliders until the level meter shows "good".
   Then turn Preview off.

To avoid echo, keep your call app's speaker on your headphones (never on CABLE Input),
and never pick CABLE Output as "Your mic" in Music to Mic.

## Troubleshooting

- **"is not running"**: open the music app before pressing Start. If you restart the browser, press Stop and Start.
- **Callers hear nothing**: check the call app's mic is CABLE Output and that the level meter moves.
- **Music sounds muffled in the call**: keep Clarity on, and turn off *Audio enhancements* for CABLE Output
  in Windows Sound settings. The rest is the call app's own processing.
- **Extra "CABLE In 16ch" device**: VB-Cable adds it. You can disable it in Control Panel > Sound > Playback.

## How it works

- `music_to_mic.pyw`: per-process loopback capture (`ActivateAudioInterfaceAsync` with
  `VAD\Process_Loopback`) via ctypes, mixing/EQ/limiting with numpy, audio I/O with sounddevice (WASAPI),
  and a small localhost-only web server (random token) for the window.
- `sessions.py`: reads and sets the music app's Windows audio-session volume for Preview.
- `ui.html`: the window, shown in an Edge app window.
- `make_icon.py`: regenerates `icon.ico` and `icon.svg`.

## License

MIT, Copyright (c) 2026 Mondcrest Automations. See [LICENSE](LICENSE).
VB-Audio Virtual Cable is a separate product by VB-Audio Software with its own licence.
