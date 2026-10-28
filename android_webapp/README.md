# Stego Toolkit — Android (offline, no Play Store, no APK)

`index.html` is a single, self-contained web app (no external scripts, no
network calls) that does everything on-device in the browser:

- Message ↔ Image (PNG)
- Message ↔ Audio (WAV)
- Image ↔ Audio (WAV)

Not included on mobile: video tools, and non-WAV audio auto-conversion
(no ffmpeg available in a browser without a large extra download) — the
desktop app still covers those.

It is **cross-compatible** with the desktop Python tool: a file encoded on
your PC decodes correctly in this webapp and vice versa (verified both
directions, byte-for-byte, during development).

## Install (no Play Store, fully offline after transfer)

1. Copy `index.html` to your phone any way you like — USB cable, email to
   yourself, Bluetooth, Google Drive/Nextcloud sync, etc. A file manager
   app on the phone is enough to receive it.
2. In your phone's file manager, tap the file and choose **"Open with" →
   Chrome** (or just open it in Chrome directly if your browser is the
   default handler for `.html` files).
3. In Chrome, tap the **⋮ menu → "Add to Home screen"**. This creates a
   home-screen icon that opens the app full-screen, like an installed app.
4. From then on, everything runs locally in the page — no internet needed,
   nothing is uploaded anywhere.

This is not a literal `.apk` (building one needs the Android SDK + JDK
toolchain, ~1-2GB, not installed here), but functions the same way day to
day: tap an icon, use the app, fully offline.

## Encryption

Includes a **Text <-> Cipher** tool (encrypt/decrypt a message, copy or Share
it into any chat) and an optional password on every file tool. It uses the
browser's WebCrypto, which only works in a secure context: open the file
directly from phone storage (`file://`) or serve it over **https**. Plain
`http://<laptop-ip>:port` will not work. Works on iPhone Safari too (open via
https hosting), same as Android Chrome.

## Known pitfalls

- **Sending an encoded image through WhatsApp/Messenger/Instagram as a
  normal "Photo" destroys the hidden message.** Those apps always
  recompress photos sent that way (JPEG re-encode + resize), which wipes
  every LSB bit — this is the app recompressing it, not a bug in the tool.
  Always send/receive the PNG as a **Document / File** attachment instead
  (WhatsApp: 📎 → Document, not Gallery), which transmits the exact
  original bytes.
- Downloads use `data:` URIs rather than `blob:` object URLs. Opening this
  page via `file://` gives it an opaque/null origin, and Android Chrome
  blocks `blob:` URL downloads from that origin (shows an error like "URL
  needs to be http or https"). `data:` URIs don't have that restriction.
  If a download still doesn't start on some device/browser combo,
  long-press the resulting image/audio and use "Download"/"Save" from the
  context menu — that path works even when the button doesn't.
