import assert from 'node:assert/strict';
import test from 'node:test';

import { ApiClientError, ApiResource, apiRequest } from '../src/api/client.ts';
import { getTopic, listTopics } from '../src/api/topics.ts';
import { createAttemptSubmission, getSessionMaterial, submitAttempt } from '../src/api/sessions.ts';
import { getDiagnosis } from '../src/api/diagnoses.ts';
import { getModelExecutionKind } from '../src/api/types.ts';
import { getReview, startReview } from '../src/api/reviews.ts';
import { listLearningHistory } from '../src/api/profile.ts';
import { getExamCatalog, getExamProfile, saveExamProfile } from '../src/api/exams.ts';

const originalFetch = globalThis.fetch;

function response(body, { status = 200, headers = {} } = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('IELTS catalogue and persisted preparation goal use the real API contract', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return response(init.method === 'GET' && String(url).includes('/catalog') ? [] : { exam_variant: 'academic' });
  };
  await getExamCatalog();
  await getExamProfile('learner A');
  await saveExamProfile({ exam_variant: 'general_training', target_overall_band: 8 });
  assert.match(calls[0].url, /\/api\/v1\/exams\/catalog$/);
  assert.match(calls[1].url, /learner_id=learner%20A$/);
  assert.equal(calls[2].init.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[2].init.body), { exam_variant: 'general_training', target_overall_band: 8 });
});

test('reading material is requested for the currently assigned session', async () => {
  let requestedUrl = '';
  globalThis.fetch = async (url) => { requestedUrl = String(url); return response({ id: 'passage-current' }); };
  const material = await getSessionMaterial('session/a');
  assert.match(requestedUrl, /\/api\/v1\/sessions\/session%2Fa\/material$/);
  assert.equal(material.id, 'passage-current');
});

test('topics use the OpenAPI paths and encode IDs and query parameters', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return response([]);
  };

  await listTopics({ domain_code: 'python basics' });
  await getTopic('topic/a b');

  assert.match(calls[0].url, /\/api\/v1\/topics\?domain_code=python\+basics$/);
  assert.match(calls[1].url, /\/api\/v1\/topics\/topic%2Fa%20b$/);
  assert.equal(calls[0].init.method, 'GET');
});

test('review detail and dispatch use server routes and preserve the selected learner', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method });
    return response({ id: 'review/1' });
  };

  await getReview('review/1', 'learner a');
  await startReview('review/1', 'learner a');
  assert.match(calls[0].url, /\/api\/v1\/reviews\/review%2F1\?learner_id=learner\+a$/);
  assert.equal(calls[0].method, 'GET');
  assert.match(calls[1].url, /\/api\/v1\/reviews\/review%2F1\/start\?learner_id=learner\+a$/);
  assert.equal(calls[1].method, 'POST');
});

test('learning history uses the learner-scoped read-only profile endpoint', async () => {
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url: String(url), method: init.method };
    return response([]);
  };
  await listLearningHistory('learner/a', 40);
  assert.match(request.url, /\/api\/v1\/profile\/history\?learner_id=learner%2Fa&limit=40$/);
  assert.equal(request.method, 'GET');
});

test('HTTP errors preserve backend code, details and request ID', async () => {
  globalThis.fetch = async () => response(
    { code: 'IDEMPOTENCY_CONFLICT', message: 'Key conflict', request_id: 'req-123', details: { field: 'answer' } },
    { status: 409, headers: { 'X-Request-ID': 'header-id' } },
  );

  await assert.rejects(apiRequest('/api/v1/sessions/x'), (error) => {
    assert.ok(error instanceof ApiClientError);
    assert.equal(error.status, 409);
    assert.equal(error.code, 'IDEMPOTENCY_CONFLICT');
    assert.equal(error.requestId, 'req-123');
    assert.deepEqual(error.details, { field: 'answer' });
    assert.equal(error.retryable, false);
    return true;
  });
});

