import assert from 'node:assert/strict';
import test from 'node:test';
import { getTransferPresentation } from '../src/learning-workspace/transferFlow.ts';
import { clearPendingAttempt, describeNextAction, prepareAttemptIntent, readPendingAttempt, restoreSessionFromServer, storePendingAttempt } from '../src/learning-workspace/learningFlow.ts';
import { submitAttempt } from '../src/api/sessions.ts';

const originalFetch = globalThis.fetch;
test.afterEach(() => { globalThis.fetch = originalFetch; });
const transfer = { id: 'server-transfer', question_role: 'transfer_check', prompt_text: 'A new server situation' };
const session = { id: 's-transfer', status: 'transfer_checking', current_question_id: transfer.id, current_question: transfer, active_diagnostic_case_id: 'case-real', can_dispatch_transfer: false };
const json = (body) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
function memoryStorage() {
  const data = new Map();
  return { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key) };
}

test('transfer view uses only current server assignment, not the old attempt next_question', () => {
  const oldResponse = { question_role: 'targeted_practice', next_action: 'transfer_check', next_question: { ...transfer, id: 'stale-question' } };
  const view = getTransferPresentation(session, [], oldResponse);
  assert.equal(view.question, transfer);
  assert.equal(view.result, null);
  assert.equal(view.passed, false);
  assert.equal(view.canDispatch, false);
  assert.equal(getTransferPresentation({ ...session, status: 'intervening', current_question: { ...transfer, question_role: 'targeted_practice' } }, [], oldResponse).question, null);
});

test('an evaluated transfer is not shown as an unanswered task; dispatch needs backend permission', () => {
  const attempts = [{ question_id: transfer.id }];
  assert.equal(getTransferPresentation(session, attempts, null).question, null);
  assert.equal(getTransferPresentation(session, attempts, null).canDispatch, false);
  assert.equal(getTransferPresentation({ ...session, can_dispatch_transfer: true }, attempts, null).canDispatch, true);
  assert.equal(getTransferPresentation({ ...session, status: 'completed', can_dispatch_transfer: true }, attempts, null).canDispatch, false);
});

test('practice success and failed/old-question transfer never imply mastery', () => {
  for (const result of [
    { question_role: 'targeted_practice', is_correct: true, next_action: 'transfer_check' },
    { question_role: 'transfer_check', is_correct: false, next_action: 'transfer_failed_needs_practice', knowledge_state_status: 'needs_practice' },
    { question_role: 'transfer_check', is_correct: true, next_action: 'transfer_retry_blocked', knowledge_state_status: 'needs_practice' },
    { question_role: 'transfer_check', is_correct: false, next_action: 'mastery_achieved', knowledge_state_status: 'stable' },
  ]) assert.equal(getTransferPresentation(session, [], result).passed, false);
  const verified = { question_role: 'transfer_check', is_correct: true, next_action: 'mastery_achieved', knowledge_state_status: 'stable' };
  assert.equal(getTransferPresentation(session, [], verified).passed, true);
  assert.match(describeNextAction(verified.next_action).description, /不代表长期保持/);
  assert.match(describeNextAction('transfer_unavailable').description, /保留不确定性/);
});

test('refresh restores the server evaluation, case and current transfer without local progression', async () => {
  const evaluation = { attempt_id: 'a-practice', question_role: 'targeted_practice', is_correct: true, next_action: 'transfer_check', diagnostic_case_id: 'case-real' };
  globalThis.fetch = async (url) => String(url).endsWith('/attempts') ? json([{ id: 'a-practice', question_id: 'practice' }]) : json({ ...session, latest_attempt_result: evaluation });
  const restored = await restoreSessionFromServer(session.id, new AbortController().signal);
  assert.deepEqual(restored.session.latest_attempt_result, evaluation);
  assert.equal(restored.session.active_diagnostic_case_id, 'case-real');
  assert.equal(getTransferPresentation(restored.session, restored.attempts, restored.session.latest_attempt_result).question.id, transfer.id);
});

test('pending attempt survives a refresh with the original payload and frozen idempotency key', () => {
  const storage = memoryStorage();
  const intent = prepareAttemptIntent(null, session.id, transfer.id, 'a careful answer');
  storePendingAttempt(storage, intent);
  const recovered = readPendingAttempt(storage, session.id);
  assert.deepEqual(recovered.payload, intent.payload);
  assert.equal(Object.isFrozen(recovered.payload), true);
  assert.throws(() => prepareAttemptIntent(recovered, session.id, transfer.id, 'different answer'), { code: 'PENDING_SUBMISSION_EXISTS' });
  assert.equal(readPendingAttempt(storage, 'another-session'), null);
  clearPendingAttempt(storage, session.id);
  assert.equal(readPendingAttempt(storage, session.id), null);
});

test('lost HTTP response can be retried after refresh without changing the learner intent', async () => {
  const storage = memoryStorage();
  const intent = prepareAttemptIntent(null, session.id, transfer.id, 'answer for this transfer');
  storePendingAttempt(storage, intent);
  const sent = [];
  const serverResponse = { attempt_id: 'persisted-attempt', session_id: session.id, question_id: transfer.id, question_role: 'transfer_check', is_correct: false, next_action: 'transfer_failed_needs_practice', diagnostic_case_id: 'case-real' };
  globalThis.fetch = async (_url, init) => {
    sent.push(JSON.parse(init.body));
    if (sent.length === 1) throw new TypeError('Response was lost after commit');
    return json(serverResponse);
  };
  await assert.rejects(submitAttempt(intent.sessionId, intent.payload), { code: 'NETWORK_ERROR' });
  const recovered = readPendingAttempt(storage, session.id);
  const result = await submitAttempt(recovered.sessionId, recovered.payload);
  assert.deepEqual(sent[0], sent[1]);
  assert.deepEqual(result, serverResponse);
  assert.equal(getTransferPresentation(session, [{ question_id: transfer.id }], result).passed, false);
});
