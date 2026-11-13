# IELTS-2B.1 Phase 4 — Matching Headings Transfer & Delayed Retention

> Phase 6 content review found incorrect or overly narrow answer headings in the original transfer/review content version 1. The Phase 4 HTTP run established the mechanics against that answer key; it did not establish editorial correctness. Phase 6 publishes corrected version 2 content and prevents new transfer or retention results from the affected version 1 assignments. See [the final acceptance report](IELTS_2B1_FINAL_ACCEPTANCE.md).

**Date:** 2026-11-11
**Branch:** `feat/ielts-2b-reading-question-groups`
**HEAD at verification:** `ce5f97148685c6856d93acb5e141ff774a6144c3`
**Result:** **PASS for the scoped first delayed review cycle**, with the limitations below.

Phase 4 adds protocol-checked Matching Headings transfer and review tasks to the existing LearningSession / Question / Attempt / KnowledgeState / ReviewItem flow. It does not add a parallel learning engine, React screens, or other Reading question types.

## Implemented

- Added Academic and General Training transfer and delayed-review content for both supported diagnosis targets (`main_idea_vs_detail`, `surface_keyword_matching`). The eight authored groups use distinct original passages, stable IDs, immutable content/rule versions, and explicit authorship, copyright, target, and independence provenance metadata.
- Added role and target validation for transfer and review content. Dispatch checks the triggering attempt's protocol and version, exam variant, current supported diagnosis, completed successful targeted practice, exact question role, versioned task map, and reviewed independence provenance. It excludes prior and currently assigned question groups/passages for that learner/topic. Unsupported or exhausted pools return an explicit unavailable response and do not promote state.
- Transfer and review assignments pin a ReadingGroupVersion. ReviewItem now stores its triggering Attempt and assigned group version. Migration `0006_matching_headings_review_provenance` adds nullable, backward-compatible foreign keys; `0005 → 0006` preservation is tested.
- Transfer uses the existing structured group evaluator and saves an Attempt with item evaluations and version snapshots. A full 3/3 pass alone advances Matching Headings to `transfer_verified`; a partial/failed transfer remains `needs_practice`. Neither path maps Matching Headings transfer to `stable`.
- A passing transfer schedules an idempotent ReviewItem. Review start and completion are rejected before due time. A due, independent review Attempt sets that ReviewItem's `retention_verified` only on a full pass; a failure stores its Attempt/evaluation, clears that item's verification, and moves current knowledge back to `needs_practice` without deleting historic records. A successful review does not mark knowledge `stable`.
- The TFNG migration guard now permits only its existing protocol; Python string-answer behavior remains on its existing path.

## Reproducible real HTTP evidence

The Uvicorn acceptance script starts a real loopback HTTP server against a temporary SQLite database upgraded to Alembic head. Its injected clock advances review time without changing the operating-system clock. No real model endpoint is called; execution mode is `rules`, with the FakeModelProvider configured for this isolated fixture. The output includes 104 HTTP request/response records, SQLite state snapshots, pinned/catalog versions, and an answer-key exposure check:

- [Uvicorn request/response and SQLite evidence](ielts-2b1-phase4-api-evidence/http-and-sqlite.json)
- [Repeatable HTTP acceptance runner](../../backend/scripts/verify_matching_headings_transfer_review_http.py)

The evidence reports `private_answer_material_exposed_by_api: false`. It intentionally does not include private answer keys or diagnostic mappings.

