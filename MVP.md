# MVP — EncDec (Stego Toolkit + Hub)

## Goal
Steganography and encryption toolkit for fun encrypting/decrypting of messages on laptop and phones: message or image hidden in image, audio and video, with real password encryption, desktop GUIs and exe, a phone web app, and a private login-protected hub (encrypted drops and live chat) for the user and specific friends.

## Users and context
The user and specific friends they are with. Windows laptop (conda env `stego`), Android/iPhone browsers, hub hosted on Render.

## Requirements (MUST)
- [x] Message in image/audio/video and image in audio/video, each with decoder; one folder per tool pair (verified earlier sessions)
- [x] Desktop app with progress bar and console log (`stego_app.py`, `dist/StegoTool.exe`)
- [x] Real encryption: optional password on every tool plus Text<->Cipher (AES-256-GCM), byte-compatible between desktop and phone (verified)
- [x] Works on phones via browser (`android_webapp/index.html`; needs https or file://)
- [x] Hub: per-user login, admin-created accounts, drops waiting for a recipient in any supported format, live encrypted chat (verified locally)
- [x] Conda env `stego`
- [ ] Hub deployed and working on Render (user does the push and deploy)

## Requirements (SHOULD / later)
- Persistent storage on Render (free tier wipes SQLite on restart)
- Video support in the hub/phone (desktop only today)
- Publish `StegoTool.exe` via GitHub Releases

## Out of scope
- Deployment actions by Claude (user pushes to GitHub and deploys on Render themselves)

## Constraints
- E2E: server must never see passphrases or plaintext
- Accounts created by admin only; no public signup
- Free-tier Render: ephemeral storage, sleeps when idle
- GitHub file limit 100 MB, so `dist/` is git-ignored
- Nothing committed/pushed/deployed by Claude without the user's go-ahead

## Acceptance criteria / how we know it is done
Round trips pass for every tool with and without password; hub tests pass; hub reachable on Render over https with two accounts exchanging a drop and chat messages. Specific acceptance tests beyond this: confirm with the user.

## Change requests log
| Date | Requested by | Change | Status |
|---|---|---|---|
| 2026-10-28 | user | Fix issues/enhance so it works on laptop and phones, with real encrypt/decrypt of messages | done |
| 2026-10-28 | user | Redesign: hosted, password-protected hub for specific people; image waiting to be decrypted; encrypt in any format; live chat; deploy to Render for testing | built, tested locally |
| 2026-10-28 | user | Decisions: end-to-end, admin-created accounts, ephemeral storage OK | done |
| 2026-10-28 | user | Project moved to Documents\GitHub\EncDec; user will push to GitHub and deploy on Render | repo prepared |
