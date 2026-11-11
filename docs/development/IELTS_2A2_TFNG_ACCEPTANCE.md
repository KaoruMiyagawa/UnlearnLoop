# IELTS-2A.2 TFNG transfer and delayed review acceptance

**Acceptance: PASS for the scoped TFNG paths and A–F scenarios below.** TFNG-specific concurrent submissions and content changes after dispatch remain unverified, as noted under Coverage and limits.

The recorded runs use Uvicorn on an isolated localhost port, real HTTP via httpx, a temporary SQLite database and an injected test clock. The FakeModelProvider is configured to raise if invoked: TFNG decisions execute deterministic versioned rules, not verified AI semantic diagnosis. Synthetic test answers are retained in these traces. No formal database or system clock was modified.

TFNG uses the existing KnowledgeState string column: `transfer_verified` records a fresh correct transfer, while `ReviewItem.retention_verified` separately records a due independent review. Historical `stable` retains its existing meaning. No schema migration is required.

### Academic: logic, successful transfer and due review

Full HTTP request/response trace and database snapshot: [acad-logic-pass.json](ielts-2a2-api-evidence/acad-logic-pass.json).

- `POST /api/v1/sessions/sess_01b5708550d44a0f/attempts`: attempt `att_42829f154f26443e`, question `ielts-tfng-acad-initial`, next `diagnose`, knowledge state `needs_diagnosis`.
- `POST /api/v1/sessions/sess_01b5708550d44a0f/attempts`: attempt `att_3048509c3205486e`, question `ielts-tfng-acad-locate`, next `diagnose_step`, knowledge state `None`.
- `POST /api/v1/sessions/sess_01b5708550d44a0f/attempts`: attempt `att_bb3084ea06d44e5c`, question `ielts-tfng-acad-logic`, next `diagnose_step`, knowledge state `None`.
- Hypotheses: `true_false_not_given=candidate`, `passage_location=lowered`.
- Hypotheses: `true_false_not_given=supported`, `passage_location=lowered`.
- `POST /api/v1/sessions/sess_01b5708550d44a0f/attempts`: attempt `att_829391c1f84940fb`, question `ielts-tfng-acad-practice-logic`, next `transfer_check`, knowledge state `insufficient_evidence`.
- `POST /api/v1/sessions/sess_01b5708550d44a0f/attempts`: attempt `att_8c64a40d896145f0`, question `ielts-tfng-acad-transfer-logic`, next `transfer_verified`, knowledge state `transfer_verified`.
- `POST /api/v1/sessions/sess_01b5708550d44a0f/attempts`: attempt `att_8c64a40d896145f0`, question `ielts-tfng-acad-transfer-logic`, next `transfer_verified`, knowledge state `transfer_verified`.
- `POST /api/v1/sessions/sess_a248863c78684afe/attempts`: attempt `att_93e2d4f0ed8d41d8`, question `ielts-tfng-acad-review-logic`, next `delayed_retention_verified`, knowledge state `None`.
- `POST /api/v1/sessions/sess_a248863c78684afe/attempts`: attempt `att_93e2d4f0ed8d41d8`, question `ielts-tfng-acad-review-logic`, next `delayed_retention_verified`, knowledge state `None`.
Database evidence: `{"knowledge_status": "transfer_verified", "last_transfer_attempt_id": "att_8c64a40d896145f0", "attempts": [{"id": "att_42829f154f26443e", "question_id": "ielts-tfng-acad-initial", "version": 1, "correct": false}, {"id": "att_3048509c3205486e", "question_id": "ielts-tfng-acad-locate", "version": 1, "correct": true}, {"id": "att_bb3084ea06d44e5c", "question_id": "ielts-tfng-acad-logic", "version": 1, "correct": false}, {"id": "att_829391c1f84940fb", "question_id": "ielts-tfng-acad-practice-logic", "version": 1, "correct": true}, {"id": "att_8c64a40d896145f0", "question_id": "ielts-tfng-acad-transfer-logic", "version": 1, "correct": true}], "reviews": [{"id": "rev_2b0b5981c37746ef", "hypothesis_id": "hyp_4d46ed734e504776", "status": "completed", "attempt_id": "att_93e2d4f0ed8d41d8", "retention_verified": true, "outcome": "passed_delayed"}, {"id": "rev_d5dbe3e80f6c45d8", "hypothesis_id": "hyp_4d46ed734e504776", "status": "pending", "attempt_id": null, "retention_verified": false, "outcome": null}]}`