| Scenario | Observed result |
|---|---|
| A — Academic, main-idea/detail | Initial Attempt `att_8ddb794caab34f01` created DiagnosticCase `diag_73104a37c9964ade` with two competing hypotheses. The probe updated them to supported/lowered; practice Attempt `att_28a15bddcef84407` passed. Transfer used pinned group `rg_7cdd91685f6e669738affb2c70ee9b6b` and Attempt `att_cd74116386914edc` passed 3/3. After the catalog was advanced to `rg_07e194646a681a13fb9dd5c0872bb021`, the old assignment restored at its pinned version. ReviewItem `rev_698cb53a9600409a` used pinned group `rg_5256e1cc13448f475ace7912b679945a`; after advancing the catalog to `rg_1fadd42c347d5aa9e2ae621eb8590335`, due review Attempt `att_694af53ea966482a` passed and the item became retention-verified. |
| B — Academic, surface keyword | Transfer Attempt `att_d9384518e3b24277` failed; `next_action=matching_headings_transfer_failed_needs_practice`; no retention verification was created. |
| C — GT, main-idea/detail | Transfer Attempt `att_5362b150866f4fc7` passed and created a ReviewItem. Due review Attempt `att_e84f52aea3b24e84` failed; the item remained unverified and current KnowledgeState returned to `needs_practice`. |
| D — GT, surface keyword | Transfer Attempt `att_8f36767b1b54465a` and due review Attempt `att_d794ff487ec44d67` passed; only that dated ReviewItem was marked retention-verified. |
| E — transfer pool exhausted | Service returned degraded `transfer_unavailable`, with no question and no state promotion. |
| F — review pool exhausted | The due ReviewItem remained pending and unverified; no substitute or fabricated result was created. |
| G/H — early review | Start and acknowledgment before due time both returned HTTP 400. |
| I — retries/concurrency | Parallel transfer dispatches and review starts returned the same assigned task/session; duplicate same-key review submissions and retry returned the same Attempt. Transfer replay was also checked. |
| J — catalog version change | New immutable catalog revisions did not alter the already pinned transfer assignment or scheduled review version; both scored/restored against their original versions. |
| K — TFNG compatibility | Existing Academic TFNG string-answer route created its regular Attempt and diagnostic flow. |
| L — Python compatibility | Existing Python string-answer route created its regular Attempt and diagnostic flow. The old Python stable-status tests passed in the full suite. |

The evidence's database snapshot links the Academic transfer Attempt, DiagnosticCase, EvidenceLink IDs, KnowledgeState, ReviewItem, transfer/review Attempts, question IDs, and immutable group-version IDs. Full per-request records contain the diagnostic and practice dispatch responses and are the source for the chain above.

## Verification

- Backend full suite: **155 passed**, one upstream Starlette/httpx deprecation warning.
- Focused Phase 4 backend integration tests after final service-message adjustment: **7 passed**.
- Frontend: `node --test tests/*.test.mjs` — **44 passed**.
- Frontend TypeScript: `npm run typecheck` — passed.
- Production frontend build: `npm run build` — passed.
- Alembic heads: exactly one, `0006_matching_headings_review_provenance`.
- `git diff --check`: passed.
- API end-to-end run: Uvicorn + isolated SQLite, **104 HTTP requests**, passed.
- Configuration is exercised by the backend suite and the Uvicorn runner's isolated `Settings` injection. The repository does not define a separate backend static configuration-typecheck command.

The formal development database hash remained `BC4656AA2BC624F0A257254BA25597DB3031126FDFCBE79E5F3BB0CB607793E0` during verification; tests and HTTP acceptance used isolated databases.

## Limits and follow-up

- The decision engine is versioned deterministic rules. FakeModelProvider is fixture/configuration only; this does **not** verify real AI semantic diagnosis or paid-model behavior.
- The new content's answer mappings, target alignment, and independence metadata were author-checked. Independent editorial review is explicitly pending in the content metadata; this report does not claim external content review.
- The supplied pool supports the first delayed review cycle per diagnosis target. After a successful review, the scheduler may create a later-stage pending item without an assigned group when no further distinct reviewed content exists. The due item remains unverified until a valid task is assigned; further spaced cycles need additional independent content.
- No Matching Headings React UI, other Reading question types, or production deployment were part of this phase.

## Working tree

No commit, push, merge, reset, clean, or rebase was performed. The two pre-existing cleanup audit document modifications remain untouched. See `git status` for the exact worktree state.
