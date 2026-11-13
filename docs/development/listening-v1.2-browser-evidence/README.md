# Listening V1.2 browser evidence

Captured with a real headless Chrome session against a live Vite frontend, Uvicorn/FastAPI, and a temporary migrated SQLite database. The runner leaves the formal local SQLite untouched.

The entry screenshots cover Premium Academic and Noir & Champagne at 1440 × 1000 and 390 × 844. Result screenshots show post-submit feedback. The browser journey also verified 63.72-second WAV metadata and playback, audio-load error presentation, local draft restoration after refresh, 3/5 result feedback, answer explanations, audio seek to the question's 9.24-second anchor, keyboard focus visibility, Reading route navigation, no horizontal overflow, and no console errors.

The isolated live API run returned lesson `200`, create `201`, submit `200`, same-answer retry `200`, and history `200`; five version-pinned Attempts were persisted. See [HTTP evidence](http-evidence.json), [browser network evidence](browser-http-evidence.json), and [SQLite evidence](persistence-evidence.json).

## Captures

| Theme | Desktop | Mobile |
| --- | --- | --- |
| Premium Academic | [1440 × 1000](listening-desktop-premium-academic.png) | [390 × 844](listening-mobile-premium-academic.png) |
| Noir & Champagne | [1440 × 1000](listening-desktop-noir-champagne.png) | [390 × 844](listening-mobile-noir-champagne.png) |

Results: [Premium Academic](listening-results-premium-academic.png) · [Noir & Champagne](listening-results-noir-champagne.png). A Reading route smoke capture is [here](reading-regression.png). The existing Matching Headings Chrome journey passed 14 scenarios and saved its 27 screenshots plus request/persistence evidence under [`reading-regression/`](reading-regression/).
