# Learn V1.2 — Listening acceptance

Updated: 2026-11-13

## Delivered scope

Listening is implemented as one limited IELTS-style study-arrangements exercise at `/learn/listening`. It contains a 64-second original English script synthesized offline to a playable WAV, five multiple-choice questions, server-side exact-choice scoring, per-item explanations, and audio time anchors. Correct answers and explanations are omitted from the pre-submit DTO and exposed only after completion.

The exercise uses shared `LearningSession`, `Question`, and `Attempt` records. Session and answer snapshots pin `listening-study-group-v1` and `listening-exact-choice-v1`, the audio URL, item time range, and rights/source statement. No Listening-specific learner profile, review system, evidence table, or migration was added. The attempt result is a result for this session only; it does not create transfer/retention verification or an IELTS Band score.

Audio: [`study-group.wav`](../../frontend/public/audio/listening/study-group.wav). The script is original VerbaTrail writing; the WAV was synthesized locally with Piper 1.8.0 using `en_US-joe-medium`. The pinned model card identifies CC0 training data and an `rdh` CC0 base; Piper's official voice-chain reuse guidance lists this voice as CC0. No IELTS test audio or licensed external recording was used. The browser-reported duration and license references are in [audio provenance](../../frontend/public/audio/listening/README.md).

## Verification

- Backend: `167 passed` (full `pytest` suite; one existing Starlette/httpx deprecation warning).
- Frontend: `48 passed` (`node --test tests/*.test.mjs`).
- TypeScript: `npm run typecheck` passed.
- Production build: `npm run build` passed.
- Alembic: one head, `0007_evidence_validity_events`; no database migration was required.
- Isolated SQLite + live Uvicorn HTTP: lesson 200, session create 201, submit 200, same-payload retry 200, history 200; five Attempts persisted with both versions and audio provenance. The formal SQLite was not used.
- Headless Chrome: playable audio (63.72 sec), playback/pause, draft restore after reload, submit/results, correct and incorrect feedback, time-anchor seek to 9.55 sec, keyboard-visible focus, audio error presentation, no console errors, and no horizontal overflow at 1440×1000 and 390×844 in both themes.
- Reading browser regression: existing Matching Headings journey passed 14 browser scenarios, produced 27 captures, and exercised 604 browser API requests on isolated SQLite. Captures are stored in [`reading-regression/`](listening-v1.2-browser-evidence/reading-regression/).
- `git diff --check`: passed.

## Browser captures

Desktop and mobile captures show the exercise entry in both themes:

| Theme | Desktop 1440 × 1000 | Mobile 390 × 844 |
| --- | --- | --- |
| Premium Academic | ![Desktop Premium Academic](listening-desktop-premium-academic.png) | ![Mobile Premium Academic](listening-mobile-premium-academic.png) |
| Noir & Champagne | ![Desktop Noir & Champagne](listening-desktop-noir-champagne.png) | ![Mobile Noir & Champagne](listening-mobile-noir-champagne.png) |

Post-submit captures: [Premium Academic](listening-results-premium-academic.png) · [Noir & Champagne](listening-results-noir-champagne.png) · Reading regression: [browser capture](reading-regression.png).

Machine-readable evidence: [HTTP status and retry](http-evidence.json), [browser API requests](browser-http-evidence.json), and [isolated persistence](persistence-evidence.json).

## Limits

This is one authored practice exercise, not a complete IELTS Listening paper or official IELTS product. The spoken voice is synthetic. It provides rule-based answer correctness and authored explanations, not speech recognition or an AI estimate. Current ability remains unassessed, and one exercise is not evidence of independent transfer or delayed retention.
