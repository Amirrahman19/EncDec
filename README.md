# Steganography Toolkit

LSB-based steganography tools. Each tool lives in its own standalone folder with
an encoder+decoder module (`stego.py`) and its own GUI (`gui.py`). A combined GUI
ties all of them into one app with a tab per tool.

## Folders

- `msg_in_image/` — hide/extract a text message in a PNG/BMP/JPEG image.
- `msg_in_audio/` — hide/extract a text message in a WAV file.
- `img_in_audio/` — hide/extract an entire image inside a WAV file.
- `msg_in_video/` — hide/extract a text message in a video.
- `img_in_video/` — hide/extract an entire image inside a video.
- `combined_gui/` — one Tkinter app with all five tools as tabs (loads each
  folder's `stego.py` directly, so the per-tool folders remain independent).

Encode output is always forced into a lossless carrier format, regardless of
what extension you type/reuse for the output path:

- Image encode output → always `.png` (any lossy save, e.g. reusing a `.jpg`
  path in place, would silently destroy the embedded bits).
- Audio encode output → always `.wav` (PCM).
- Video encode output → always `.avi` (FFV1 lossless).

Source files, however, can be **any format**: image tools accept
jpg/bmp/gif/tiff/webp/png via Pillow; audio and video tools accept any
format ffmpeg can read (mp3, m4a, flac, mp4, mov, mkv, webm, ...) — a
non-WAV/AVI source is automatically transcoded to the required lossless
format before embedding, using a bundled ffmpeg binary
(`imageio-ffmpeg`), with the conversion step shown in the console log.

## Encryption (desktop app and phone web app)

- **Text <-> Cipher** tool: type a message + password, get an encrypted text
  blob you can paste into any chat app; the other side pastes it back in with
  the same password. No carrier file needed.
- Every file tool also has an optional **Password** field: the hidden payload
  is encrypted before being embedded, so even someone who finds the hidden
  data can't read it. Leave it empty for the old plain behaviour.
- AES-256-GCM, key from PBKDF2-HMAC-SHA256 (200k iterations), random salt and
  nonce. Wrong password or tampering is detected. Desktop and phone are
  byte-compatible (verified both directions). There is no password recovery.

## Standalone executable

`stego_app.py` (root level) is a single self-contained GUI app covering all
five encode **and** decode operations, with an ENCODE / DECODE tab at the
top and a tool dropdown underneath each, a progress bar and a live console
log pane — styled as a dark hacker-terminal theme (neon green/cyan,
monospace, custom padlock icon). Built `--windowed` (no terminal window);
logs also get appended to `stego_tool.log` next to the exe.

Prebuilt executable: `dist/StegoTool.exe`

Rebuild with PyInstaller (from the `stego` conda env) — the ffmpeg binary
and icon must be explicitly bundled via `--add-binary`/`--add-data`, and
Pillow must be the **pip**-installed wheel (not conda's) since conda's
build splits its DLLs into a location PyInstaller's analyzer won't find:

```
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
# use that path below as <ffmpeg_exe>

pyinstaller --noconfirm --onefile --windowed --name StegoTool --icon "assets\icon.ico" --add-binary "<ffmpeg_exe>;imageio_ffmpeg/binaries" --add-data "assets\icon.ico;assets" stego_app.py
```

## Environment

Conda env `stego` (Python 3.11, pip-installed Pillow, NumPy,
opencv-python-headless, imageio-ffmpeg, pyinstaller). See `environment.yml`.

```
conda activate stego
python stego_app.py               # combined encoder + decoder GUI
python combined_gui/app.py        # original all-in-one GUI (per-tool folders)
python msg_in_image/gui.py        # or run any tool standalone
```

## Mobile (Android, offline, no Play Store)

`android_webapp/index.html` is a single self-contained web app (same cyber
theme, zero network dependencies) covering Message↔Image, Message↔Audio and
Image↔Audio. Transfer it to a phone, open in Chrome, and use "Add to Home
screen" — see `android_webapp/README.md` for details. It's cross-compatible
with the desktop tool (files encode/decode correctly in both directions).

## How it works

Each payload is prefixed with a 4-byte big-endian length header, then written
one bit per LSB of each image pixel channel / audio sample / video pixel
channel across all frames.
