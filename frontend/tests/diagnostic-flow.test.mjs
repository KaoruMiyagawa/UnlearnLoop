import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { getModelExecutionKind } from '../src/api/types.ts';
import { retryDiagnosticStep, runDiagnosticStep } from '../src/api/diagnoses.ts';
import {
  canRetryDiagnosticStep,
  canRunDiagnosticStep,
  clearPendingDiagnosticIntent,
  diagnosticExecutionDescription,
  diagnosticStatusLabel,
  evidenceRelationLabel,
  getOrCreateDiagnosticIntent,
  groupEvidenceByHypothesis,
  hypothesisStatusLabel,
  loadDiagnosticWorkspace,
  readPendingDiagnosticIntent,
} from '../src/learning-workspace/diagnosticFlow.ts';

const originalFetch = globalThis.fetch;

test.afterEach(() => { globalThis.fetch = originalFetch; });

test('diagnostic workspace reads actual case, hypotheses, evidence, and triggering attempt endpoints', async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    const path = new URL(url).pathname;
    calls.push(path);
    if (path.endsWith('/diagnoses/d-1')) return new Response(JSON.stringify({
      id: 'd-1', session_id: 's-1', trigger_attempt_id: 'a-1', status: 'needs_evidence',
      uncertainty_level: 'high', followup_turn_count: 0, tokens_used: 0,
      model_provider_name: 'fake', is_mock_provider: true, execution_mode: 'mock',
      hypotheses: [], evidence_count: 0, created_at: '2026-01-01', updated_at: '2026-01-01',
    }));
    if (path.endsWith('/diagnoses/d-1/hypotheses')) return new Response(JSON.stringify([{ id: 'h-1', diagnostic_case_id: 'd-1', error_code: 'RANGE_END', name: '停止位置理解错误', confidence: 0.6, status: 'candidate', created_at: '2026-01-01', updated_at: '2026-01-01' }]));
    if (path.endsWith('/diagnoses/d-1/evidence')) return new Response(JSON.stringify([{ id: 'e-1', hypothesis_id: 'h-1', source_type: 'initial_attempt', source_ref: 'a-1', relation: 'supports', summary: '原始回答与假设一致', created_at: '2026-01-01' }]));
    if (path.endsWith('/attempts/a-1')) return new Response(JSON.stringify({ id: 'a-1', session_id: 's-1', question_id: 'q-1', question_role: 'initial', question_version: 1, submitted_answer: 'learner raw response', evaluation_status: 'evaluated', submitted_at: '2026-01-01' }));
    throw new Error(`Unexpected API path ${path}`);
  };

  const data = await loadDiagnosticWorkspace('d-1', new AbortController().signal);
  assert.equal(data.diagnosis.status, 'needs_evidence');
  assert.equal(data.hypotheses[0].status, 'candidate');
  assert.equal(data.evidence[0].relation, 'supports');
  assert.equal(data.triggerAttempt.submitted_answer, 'learner raw response');
  assert.equal(calls.length, 4);
  assert.ok(calls.some((path) => path.endsWith('/diagnoses/d-1/hypotheses')));
  assert.ok(calls.some((path) => path.endsWith('/diagnoses/d-1/evidence')));
});

test('Agent step and retry use the backend decision endpoints with the stored idempotency payload', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ path: new URL(url).pathname, method: init.method, body: JSON.parse(init.body) });
    return new Response(JSON.stringify({
      session_id: 's-1', diagnostic_case_id: 'd-1', case_status: 'question_selected',
      executed_tool: 'select_diagnostic_followup', selected_intervention: 'ask_followup',
      selected_question_id: 'q-followup', next_question: { id: 'q-followup', question_role: 'diagnostic_followup' },
      uncertainty_level: 'high', followup_turns_used: 1, max_followup_turns: 2,
      tokens_used_in_case: 200, session_token_budget: 4096, model_provider_name: 'fake',
      is_mock_provider: true, execution_mode: 'mock', confidence_is_heuristic: true,
    }));
  };

  await runDiagnosticStep('d-1', { idempotency_key: 'same-step-key' });
  await retryDiagnosticStep('d-1', { idempotency_key: 'explicit-retry-key' });
  assert.deepEqual(calls.map(({ path, method, body }) => ({ path, method, body })), [
    { path: '/api/v1/diagnoses/d-1/step', method: 'POST', body: { idempotency_key: 'same-step-key' } },
    { path: '/api/v1/diagnoses/d-1/retry', method: 'POST', body: { idempotency_key: 'explicit-retry-key' } },
  ]);
});

