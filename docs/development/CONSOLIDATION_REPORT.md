# VerbaTrail Consolidation Report

- Date: 2026-11-10
- New project: `D:\Projects\VerbaTrail`
- Working branch: `feat/verbatrail-consolidation` (local only)
- Base: accepted IELTS branch commit `d1cab43438aeea1aafd9ddeced775027c65946f1`
- Remote: `https://github.com/KaoruMiyagawa/UnlearnLoop.git` (unchanged; no push or merge)
- Source backup: `D:\Temp\VerbaTrail-consolidation-backup-20261110`

## Repository method and history

The five source folders were not independent repositories. `UnlearnLoop-argon`, `UnlearnLoop-codex`, `UnlearnLoop-ielts`, and `UnlearnLoop-integration` were linked worktrees of `D:\Projects\UnlearnLoop`. A further linked worktree, `D:\Temp\unlearnloop-main-docs-ielts1`, existed outside the supplied five paths.

A `git clone --no-hardlinks` from the common repository created a standalone `.git` directory in VerbaTrail. Its `origin` was reset to the existing GitHub URL and fetched successfully. The base IELTS branch and all remote history are retained; consolidation work is on a new local branch. Source linked-worktree `.git` pointers were not altered.

A complete `git bundle --all` was verified at `D:\Temp\VerbaTrail-consolidation-backup-20261110\unlearnloop-all-refs.bundle`. The original source repository, all five source folders and the extra temporary worktree remain untouched.

## Source-by-source mapping

| Source | Valuable material and destination | Git / working-tree disposition |
|---|---|---|
| `D:\Projects\UnlearnLoop` | Stage 1–5 foundations, architecture, shared object database and local `main` lineage remain in the cloned Git history. | Source `main` was locally ahead 3 / behind 1 relative to its then-tracked remote; both branch tips and all refs are in the bundle. The source repo is unmodified. |
| `D:\Projects\UnlearnLoop-argon` | `docs/design/focus-redesign` and `docs/design/verbatrail-ielts` copied under `docs/design/archived/`; Focus, Oxford, Nordic and Nocturne prototypes are labeled historical/unselected. | `feat/stage5-visual` history is preserved as a remote branch. Untracked design documents remain untouched in source. |
| `D:\Projects\UnlearnLoop-codex` | Stage 5 API Client implementation and tests already occur in the shared Git history inherited by the IELTS base. | `feat/stage5-api-client` is preserved as a remote branch; source was clean and unchanged. |
| `D:\Projects\UnlearnLoop-ielts` | IELTS-1 backend/frontend, Alembic 0004, bilingual docs, browser evidence, uncommitted theme UI, `ThemeProvider.tsx`, and visual screenshots/report are in VerbaTrail. | Tracked diff was applied as a patch; untracked files were copied. Source is untouched. IELTS-0 baseline and IELTS-1 history remain in Git. |
| `D:\Projects\UnlearnLoop-integration` | Stage 5C implementation is already in IELTS ancestry. Its five untracked proposal/audit documents are archived under `docs/archive/integration-proposals/` with a note that the implementation predated IELTS-1. | `feat/stage5c-integration` history is preserved. The 266,240-byte local SQLite file was copied without migration to `backend/unlearnloop.db`; a byte-identical backup exists (SHA-256 `BC4656AA2BC624F0A257254BA25597DB3031126FDFCBE79E5F3BB0CB607793E0`). Source is untouched. |
| `D:\Temp\unlearnloop-main-docs-ielts1` (extra discovered worktree) | Its documentation commit is in Git history and the remote main lineage. | Source worktree remains untouched. |

The Argon design README and dual-theme handoff were adjusted only in the new copy to remove references to old absolute working paths and clarify archive/current status.

## Data and secrets

No real `.env` or API key file was found in the five project roots; only tracked `.env.example` templates exist. The Integration SQLite file passed `PRAGMA integrity_check`, was at migration revision `0002_stage3_model_calls`, and contains one learning session but no attempts. It was copied byte-for-byte and backed up before any new-root startup or migration. Automated tests are configured with temporary SQLite files. The copied DB is ignored by Git.

The old source folders have not been deleted. Keep the backup bundle, working-tree patch, untracked snapshots and database backup until the owner completes final cleanup.

## Product-name migration

README pages, browser title, FastAPI title/default app name, Python distribution name, npm package name, environment examples, roadmap headings, and launcher are now branded VerbaTrail. Historical module/database identifiers such as `unlearnloop.db`, `app` package paths, old commit subjects, and the unchanged GitHub URL remain for compatibility and traceability. The launcher no longer depends on a Python environment in an old worktree or a hard-coded `D:\Temp` venv.

## Validation results

- Backend: `80 passed` on the final complete run. One initial run had a timing-sensitive failure in the concurrent review-answer test; that test passed when rerun alone, and the subsequent full suite passed. Starlette emitted one deprecation warning about its `httpx` TestClient integration.
- Frontend: all `40` Node tests passed.
- TypeScript: `npm run typecheck` passed.
- Production bundle: `npm run build` passed using Vite `6.4.6`.
- Dependency audit: `npm audit --audit-level=moderate` found `0 vulnerabilities` after updating Vite within the Vite 6 major line. `@vitejs/plugin-react` 4 declares compatibility with Vite 6.
- Formatting: `git diff --check` passed (Git reported only configured LF/CRLF normalization notices).
- Startup: the backend started at `127.0.0.1:19241` against the fresh temporary database `D:\Temp\verbatrail-consolidation-smoke-20261110.sqlite`; Vite started at `127.0.0.1:19242`. The browser loaded the VerbaTrail home page and both Reading task variants through the backend API.
- Browser evidence: Headless Chrome smoke results and screenshots are under `docs/development/consolidation-browser-evidence/`. It verified Premium/Noir switching and persistence, Academic session restoration, and a distinct General Training Reading task. At 390 CSS pixels, both themes' home and reading pages reported `documentWidth=390`; the reading passage was visible. This smoke pass did not submit an answer or execute diagnosis in the browser. The service used `FakeModelProvider` with remote calls disabled; it is not evidence of real AI personalization.
- Database preservation: the copied ignored local database remains at `backend/unlearnloop.db`, was not migrated, and matches the external backup. Automated tests and browser startup used temporary databases.

The one concurrency-test flake should be watched in CI, although it passed in the final full suite. The smoke pass exercises actual browser navigation but is not a substitute for the archived IELTS-1 end-to-end browser acceptance evidence.

## Next integration boundary

This local consolidation branch is not published. The `origin` remains `https://github.com/KaoruMiyagawa/UnlearnLoop.git`; local `main` tracks `origin/main`, and the source repository's divergent `main` tip is preserved locally as `archive/source-main-80df`. IELTS and Stage 3/4/5 feature branches remain available in this clone. The consolidation commit is local only: no push, remote merge, or old-directory deletion has occurred. Do not treat this commit as production readiness or evidence that a real model provider gives valid personalized diagnoses.
