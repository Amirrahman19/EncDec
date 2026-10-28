# B&A — Before and After — EncDec

Append-only. Each entry: what the state was BEFORE, what changed, WHY, HOW, and how it is in line with MVP.md.

## Baseline (reconstructed)
- Empty directory on 2026-10-17; toolkit built over 2026-10-17 to 2026-10-27 (stego tools, GUIs, exe, Android web app, first hub).

## Entries

### 2026-10-28 — Encryption, hub, repo prep
- **Before:** Stego tools hid data but did not encrypt; no hosted multi-user option; folder not laid out for GitHub/Render.
- **Change (what/how):** Added AES-256-GCM (PBKDF2) password encryption and Text<->Cipher to `stego_app.py` and `android_webapp/index.html` (byte-compatible); fixed the web alpha-premultiply bug, rAF hang, slow bit embedding, 24-bit WAV and unfriendly decode errors; rebuilt the exe. Built `hub/` (FastAPI, scrypt logins, admin-created users, E2E drops, encrypted live chat, CSP/CSRF/throttling). After the move to EncDec: root `.gitignore`, `render.yaml` moved to repo root (rootDir hub), hub/README updated.
- **Why:** User wanted real encryption and a private hosted tool for specific friends, deployable on Render.
- **MVP alignment:** Encryption, phone and hub MUSTs; deployment left to the user per constraint.
- **Files:** stego_app.py, android_webapp/, hub/*, render.yaml, .gitignore, README.md, environment.yml
- **Verified:** Python/JS encryption interop; core round trips; hub API tests (auth, CSRF, isolation, lockout); live websocket relay and origin/anon rejection; browser end-to-end (send, reveal, wrong passphrase, chat); hub starts from the EncDec path.
- **Not verified:** Render deployment, real phones, exe after the move, hub behind Render's proxy.