test('diagnostic actions are gated by real session and case states', () => {
  const active = { status: 'diagnosing' };
  const caseOpen = { status: 'needs_evidence' };
  assert.equal(canRunDiagnosticStep(active, caseOpen), true);
  const awaitingFollowup = { status: 'diagnosing', current_question_id: 'q-followup' };
  assert.equal(canRunDiagnosticStep(awaitingFollowup, caseOpen, []), false);
  assert.equal(canRunDiagnosticStep(awaitingFollowup, caseOpen, [{ question_id: 'q-followup' }]), true);
  assert.equal(canRunDiagnosticStep({ status: 'paused' }, caseOpen), false);
  assert.equal(canRunDiagnosticStep(active, { status: 'resolved' }), false);
  assert.equal(canRunDiagnosticStep(active, { status: 'insufficient_evidence' }), false);
  assert.equal(canRetryDiagnosticStep(active, { status: 'retry_waiting' }), true);
  assert.equal(canRetryDiagnosticStep(active, caseOpen), false);
  assert.equal(canRetryDiagnosticStep({ status: 'paused' }, { status: 'retry_waiting' }), false);
});

test('server enums keep their real meanings and unknown statuses remain unknown', () => {
  assert.equal(diagnosticStatusLabel('needs_evidence'), '证据仍不足');
  assert.equal(hypothesisStatusLabel('ruled_out'), '已排除');
  assert.notEqual(hypothesisStatusLabel('resolved'), '已排除');
  assert.match(hypothesisStatusLabel('resolved'), /未知假设状态/);
  assert.equal(evidenceRelationLabel('contradicts'), '反对');
});

test('evidence is linked only to the hypothesis ID returned by the API', () => {
  const grouped = groupEvidenceByHypothesis([
    { id: 'e1', hypothesis_id: 'h1', relation: 'supports' },
    { id: 'e2', hypothesis_id: 'h2', relation: 'contradicts' },
    { id: 'e3', hypothesis_id: 'h1', relation: 'neutral' },
  ]);
  assert.deepEqual(grouped.get('h1').map((item) => item.id), ['e1', 'e3']);
  assert.deepEqual(grouped.get('h2').map((item) => item.id), ['e2']);
});

test('pending step intent persists its idempotency key and prevents a different action from reusing it', () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  let generated = 0;
  const first = getOrCreateDiagnosticIntent(storage, 'd-1', 'step', () => `step-key-${++generated}`);
  const restored = readPendingDiagnosticIntent(storage, 'd-1');
  assert.equal(restored.payload.idempotency_key, first.payload.idempotency_key);
  assert.equal(getOrCreateDiagnosticIntent(storage, 'd-1', 'step').payload.idempotency_key, first.payload.idempotency_key);
  assert.throws(() => getOrCreateDiagnosticIntent(storage, 'd-1', 'retry'), /等待明确恢复/);
  clearPendingDiagnosticIntent(storage, 'd-1');
  assert.equal(readPendingDiagnosticIntent(storage, 'd-1'), null);
});

test('model mode requires consistent server metadata and displays incomplete/conflicting data as unknown', () => {
  const fake = { model_provider_name: 'fake', is_mock_provider: true, execution_mode: 'mock' };
  const live = { model_provider_name: 'deepseek', is_mock_provider: false, execution_mode: 'live' };
  assert.equal(diagnosticExecutionDescription(fake, null).kind, 'mock');
  assert.equal(diagnosticExecutionDescription(live, null).kind, 'live');
  assert.equal(diagnosticExecutionDescription({ ...fake, execution_mode: 'live' }, null).kind, 'unknown');
  assert.equal(diagnosticExecutionDescription(fake, live).kind, 'unknown');
  assert.equal(getModelExecutionKind({ model_provider_name: 'fake', is_mock_provider: false, execution_mode: 'live' }), 'unknown');
});

test('real diagnostic workspace does not import demo fixtures or mock timeline data', async () => {
  const source = await readFile(new URL('../src/learning-workspace/RealLearningWorkspace.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /INITIAL_LOOP_STAGE_SNAPSHOTS|INITIAL_DECISION_TIMELINE|stage5WorkbenchModel/);
  assert.match(source, /loadDiagnosticWorkspace\(diagnosticCaseId, signal\)/);
  assert.match(source, /runDiagnosticStep\(diagnosticCaseId, intent\.payload, signal\)/);
});
