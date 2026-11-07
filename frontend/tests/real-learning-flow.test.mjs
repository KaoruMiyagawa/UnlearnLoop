import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ApiClientError, apiRequest } from '../src/api/client.ts';
import { createSession, dispatchTransferCheck, submitAttempt } from '../src/api/sessions.ts';
import { getSanitizedQuestion, getTopic, getTopicMaterials, listTopics } from '../src/api/topics.ts';
import { deriveLearningVisualStage, describeNextAction, prepareAttemptIntent, restoreSessionFromServer, SingleFlightGate } from '../src/learning-workspace/learningFlow.ts';

const originalFetch = globalThis.fetch;

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

test.afterEach(() => { globalThis.fetch = originalFetch; });

test('real mode is the default and its workspace does not import demo fixtures', async () => {
  const appSource = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const realWorkspaceSource = await readFile(new URL('../src/learning-workspace/RealLearningWorkspace.tsx', import.meta.url), 'utf8');
  assert.match(appSource, /useState<'demo' \| 'real'>\('real'\)/);
  assert.match(appSource, /dataMode === 'real' \?/);
  assert.doesNotMatch(realWorkspaceSource, /INITIAL_LOOP_STAGE_SNAPSHOTS|INITIAL_DECISION_TIMELINE|stage5WorkbenchModel/);
  assert.match(realWorkspaceSource, /listTopics\(|createSession\(|submitAttempt\(/);
});

test('real topic, detail, materials and sanitized question render from server responses', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push(String(url));
    if (String(url).endsWith('/api/v1/topics')) return jsonResponse([{ id: 't-math', slug: 'fractions', domain_code: 'math', title: 'Fractions', summary: 'Server topic', difficulty_level: 1 }]);
    if (String(url).endsWith('/api/v1/topics/fractions')) return jsonResponse({ id: 't-math', slug: 'fractions', domain_code: 'math', title: 'Fractions', summary: 'Server detail', difficulty_level: 1, questions_count: 1 });
    if (String(url).endsWith('/api/v1/topics/fractions/materials')) return jsonResponse([{ id: 'm-1', topic_id: 't-math', title: 'Material', summary: 'Server material', content_body: 'Exact server body', content_format: 'markdown', version: 1 }]);
    if (String(url).endsWith('/api/v1/questions/q-1')) return jsonResponse({ id: 'q-1', topic_id: 't-math', question_role: 'initial', question_type: 'short_text', prompt_text: 'Server prompt', difficulty: 1, version: 1 });
    throw new Error(`Unexpected URL ${url}`);
  };

  assert.equal((await listTopics())[0].title, 'Fractions');
  assert.equal((await getTopic('fractions')).summary, 'Server detail');
  assert.equal((await getTopicMaterials('fractions'))[0].content_body, 'Exact server body');
  const question = await getSanitizedQuestion('q-1');
  assert.equal(question.prompt_text, 'Server prompt');
  assert.equal('standard_answer' in question, false);
  assert.equal(calls.length, 4);
});

test('session creation sends selected server topic and preserves returned current question', async () => {
  let sent;
  globalThis.fetch = async (_url, init) => {
    sent = JSON.parse(init.body);
    return jsonResponse({ id: 'ses-1', topic_id: 'topic-math', topic_title: 'Fractions', learner_id: 'learner-1', status: 'active', topic_mastered: false, current_question_id: 'q-server', current_question: { id: 'q-server', topic_id: 'topic-math', question_role: 'initial', question_type: 'short_text', prompt_text: 'Actual first question', difficulty: 1, version: 2 }, active_diagnostic_case_id: null, attempts_count: 0, started_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }, 201);
  };
  const created = await createSession({ topic_id: 'topic-math', learner_id: 'learner-1' });
  assert.deepEqual(sent, { topic_id: 'topic-math', learner_id: 'learner-1' });
  assert.equal(created.current_question.id, 'q-server');
  assert.equal(created.current_question.prompt_text, 'Actual first question');
});

test('creating a session failure remains a backend error and does not manufacture a session', async () => {
  globalThis.fetch = async () => jsonResponse({ code: 'NOT_FOUND', message: 'Topic missing', request_id: 'r-404', details: {} }, 404);
  await assert.rejects(createSession({ topic_id: 'missing-topic' }), (error) => {
    assert.ok(error instanceof ApiClientError);
    assert.equal(error.code, 'NOT_FOUND');
    assert.equal(error.status, 404);
    return true;
  });
});

test('attempt responses control correctness and next_action presentation', async () => {
  const responses = [
    { attempt_id: 'a-correct', session_id: 's', question_id: 'q', question_role: 'initial', is_correct: true, next_action: 'transfer_check', knowledge_state_status: null },
    { attempt_id: 'a-wrong', session_id: 's', question_id: 'q2', question_role: 'initial', is_correct: false, next_action: 'diagnose', diagnostic_case_id: 'diag-1', knowledge_state_status: 'needs_diagnosis' },
  ];
  globalThis.fetch = async () => jsonResponse(responses.shift());
  const first = await submitAttempt('s', { question_id: 'q', submitted_answer: 'server correct', idempotency_key: 'intent-1' });
  const second = await submitAttempt('s', { question_id: 'q2', submitted_answer: 'server wrong', idempotency_key: 'intent-2' });
  assert.equal(first.is_correct, true);
  assert.equal(describeNextAction(first.next_action).title, '需要迁移验证题');
  assert.equal(second.is_correct, false);
  assert.equal(second.diagnostic_case_id, 'diag-1');
  assert.equal(describeNextAction(second.next_action).title, '等待诊断步骤');
  assert.match(describeNextAction(second.next_action).description, /不会在前端生成假设或证据/);
});

test('transfer question is requested from the service and not chosen by the browser', async () => {
  let body;
  globalThis.fetch = async (_url, init) => {
    body = JSON.parse(init.body);
    return jsonResponse({ question: { id: 'q-fresh-server', topic_id: 't', question_role: 'transfer_check', question_type: 'short_text', prompt_text: 'Fresh server prompt', difficulty: 2, version: 1 }, session_status: 'transfer_checking', degraded: false, message: 'dispatched' });
  };
  const result = await dispatchTransferCheck('s-1', { force_fresh: true });
  assert.deepEqual(body, { force_fresh: true });
  assert.equal(result.question.id, 'q-fresh-server');
});

test('same answer retry reuses the original key and changed intent is rejected', async () => {
  let calls = 0;
  const bodies = [];
  globalThis.fetch = async (_url, init) => {
    calls += 1;
    bodies.push(JSON.parse(init.body));
    return jsonResponse({ attempt_id: 'a-1', session_id: 's-intent', question_id: 'q-intent', question_role: 'initial', next_action: 'diagnose' });
  };
  const prepared = prepareAttemptIntent(null, 's-intent', 'q-intent', 'answer A');
  const retry = prepareAttemptIntent(prepared, 's-intent', 'q-intent', 'answer A');
  assert.equal(retry, prepared);
  await submitAttempt(prepared.sessionId, prepared.payload);
  await submitAttempt(retry.sessionId, retry.payload);
  assert.equal(bodies[0].idempotency_key, bodies[1].idempotency_key);
  assert.deepEqual(bodies[0], bodies[1]);
  assert.throws(() => prepareAttemptIntent(prepared, 's-intent', 'q-intent', 'answer B'), (error) => error.code === 'PENDING_SUBMISSION_EXISTS');
  assert.equal(calls, 2);
});

test('single-flight gate rejects overlapping submit clicks', async () => {
  const gate = new SingleFlightGate();
  assert.equal(gate.tryAcquire(), true);
  assert.equal(gate.tryAcquire(), false);
  gate.release();
  assert.equal(gate.tryAcquire(), true);
});

test('real session restoration reloads server state and resumes paused sessions', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const path = String(url);
    calls.push(`${init.method} ${path}`);
    if (path.endsWith('/api/v1/sessions/s-paused')) return jsonResponse({ id: 's-paused', topic_id: 'topic-math', topic_title: 'Fractions', learner_id: 'learner', status: 'paused', topic_mastered: false, current_question_id: 'q-1', current_question: { id: 'q-1', topic_id: 'topic-math', question_role: 'initial', question_type: 'short_text', prompt_text: 'Restored prompt', difficulty: 1, version: 1 }, attempts_count: 1, started_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' });
    if (path.endsWith('/api/v1/sessions/s-paused/resume')) return jsonResponse({ id: 's-paused', topic_id: 'topic-math', topic_title: 'Fractions', learner_id: 'learner', status: 'active', topic_mastered: false, current_question_id: 'q-2', current_question: { id: 'q-2', topic_id: 'topic-math', question_role: 'diagnostic_followup', question_type: 'short_text', prompt_text: 'Server followup', difficulty: 1, version: 1 }, attempts_count: 1, started_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' });
    if (path.endsWith('/api/v1/sessions/s-paused/attempts')) return jsonResponse([{ id: 'a-old', session_id: 's-paused', question_id: 'q-1', question_role: 'initial', submitted_answer: 'old answer', evaluation_status: 'evaluated', submitted_at: '2026-01-01T00:00:00Z' }]);
    throw new Error(`Unexpected URL ${url}`);
  };
  const restored = await restoreSessionFromServer('s-paused', new AbortController().signal);
  assert.equal(restored.session.status, 'active');
  assert.equal(restored.session.current_question.prompt_text, 'Server followup');
  assert.equal(restored.attempts[0].submitted_answer, 'old answer');
  assert.equal(calls.some((call) => call.includes('/resume')), true);
});

test('API unavailable surfaces the real network error without a mock success fallback', async () => {
  globalThis.fetch = async () => { throw new TypeError('offline'); };
  await assert.rejects(listTopics(), (error) => error.code === 'NETWORK_ERROR' && error.retryable === true);
});

test('visual step is derived from server state, never from a local increment', () => {
  const session = { status: 'diagnosing', active_diagnostic_case_id: 'd-1', current_question: null };
  assert.equal(deriveLearningVisualStage(session, null), 3);
  assert.equal(deriveLearningVisualStage(session, null), 3);
  assert.equal(deriveLearningVisualStage({ status: 'diagnosing', active_diagnostic_case_id: 'd-1', current_question: { question_role: 'initial' } }, null), 3);
  assert.equal(deriveLearningVisualStage({ status: 'completed', topic_mastered: false, knowledge_state_status: 'needs_practice', current_question: null }, null), 5);
  assert.equal(deriveLearningVisualStage({ status: 'transfer_checking', topic_mastered: true, current_question: null }, null), 6);
});

test('timeout and explicit cancellation preserve distinguishable API errors', async () => {
  globalThis.fetch = async (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  });
  await assert.rejects(apiRequest('/api/v1/test', {}, 5), (error) => error.code === 'REQUEST_TIMEOUT');

  const controller = new AbortController();
  const request = apiRequest('/api/v1/test', { signal: controller.signal }, 1000);
  controller.abort();
  await assert.rejects(request, (error) => error.code === 'REQUEST_ABORTED');
});
