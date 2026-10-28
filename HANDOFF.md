# HANDOFF — Cybersecurity

_Last updated: 2026-10-28 · by: backfill script (reconstructed; refresh on first real session)_

## Status in one paragraph
Current state per last recorded session: see 'Verified / Not verified' and B&A.md. Baseline before Claude work: Empty directory (2026-10-17).

## How to run / build / test
Hub: in `hub/` with env `stego`: `uvicorn app:app --port 8000`, open http://localhost:8000, user `admin`. Tools: see per-folder `gui.py`; exe `dist/StegoTool.exe`.

## Where things are
- Root: `C:\Users\Amir Rahman\Desktop\Knowledge Hub\Projects\Cybersecurity`
- Top level: `README.md`, `android_webapp/`, `assets/`, `combined_gui/`, `environment.yml`, `hub/`, `img_in_audio/`, `img_in_video/`, `msg_in_audio/`, `msg_in_image/`, `msg_in_video/`, `stego_app.py`
- Manifests: environment.yml
- Not a git repository (no version history).

## Decisions in force
- One folder per tool pair (user)
- Separate encoder/decoder exes (user)
- Hosted private hub with credentials (user idea, built)
- Do not deploy now (user)

## Known problems & mistakes to avoid
- WhatsApp photo picker recompresses images and wipes LSB data — send as Document/File (not a code bug)
- Android Chrome blocks blob: downloads from file:// pages — switched to data: URIs

## Verified / Not verified
**Not verified:**
- Hub in production; mobile on many devices

## Open questions
- Confirm the reconstructed MVP with the user.

## Next actions (ordered)
1. git init → GitHub → Render per hub/README.md when the user asks

## Read first
- `MVP.md`, `B&A.md`
- Memory record: `Claude Vault\Memory\Log - Software and Data Projects.md` (see the project record)
- `Claude Vault\Agent Harness\README.md` (skills), `Claude Vault\Memory\README.md`
