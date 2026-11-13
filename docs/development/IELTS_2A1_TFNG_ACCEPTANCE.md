# IELTS-2A.1 TFNG backend acceptance

## Scope and execution

The new protocol is deterministic, versioned rule evaluation. It performs no model calls. Integration tests replace FakeModelProvider.generate_structured with an exception to prove this boundary. TestClient exercises the real FastAPI routes with pytest temporary SQLite databases. This is backend integration acceptance, not browser acceptance. No frontend changes were made.

## Original content

`backend/app/content/ielts_tfng_diagnostic_pack.json` supplies two separate topics (Academic and General Training), each with stable version-1 IDs: initial, locate, logic, practice-logic, practice-location. Each question has its own original passage, server-only answer, purpose and evidence scope. Rubrics carry `reading-error-dna-v1` and `tfng-v1`. No existing questions were replaced.

Initial claim: the town library opens at nine on Sundays. The passage specifies weekdays only. An answer of FALSE starts competing TFNG-logic and passage-location hypotheses. A museum sentence-selection task then tests location without TFNG reasoning. A water-temperature task provides the relevant evidence directly to reduce location demands and tests missing information versus explicit denial.

## Actual API runs

### A: successful location, weak TFNG logic

Full actual request/response record: [acad-logic.json](ielts-2a1-api-evidence/acad-logic.json).

| Request | Result |
|---|---|
| POST `/api/v1/sessions/sess_c69b2492fab44b31/attempts` | question=`ielts-tfng-acad-initial`, answer=`FALSE`, Attempt=`att_d5ba784a767f4398` |
| POST `/api/v1/sessions/sess_c69b2492fab44b31/attempts` | question=`ielts-tfng-acad-initial`, answer=`FALSE`, Attempt=`att_d5ba784a767f4398` |
| POST `/api/v1/diagnoses/diag_391cdd4bf1494a17/step` | `question_selected` → `ielts-tfng-acad-locate`; turns=1; mode=`rules` |
| POST `/api/v1/diagnoses/diag_391cdd4bf1494a17/step` | `question_selected` → `ielts-tfng-acad-locate`; turns=1; mode=`rules` |
| POST `/api/v1/sessions/sess_c69b2492fab44b31/attempts` | question=`ielts-tfng-acad-locate`, answer=`B`, Attempt=`att_71c7ed40c1544fc2` |
| POST `/api/v1/diagnoses/diag_391cdd4bf1494a17/step` | `question_selected` → `ielts-tfng-acad-logic`; turns=2; mode=`rules` |
| POST `/api/v1/sessions/sess_c69b2492fab44b31/attempts` | question=`ielts-tfng-acad-logic`, answer=`FALSE`, Attempt=`att_3723cfa678fa40b7` |
| POST `/api/v1/diagnoses/diag_391cdd4bf1494a17/step` | `intervention_selected` → `ielts-tfng-acad-practice-logic`; turns=2; mode=`rules` |

Selected training reason: TFNG v1：true_false_not_given 获得支持，另一原因被削弱；选择对应训练，仍不确认能力缺陷。

Final hypotheses: `true_false_not_given=supported`, `passage_location=lowered`.

### B: successful TFNG logic, weak location

Full actual request/response record: [acad-location.json](ielts-2a1-api-evidence/acad-location.json).

| Request | Result |
|---|---|
| POST `/api/v1/sessions/sess_1fce05cce7ab41eb/attempts` | question=`ielts-tfng-acad-initial`, answer=`FALSE`, Attempt=`att_844390a874664fe7` |
| POST `/api/v1/sessions/sess_1fce05cce7ab41eb/attempts` | question=`ielts-tfng-acad-initial`, answer=`FALSE`, Attempt=`att_844390a874664fe7` |
| POST `/api/v1/diagnoses/diag_cfa185e949cb4cf8/step` | `question_selected` → `ielts-tfng-acad-locate`; turns=1; mode=`rules` |
| POST `/api/v1/diagnoses/diag_cfa185e949cb4cf8/step` | `question_selected` → `ielts-tfng-acad-locate`; turns=1; mode=`rules` |
| POST `/api/v1/sessions/sess_1fce05cce7ab41eb/attempts` | question=`ielts-tfng-acad-locate`, answer=`A`, Attempt=`att_78d5d2ddf0534cd7` |
| POST `/api/v1/diagnoses/diag_cfa185e949cb4cf8/step` | `question_selected` → `ielts-tfng-acad-logic`; turns=2; mode=`rules` |
| POST `/api/v1/sessions/sess_1fce05cce7ab41eb/attempts` | question=`ielts-tfng-acad-logic`, answer=`NOT GIVEN`, Attempt=`att_95f5708f21b248b1` |
| POST `/api/v1/diagnoses/diag_cfa185e949cb4cf8/step` | `intervention_selected` → `ielts-tfng-acad-practice-location`; turns=2; mode=`rules` |

Selected training reason: TFNG v1：passage_location 获得支持，另一原因被削弱；选择对应训练，仍不确认能力缺陷。

Final hypotheses: `true_false_not_given=lowered`, `passage_location=supported`.

## Training and safe degradation

The rule proposal chooses a specific training ID only when one hypothesis is supported and the other is lowered. The executor independently checks the selected ID, target codes, supported hypothesis and unanswered status. Missing matching training, both weak results, both successful results, or unrecognised answers produce no assigned training and retain insufficient_evidence. The legacy Python protocol keeps its existing selection behavior.

## Traceability and compatibility

Attempt snapshots retain diagnostic protocol/version. Evidence refs retain diagnostic version, question ID/version and Attempt ID. Follow-up evidence updates may support or lower hypotheses; they do not confirm them. Duplicate steps replay without adding follow-up turns; duplicate answer submissions return the same Attempt. The follow-up counter excludes idempotency index events. Session and case GET requests restore server state. Answer keys, rubric and answer explanations are excluded from dispatched question DTOs.

No schema migration was required. Startup imports additive content into the configured database; during this work all startup and integration verification used temporary SQLite. The local backend/unlearnloop.db hash remained BC4656AA2BC624F0A257254BA25597DB3031126FDFCBE79E5F3BB0CB607793E0.

## Validation

Backend: 99 passed (final full run, 24.71 seconds). Frontend: 40 tests passed; TypeScript typecheck and production build passed. git diff --check passed. The previous concurrent-review timing failure did not recur. Starlette emits its existing httpx TestClient deprecation warning.

The 11 new API scenarios cover both exam variants across both diagnostic paths, both weak, both successful, unknown answers, and missing matching practice; each successful scenario exercises answer idempotency, diagnostic-step replay and restoration. The initial full run exposed an old fixed topic-count expectation (9); it was updated to 11 for the two new topics.

## Limits

This small content set tests narrow task performances and offers tentative explanations, not calibrated ability diagnosis. It does not interpret free text semantically. Microtask evidence cannot establish a confirmed or permanent impairment. UI, deep diagnosis of other categories, Next Best Action, transfer and delayed-review completion are outside IELTS-2A.1. No paid model calls, commits or pushes were performed.

## Reproduce

From the repository root, run `.\.venv\Scripts\python.exe -m pytest backend/tests/test_tfng_api.py`.
Set `TFNG_TRACE_DIR` to an isolated output directory to save the API request/response traces. No server process or real database is needed; the test client executes the application with temporary databases.
