# Stego Hub

A private, login-protected web app for a closed group. Works in any phone or
laptop browser.

- **Inbox / Send:** encrypt for a specific person in a format you choose
  (encrypted text, message hidden in an image, message hidden in WAV audio,
  image hidden in audio, or any file). The recipient logs in, sees it waiting,
  and reveals it with the passphrase.
- **Live chat:** rooms with end-to-end encrypted messages.
- **Admin:** only an admin creates users (no public signup).

## Security model

- **End-to-end:** all encryption, decryption and steganography run in the
  browser (AES-256-GCM, PBKDF2-SHA256 200k). The server only stores and relays
  ciphertext; it never sees passphrases or plaintext. The passphrase is
  separate from the login password: share it with your people outside the hub.
- Logins: scrypt-hashed passwords, httpOnly SameSite=Strict session cookie,
  login throttling (6 failures / 10 min), CSRF header, strict CSP, websocket
  origin check. Chat sender names are set by the server, not encrypted.
- Server metadata is visible to the host: who sent to whom, when, file size,
  type. Content is not.
- Free-tier Render uses ephemeral storage: users, inbox and chat history reset
  on restart/redeploy. Drops expire after 14 days; inbox cap 100; upload 25 MB.
- WebCrypto needs https (Render provides it) or `localhost`.

## Run locally

```
conda activate stego
pip install -r requirements.txt
set ADMIN_PASSWORD=choose-a-password      (PowerShell: $env:ADMIN_PASSWORD="...")
uvicorn app:app --port 8000
```

Open http://localhost:8000, log in as `admin`, add users on the Admin tab.
If `ADMIN_PASSWORD` is unset on an empty database, a random admin password is
printed in the server log.

## Deploy to Render

1. Push this repo to GitHub (private is fine). `render.yaml` is at the repo root.
2. Render dashboard -> New -> Blueprint -> pick the repo (it reads
   `render.yaml`; it builds from `hub/`).
3. Set `ADMIN_PASSWORD` when prompted. Deploy, then open the URL, log in as
   `admin`, create accounts for your people and give each their password.
4. Free instances sleep after ~15 min idle; the first request takes ~30 s.
