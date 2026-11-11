import assert from 'node:assert/strict';
import test from 'node:test';
import { evidenceTimeline, isVerifiedRetention, knowledgeStatusLabel, readAnswerDraft, reviewsForSession, storeAnswerDraft } from '../src/learning-workspace/errorDna.ts';

const session = { id: 'origin', learner_id: 'learner', topic_id: 'reading' };
const review = (id, source, target, fields = {}) => ({
  id, learner_id: session.learner_id, topic_id: session.topic_id,
  session_id: source, review_session_id: target, status: 'pending', ...fields,
});

test('review lineage follows successive review sessions and excludes other sessions, topics and learners', () => {
  const items = [
    review('later', 'review-session', 'second-review'),
    review('other', 'other-origin', 'other-review'),
    review('first', 'origin', 'review-session'),
    review('other-topic', 'origin', 'review-session', { topic_id: 'elsewhere' }),
    review('other-learner', 'origin', 'review-session', { learner_id: 'someone' }),
  ];
  assert.deepEqual(reviewsForSession(session, items).map(item => item.id), ['first', 'later']);
});

test('timeline sorts real attempts and reviews without treating a remedial pass as retention', () => {
  const passed = { status: 'completed', is_correct: true, retention_verified: true };
  const reviews = [
    review('future', 'origin', null),
    review('retained', 'origin', 'review-session', { ...passed, attempt_id: 'r1', submitted_at: '2026-11-13T10:00:00Z' }),
    review('practice', 'origin', 'second-review', { ...passed, retention_verified: false, attempt_id: 'r2', submitted_at: '2026-11-14T10:00:00Z' }),
    review('failed', 'origin', 'third-review', { ...passed, is_correct: false, retention_verified: false, attempt_id: 'r3', submitted_at: '2026-11-15T10:00:00Z' }),
  ];
  const attempts = [
    { id: 'transfer', session_id: 'origin', question_role: 'transfer_check', is_correct: true, submitted_at: '2026-11-11T10:00:00Z' },
    { id: 'initial', session_id: 'origin', question_role: 'initial', is_correct: false, submitted_at: '2026-11-11T09:00:00Z' },
    { id: 'unrelated', session_id: 'another-session' },
  ];
  const events = evidenceTimeline(session.id, attempts, reviews);
  assert.deepEqual(events.map(event => event.id), ['initial', 'transfer', 'r1', 'r2', 'r3']);
  assert.equal(events[2].result, '本次保持验证通过');
  assert.equal(events[3].result, '复习通过，未取得保持证据');
  assert.equal(events[4].result, '复习未通过');
  assert.equal(isVerifiedRetention({ ...passed, attempt_id: null }), false);
  assert.equal(knowledgeStatusLabel('transfer_verified'), '独立迁移已通过');
  assert.equal(knowledgeStatusLabel('stable'), '当前掌握状态稳定');
});

test('drafts restore by session and question and clearing one preserves the others', () => {
  const data = new Map();
  const storage = { getItem: key => data.get(key), setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
  storeAnswerDraft(storage, 'a', 'one', 'NOT GIVEN');
  storeAnswerDraft(storage, 'a', 'two', 'B');
  storeAnswerDraft(storage, 'b', 'one', 'TRUE');
  assert.equal(readAnswerDraft(storage, 'a', 'one'), 'NOT GIVEN');
  storeAnswerDraft(storage, 'a', 'one', '');
  assert.equal(readAnswerDraft(storage, 'a', 'one'), '');
  assert.equal(readAnswerDraft(storage, 'a', 'two'), 'B');
  assert.equal(readAnswerDraft(storage, 'b', 'one'), 'TRUE');
});
