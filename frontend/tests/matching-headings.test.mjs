import assert from 'node:assert/strict';
import test from 'node:test';
import { attemptContent, createAttemptSubmission } from '../src/api/sessions.ts';
import {
  acceptedGroupAttempt, prepareAttemptIntent, readPendingAttempt, storePendingAttempt,
} from '../src/learning-workspace/learningFlow.ts';
import {
  readHeadingDraft, storeHeadingDraft, validHeadingSelections,
} from '../src/learning-workspace/matchingHeadings.ts';

function memoryStorage() {
  const entries = new Map();
  return {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: key => entries.delete(key),
  };
}

const group = {
  question_type: 'matching_headings',
  allow_reuse: false,
  options: [{ id: 'i' }, { id: 'ii' }],
  items: [{ id: 'a' }, { id: 'b' }],
};
const question = { id: 'q', question_type: 'matching_headings', group_version_id: 'v1', group_display: group };

test('matching selections reject missing, unknown and reused choices', () => {
  assert.deepEqual(validHeadingSelections(group, { a: 'i', b: 'i', extra: 'ii' }), { a: 'i' });
  assert.deepEqual(validHeadingSelections(group, { a: '', b: 'unknown' }), {});
  assert.deepEqual(validHeadingSelections({ ...group, allow_reuse: true }, { a: 'i', b: 'i' }), { a: 'i', b: 'i' });
});

test('group drafts are scoped by session, question and immutable version', () => {
  const storage = memoryStorage();
  storeHeadingDraft(storage, 's', 'q', 'v1', { a: 'i' });
  storeHeadingDraft(storage, 's', 'q', 'v2', { a: 'ii' });
  assert.deepEqual(readHeadingDraft(storage, 's', question), { a: 'i' });
  assert.deepEqual(readHeadingDraft(storage, 's2', question), {});
  assert.deepEqual(readHeadingDraft(storage, 's', { ...question, id: 'q2' }), {});
  storeHeadingDraft(storage, 's', 'q', 'v1', {});
  assert.deepEqual(readHeadingDraft(storage, 's', question), {});
  assert.deepEqual(readHeadingDraft(storage, 's', { ...question, group_version_id: 'v2' }), { a: 'ii' });
});

test('structured requests freeze the selections and keep an order independent retry identity', () => {
  const input = { question_id: 'q', group_version_id: 'v1', structured_answer: { a: 'i', b: 'ii' } };
  const payload = createAttemptSubmission(input);
  input.structured_answer.a = 'ii';
  assert.ok(Object.isFrozen(payload.structured_answer));
  assert.equal(payload.structured_answer.a, 'i');
  assert.ok(!Object.hasOwn(payload, 'submitted_answer'));
  const storage = memoryStorage();
  storePendingAttempt(storage, { sessionId: 's', payload });
  const restored = readPendingAttempt(storage, 's');
  assert.deepEqual(restored.payload, payload);
  assert.ok(Object.isFrozen(restored.payload.structured_answer));
  const reordered = { group_version_id: 'v1', structured_answer: { b: 'ii', a: 'i' } };
  assert.equal(attemptContent({ question_id: 'q', ...reordered }), attemptContent(payload));
  assert.equal(prepareAttemptIntent(restored, 's', 'q', reordered), restored);
  assert.throws(() => prepareAttemptIntent(restored, 's', 'q', { ...reordered, group_version_id: 'v2' }), /幂等键|原作答/);
  assert.equal(acceptedGroupAttempt(restored, [{ session_id: 's', question_id: 'q', group_evaluation: { group_version_id: 'v2' } }]), false);
  assert.equal(acceptedGroupAttempt(restored, [{ session_id: 's', question_id: 'q', group_evaluation: { group_version_id: 'v1' } }]), true);
});
