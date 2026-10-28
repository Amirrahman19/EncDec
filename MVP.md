# MVP — Cybersecurity

> Backfilled 2026-10-28 (curated from Claude Vault Memory logs + live files). Edit freely; log later changes below. Items marked _(reconstructed)_ come from past sessions, not from a fresh interview.

## Goal
Steganography toolkit for fun encrypting/decrypting of messages on laptop and phones: message/image in image, audio and video, with encoder/decoder GUIs, executables, a mobile web app, and a password-protected hub for specific friends.

## Users and context
The user and specific friends.

## Requirements (MUST) _(reconstructed — tick only when verified)_
- [ ] Message in image/audio/video and image in audio/video, each with decoder, one folder per tool pair
- [ ] Separate encoder and decoder exes with progress bar and console logging
- [ ] Works on phones (browser app)
- [ ] Hub: per-user login, admin, images waiting to be decrypted
- [ ] Conda env `stego`

## Requirements (SHOULD / later)
- Deploy hub to Render when the user is ready

## Out of scope
- Deployment now (user: "Not now")

## Constraints
- Nothing committed/pushed/deployed without the user's go-ahead
- Set ADMIN_PASSWORD or read the random one from the server log

## Acceptance criteria
- A new model can run the project from HANDOFF.md and each MUST above can be demonstrated. _(Specific acceptance tests: unknown — confirm with the user.)_

## Change requests log
| Date | Requested by | Change | Status |
|---|---|---|---|
| 2026-10-28 | system | Backfilled MVP from history | done |
