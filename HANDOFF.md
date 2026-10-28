# HANDOFF — EncDec

_Last updated: 2026-10-28 (project moved to EncDec; push-ready, not yet pushed or deployed)_

## Status in one paragraph
Project lives at `C:\Users\Amir Rahman\Documents\GitHub\EncDec` (git repo, branch `main`, no commits yet). The desktop app has AES-256-GCM password encryption plus a Text<->Cipher tool; the phone web app matches it byte-for-byte; `hub/` is a login-protected end-to-end hub (FastAPI) tested locally. The repo is push-ready: root `.gitignore` (excludes `dist/` and the DB) and `render.yaml` at the root (rootDir hub). The user will push to GitHub and deploy on Render themselves.

## How to run / build / test
```
conda env: stego  (C:\Users\Amir Rahman\anaconda3\envs\stego\python.exe)
Desktop:  python stego_app.py
Exe:      see README.md (PyInstaller command); output dist/StegoTool.exe (git-ignored)
Hub:      cd hub; pip install -r requirements.txt; set ADMIN_PASSWORD; uvicorn app:app --port 8000
          open http://localhost:8000, log in as admin, add users in the Admin tab
Render:   New > Blueprint > pick repo (render.yaml at root); set ADMIN_PASSWORD
```

## Where things are
| Path | What |
|---|---|
| `stego_app.py` | Desktop GUI + all encode/decode + encryption (single file, PyInstaller-ready) |
| `android_webapp/` | Single-file offline phone web app (needs file:// or https for encryption) |
| `hub/app.py` | FastAPI server: auth, admin, drops, websocket chat relay (SQLite) |
| `hub/static/` | `stego.js` (stego + crypto, shared with phone app), `app.js` (UI), css/html |
| `render.yaml`, `.gitignore` | Deploy blueprint and ignores (repo root) |
| `msg_in_*`, `img_in_*`, `combined_gui/` | Older per-tool folders; no encryption, kept as-is |

## Decisions in force (and why)
- End-to-end: all crypto in the browser; server stores ciphertext only (user choice)
- Accounts admin-created, no signup (user choice)
- Ephemeral SQLite on Render free tier is acceptable for testing (user choice)
- Encrypted blob format `SGE1 | salt16 | nonce12 | ct+tag`, PBKDF2-SHA256 200k, AES-256-GCM; shared by Python and JS
- `dist/` git-ignored: exe is ~246 MB, over GitHub's 100 MB limit

## Known problems / mistakes to avoid
- WhatsApp "Photo" sending recompresses images and destroys hidden data: send as Document/File
- WebCrypto needs a secure context: https, localhost or file://; plain http on a LAN IP fails
- requestAnimationFrame never fires in background tabs: use setTimeout (already fixed)
- Canvas premultiplied alpha corrupts LSBs: composite on opaque white first (already fixed)
- The SessionStart hook can overwrite MVP/HANDOFF/B&A with stubs if they look unfilled: check before editing
- Old per-tool folders and `combined_gui/` do not support passwords

## Not verified
- Hub on Render/https and on real phones; websockets behind Render's proxy
- Exe not re-run after the folder move
- Video in hub/phone (not supported)

## Next actions (ordered)
1. User: commit and push to GitHub; Render > New > Blueprint; set ADMIN_PASSWORD
2. After deploy: create users in the Admin tab; test drops and chat from two phones over https
3. Optional: persistent storage, GitHub Release for the exe

## Read first
- MVP.md, B&A.md, hub/README.md
