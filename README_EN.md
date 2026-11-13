# VerbaTrail

**VerbaTrail — Learn a language. Make it yours.**

An adaptive language learning system designed to help learners build understanding, communication skills, and lasting proficiency through personalized practice and evidence-based feedback.

**First milestone: IELTS Overall Band 8.0.** This is a learning goal, not a statement of current ability, a score prediction, or a guarantee. The long-term vision is to help people truly learn a language, beyond getting more test questions right.

[简体中文](README.md) · [Learn / IELTS development baseline](https://github.com/KaoruMiyagawa/VerbaTrail/tree/feat/ielts-2b-reading-question-groups) · [Windows quick start](docs/development/QUICKSTART.md) · [Current architecture](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/architecture/CURRENT_ARCHITECTURE.md) · [Product direction](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/product/IELTS_PRODUCT_DIRECTION.md) · [Roadmap](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/development/ROADMAP.md)

> **Current status:** VerbaTrail has three product areas: Learn / Discover / Adapt. Learn has Listening, Speaking, Reading, and Writing sections. Reading retains the existing Academic and General Training flows. Listening now has one limited original synthetic-audio exercise; Speaking and Writing remain planned. The IELTS-2B.1 Phase 6.2 engineering result is **PASS WITH LIMITATIONS**. The original Phase 6 **FAIL** remains in the historical report.

## Product vision

VerbaTrail aims to adapt practice to a learner’s goals, evidence about their current abilities, and available time. It will combine useful input, practice, communication, feedback, and review. IELTS Overall Band 8.0 is the first concrete target scenario; the broader goal is language understanding, communication, and use across contexts.

Learn provides Listening, Speaking, Reading, and Writing as first-level skills. Discover will provide external learning resources with legitimate sources. Adapt will personalize learning plans and decisions. Vocabulary, grammar, Error DNA, transfer, review, learning history, and assessment are shared across skills.

```mermaid
flowchart LR
    L[Language learning system] --> P[Learner profile and ability evidence]
    P --> A[Adaptive learning Agent]
    A --> I[Input: reading · listening · vocabulary · grammar]
    A --> O[Output: speaking · writing · communication]
    I --> F[Feedback and error diagnosis]
    O --> F
    F -. Error DNA: candidate explanations and evidence .-> T[Transfer to new contexts and long-term review]
    T --> N[Personalized learning plan]
    N --> A
```

**Error DNA is one feedback and diagnosis capability, not the whole product.** It organizes observed answer patterns, candidate explanations, and evidence that may verify them. Rule-based flows and FakeModelProvider do not establish real AI semantic diagnosis. A single answer, transfer pass, or review pass cannot by itself prove lasting mastery.

## Capability status

| Capability | Status and limits |
| --- | --- |
| IELTS Reading | **Implemented in a limited scope:** original Academic and General Training materials, TFNG flows, and Matching Headings group answers with item-level evaluation. This is not full Reading question-type coverage. |
| IELTS Listening | **First limited loop implemented:** one approximately 64-second original script with offline-synthesized audio, five multiple-choice questions, server-side rule scoring, explanations, and audio time anchors. Attempts reuse shared learning history. No official Band score, full exam, or long-term ability/transfer/retention claim. |
| Feedback and Error DNA | **Partially implemented:** candidate hypotheses, evidence, discriminating follow-up, and targeted practice for specific Reading paths. These are supported by server-side rules; they are not validated real-model teaching or a language-wide learner profile. |
| Transfer and review | Matching Headings independent transfer and first delayed review use server records. Historical evidence labeling and state reconciliation passed isolated retesting. |
| Learning history and profile | Displays server-side sessions, knowledge states, transfer, review, historical evidence validity, and revalidation when available. |
| Dual-theme interface | **Implemented:** one React app supports Premium Academic and Noir & Champagne. |
| Speaking and Writing | **Planned:** speaking recording/transcription and feedback, and writing drafts and feedback, remain unimplemented. |
| Vocabulary, Grammar, comprehension and expression practice | **Planned:** there is no unified cross-skill ability model or complete training system yet. |
| Learner model, personalized plan, adaptive Agent | **Planned:** a complete initial ability assessment and cross-skill plan do not exist yet. |
| IELTS mock tests, UKVI, Life Skills, other languages | **Not implemented:** future directions; the current product covers limited English IELTS Reading and one original Listening exercise. |
| Real-model teaching quality, official scoring, band prediction | **Unvalidated / not implemented:** no claim of real AI personalization, official scores, or an IELTS 8.0 outcome. |

### Themes and product captures

These are genuine browser captures from an earlier isolated IELTS-1 acceptance run. They show the home and Reading interface at that time; they do not imply that IELTS-2B.1 Phase 6 passed or that all current capabilities are complete.

<table>
  <tr>
    <td><img src="https://raw.githubusercontent.com/KaoruMiyagawa/VerbaTrail/feat/ielts-2b-reading-question-groups/docs/development/consolidation-browser-evidence/home-premium.png" alt="Premium Academic home" width="100%"><br><sub>Premium Academic · Home</sub></td>
    <td><img src="https://raw.githubusercontent.com/KaoruMiyagawa/VerbaTrail/feat/ielts-2b-reading-question-groups/docs/development/consolidation-browser-evidence/home-noir.png" alt="Noir & Champagne home" width="100%"><br><sub>Noir &amp; Champagne · Home</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="https://raw.githubusercontent.com/KaoruMiyagawa/VerbaTrail/feat/ielts-2b-reading-question-groups/docs/development/consolidation-browser-evidence/academic-reading-premium.png" alt="Academic Reading workspace" width="100%"><br><sub>Academic Reading · earlier isolated browser acceptance</sub></td>
  </tr>
</table>

[Learn V1.1 browser captures](docs/development/learn-v1.1-browser-evidence/README.md) · [Listening V1.2 captures and acceptance](docs/development/listening-v1.2-browser-evidence/README.md) · [IELTS-2B.1 Phase 6.2 retest](docs/development/IELTS_2B1_PHASE6_2_ACCEPTANCE.md) · Original Phase 6 FAIL report at `docs/development/IELTS_2B1_FINAL_ACCEPTANCE.md` · [Earlier browser evidence index](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/development/consolidation-browser-evidence/README.md) · [Dual-theme visual review](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/development/theme-visual-acceptance/VISUAL_REVIEW.md)

## Architecture

```mermaid
flowchart LR
    UI[React / TypeScript / Vite] -->|REST API| API[FastAPI]
    API --> APP[Application services and domain rules]
    APP --> DATA[SQLite / SQLAlchemy]
    APP --> MIG[Alembic migrations]
    APP --> LEARN[Sessions · answers · evaluation]
    APP --> AGENT[Rule-based diagnosis and learning-state orchestration]
    AGENT --> PROVIDER[FakeModelProvider / model adapter interface]
```

The current backend manages learning sessions, version-pinned reading groups, structured answers, evaluation snapshots, specific diagnostic flows, transfer, and review states. React renders server-provided state through an API client. SQLite is the default local store. A unified learner model, cross-skill planning, and a validated live-model Agent are not implemented. See the [current architecture](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/architecture/CURRENT_ARCHITECTURE.md) and [target architecture](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/architecture/ARCHITECTURE.md).

## Run locally on Windows

Requirements: Python 3.11+, Node.js, npm, and Git. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
```

Start the backend in a PowerShell window (`DATABASE_URL` is relative to `backend/`):

```powershell
$env:DATABASE_URL = 'sqlite:///./verbatrail-local.db'
$env:APP_NAME = 'VerbaTrail'
$env:MODEL_PROVIDER = 'fake'
$env:ALLOW_REMOTE_MODEL_CALLS = 'false'
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
```

Start the frontend in a second window:

```powershell
cd frontend
npm run dev
```

Open `http://127.0.0.1:15173`; API documentation is at `http://127.0.0.1:18000/docs`. Startup migrates the configured database. Back up and verify recoverability before using an existing database. See the [quick-start guide](docs/development/QUICKSTART.md) for details. This is a local development setup, not a production or multi-user security configuration.

## Tests and project maturity

Common checks:

```powershell
cd backend
..\.venv\Scripts\python -m pytest
cd ../frontend
node --test tests/*.test.mjs
npm run typecheck
npm run build
```

The IELTS-2B.1 Phase 6.2 retest passed **166 backend tests** and **48 frontend tests**, TypeScript checks, production build, isolated HTTP flows, and Chrome browser regression. Learn V1.1 captures and browser checks are documented in the [evidence index](docs/development/learn-v1.1-browser-evidence/README.md). Tests use rules and FakeModelProvider; they do not validate real-model quality, external expert review, production security, or complete IELTS coverage.

The current trust boundary is local, single-user development: `learner_id` is a filter, not authentication. The project does not provide production-grade account authentication or tenant isolation. No open-source license is declared; redistribution rights should not be assumed.

## Product and development documents

- [Product direction](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/product/IELTS_PRODUCT_DIRECTION.md): learner-centered language-learning vision and capability plan.
- [Product requirements](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/product/PRD.md): current scope, capability status, and product boundaries.
- [Current architecture](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/architecture/CURRENT_ARCHITECTURE.md) · [Target architecture](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/architecture/ARCHITECTURE.md)
- [Development roadmap](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/ielts-2b-reading-question-groups/docs/development/ROADMAP.md) · [Windows quick start](docs/development/QUICKSTART.md)
- IELTS-2B.1 Phase 6 final acceptance (local report not yet committed): current FAIL reason, fixes, evidence, and outstanding work.

The roadmap starts with trust labels and recalculation for historical evidence, then builds a language ability model, initial assessment, and personalized planning. It next expands across skills, long-term memory and transfer, before evaluating additional languages and more capable teaching systems.
