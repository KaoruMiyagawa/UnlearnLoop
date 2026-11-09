import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { resolveWorkspaceFromPath } from '../src/app-shell/navigation.ts';

test('review route is distinct from the learner profile route', () => {
  assert.equal(resolveWorkspaceFromPath('/review'), 'review');
  assert.equal(resolveWorkspaceFromPath('/profile'), 'profile');
});

test('real review and profile pages use server resources and keep demo data out', async () => {
  const review = await readFile(new URL('../src/review-workspace/FocusReviewWorkspace.tsx', import.meta.url), 'utf8');
  const profile = await readFile(new URL('../src/profile-workspace/FocusProfileWorkspace.tsx', import.meta.url), 'utf8');
  const homeEntry = await readFile(new URL('../src/review-workspace/ReviewHomeEntry.tsx', import.meta.url), 'utf8');

  assert.match(review, /startReview\(item\.id, LEARNER_ID\)/);
  assert.match(review, /item\.is_due/);
  assert.match(review, /submitAttempt\(intent\.sessionId, intent\.payload\)/);
  assert.match(review, /PENDING_REVIEW_ANSWER_KEY/);
  assert.doesNotMatch(review, /completeReview\(|INITIAL_DECISION_TIMELINE|stage5WorkbenchModel/);
  assert.match(profile, /listKnowledgeStates\(LEARNER_ID/);
  assert.match(profile, /listLearningHistory\(LEARNER_ID/);
  assert.match(profile, /尚未证明长期保持/);
  assert.doesNotMatch(profile, /INITIAL_TOPIC_MASTERY_MATRIX|stage5WorkbenchModel/);
  assert.match(homeEntry, /listReviews\(\{ learner_id: LEARNER_ID, status: 'pending' \}/);
  assert.match(homeEntry, /is_due === true/);
});