### General Training: location, failed transfer and remediation review

Full HTTP request/response trace and database snapshot: [gt-location-transfer_fail.json](ielts-2a2-api-evidence/gt-location-transfer_fail.json).

- `POST /api/v1/sessions/sess_4a03b1911a4d47c0/attempts`: attempt `att_8fd287729fe6428a`, question `ielts-tfng-gt-initial`, next `diagnose`, knowledge state `needs_diagnosis`.
- `POST /api/v1/sessions/sess_4a03b1911a4d47c0/attempts`: attempt `att_fb43e65158714821`, question `ielts-tfng-gt-locate`, next `diagnose_step`, knowledge state `None`.
- `POST /api/v1/sessions/sess_4a03b1911a4d47c0/attempts`: attempt `att_f86e99ff02844e7a`, question `ielts-tfng-gt-logic`, next `diagnose_step`, knowledge state `None`.
- Hypotheses: `true_false_not_given=candidate`, `passage_location=supported`.
- Hypotheses: `true_false_not_given=lowered`, `passage_location=supported`.
- `POST /api/v1/sessions/sess_4a03b1911a4d47c0/attempts`: attempt `att_8e4e0335f4aa4b01`, question `ielts-tfng-gt-practice-location`, next `transfer_check`, knowledge state `insufficient_evidence`.
- `POST /api/v1/sessions/sess_4a03b1911a4d47c0/attempts`: attempt `att_db7016005e704923`, question `ielts-tfng-gt-transfer-location`, next `transfer_failed_needs_practice`, knowledge state `needs_practice`.
- `POST /api/v1/sessions/sess_4a03b1911a4d47c0/attempts`: attempt `att_db7016005e704923`, question `ielts-tfng-gt-transfer-location`, next `transfer_failed_needs_practice`, knowledge state `needs_practice`.
- `POST /api/v1/sessions/sess_c573128322844ed4/attempts`: attempt `att_7f803f08203d47f8`, question `ielts-tfng-gt-review-location`, next `review_passed_without_retention`, knowledge state `None`.
Database evidence: `{"knowledge_status": "needs_practice", "last_transfer_attempt_id": null, "attempts": [{"id": "att_8fd287729fe6428a", "question_id": "ielts-tfng-gt-initial", "version": 1, "correct": false}, {"id": "att_fb43e65158714821", "question_id": "ielts-tfng-gt-locate", "version": 1, "correct": false}, {"id": "att_f86e99ff02844e7a", "question_id": "ielts-tfng-gt-logic", "version": 1, "correct": true}, {"id": "att_8e4e0335f4aa4b01", "question_id": "ielts-tfng-gt-practice-location", "version": 1, "correct": true}, {"id": "att_db7016005e704923", "question_id": "ielts-tfng-gt-transfer-location", "version": 1, "correct": false}], "reviews": [{"id": "rev_07c10b660cb8421f", "hypothesis_id": "hyp_386c5bf981984328", "status": "completed", "attempt_id": "att_7f803f08203d47f8", "retention_verified": false, "outcome": "passed_without_retention_baseline"}]}`

## Coverage and limits

- Two variants and both causes: routing, transfer success/failure, due-review success/failure, repeat submission and session restoration.
- A missing matching transfer and a mismatched diagnostic content version safely return insufficient evidence. The test changes a candidate before assignment; changing a question after it has been dispatched was not separately tested.
- Before its due time a review cannot be started or completed by acknowledgement. A successful due review records its own attempt and schedules the next review. A passed remediation review after transfer failure does not grant retention verification.
- Full backend regression, including existing IELTS-1, Python and existing concurrent-review tests: 119 passed. The concurrent test did not exhibit the previously reported intermittent failure; concurrent TFNG-specific submissions were not separately tested. Frontend: 41 passed; typecheck, production build and diff check passed.
- A successful delayed review is evidence for that review interval, not a guarantee of permanent retention. The small curated TFNG set and rule system do not demonstrate calibrated diagnosis or semantic understanding.

To reproduce the HTTP traces, set `TFNG_2A2_TRACE_DIR` to an isolated output directory and run `.\.venv\Scripts\python.exe -m pytest backend/tests/test_tfng_transfer_review.py -o addopts='' -q`.