test('non-JSON HTTP errors use the response request ID and safe fallback message', async () => {
  globalThis.fetch = async () => new Response('upstream failure', {
    status: 503,
    headers: { 'X-Request-ID': 'req-503' },
  });

  await assert.rejects(apiRequest('/api/v1/topics'), (error) => {
    assert.equal(error.code, 'HTTP_503');
    assert.equal(error.requestId, 'req-503');
    assert.equal(error.retryable, true);
    return true;
  });
});

test('network failures are normalized and marked retryable', async () => {
  globalThis.fetch = async () => { throw new TypeError('offline'); };
  await assert.rejects(apiRequest('/api/v1/topics'), (error) => {
    assert.equal(error.code, 'NETWORK_ERROR');
    assert.equal(error.status, 0);
    assert.equal(error.retryable, true);
    return true;
  });
});

test('attempt retry keeps the same intent and rejects key reuse for changed content', async () => {
  const sentBodies = [];
  globalThis.fetch = async (_url, init) => {
    sentBodies.push(JSON.parse(init.body));
    return response({ attempt_id: 'att-1', session_id: 'ses-1', question_id: 'q-1', question_role: 'initial', next_action: 'continue' });
  };

  const payload = createAttemptSubmission({
    question_id: 'q-1',
    submitted_answer: 'answer',
    idempotency_key: 'stable-key-1',
  });
  await submitAttempt('ses/1', payload);
  await submitAttempt('ses/1', payload);

  assert.equal(sentBodies.length, 2);
  assert.deepEqual(sentBodies[0], sentBodies[1]);
  assert.equal(sentBodies[0].idempotency_key, 'stable-key-1');
  assert.equal(sentBodies[0].question_id, 'q-1');

  await assert.rejects(
    submitAttempt('ses/1', { ...payload, submitted_answer: 'different answer' }),
    (error) => error.code === 'IDEMPOTENCY_CONFLICT' && error.status === 409,
  );
  assert.equal(sentBodies.length, 2, 'changed intent must be rejected before network I/O');
});

test('Mock and Live labels require consistent server metadata', () => {
  assert.equal(getModelExecutionKind({ model_provider_name: 'fake', is_mock_provider: true, execution_mode: 'mock' }), 'mock');
  assert.equal(getModelExecutionKind({ model_provider_name: 'deepseek', is_mock_provider: false, execution_mode: 'live' }), 'live');
  assert.equal(getModelExecutionKind({ model_provider_name: 'deepseek', is_mock_provider: true, execution_mode: 'live' }), 'unknown');
  assert.equal(getModelExecutionKind({ model_provider_name: 'fake', is_mock_provider: false, execution_mode: 'live' }), 'unknown');
});

test('diagnosis client reads provider execution fields without rewriting them', async () => {
  const serverPayload = {
    id: 'diag-1', session_id: 'ses-1', trigger_attempt_id: 'att-1',
    status: 'needs_evidence', uncertainty_level: 'medium', followup_turn_count: 0,
    tokens_used: 0, model_provider_name: 'fake', is_mock_provider: true,
    execution_mode: 'mock', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  };
  globalThis.fetch = async () => response(serverPayload);
  assert.deepEqual(await getDiagnosis('diag-1'), serverPayload);
});

test('ApiResource exposes loading, error and retry states while retaining the same loader', async () => {
  let calls = 0;
  const resource = new ApiResource(async () => {
    calls += 1;
    if (calls === 1) throw new ApiClientError(503, { code: 'HTTP_503', message: 'Unavailable' });
    return ['loaded'];
  });
  const seen = [];
  resource.subscribe((state) => seen.push(state.status));

  await assert.rejects(resource.load());
  assert.equal(resource.state.status, 'error');
  if (resource.state.status === 'error') assert.equal(resource.state.error.retryable, true);
  assert.deepEqual(await resource.retry(), ['loaded']);
  assert.equal(resource.state.status, 'success');
  assert.deepEqual(seen, ['idle', 'loading', 'error', 'loading', 'success']);
});
