import type { AttemptSummary, ReviewItem, SessionDetail } from '../api/types.ts';

const stageLabels: Record<string, string> = {
  initial: '初始作答',
  diagnostic_followup: '诊断追问',
  targeted_practice: '针对性训练',
  transfer_check: '独立迁移',
  review: '延迟复习',
};

export function questionRoleLabel(role: string): string {
  return stageLabels[role] ?? '作答';
}

export function questionTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    short_text: '简答题', code_trace: '代码推演', code_writing: '代码编写', multiple_choice: '选择题',
    matching_headings: 'Matching Headings · 段落标题匹配',
  };
  return labels[type] ?? '练习题';
}

const diagnosticTranslations = new Map([
  ['No reviewed independent transfer group matches the supported diagnosis; verification remains pending.', '暂无符合当前诊断目标的独立迁移文章，本次迁移仍未验证。'],
  ['Deterministic rule evaluation; not proof of a unique misconception or long-term retention.', '按题目规则评判，仅反映本次作答。错误原因仍需验证，长期保持需另行复习。'],
  ['Deterministic local rubric rule check (heuristic, non-conclusive)', '按本地评分规则检查，结果仅供判断。'],
  ['Agent structured evidence analysis (heuristic confidence, not statistical probability)', '模型按证据分析，支持程度为定性判断。'],
  ['Initial output correct but trace not provided; checking mental model.', '结果正确，仍需补充推理过程。'],
  ['Delayed review answer was incorrect; diagnosis is needed before another intervention.', '延迟复习未通过，需要补充证据再安排训练。'],
]);

/** Keep unknown technical remarks available in the audit disclosure. */
export function learnerDiagnosticText(value?: string | null): string | undefined {
  const text = value?.trim();
  if (!text) return undefined;
  const translation = diagnosticTranslations.get(text);
  if (translation) return translation;
  if (!/\p{Script=Han}/u.test(text)) return undefined;
  return text.replace(/TFNG v1(?: 规则)?/g, '判断题规则')
    .replace(/true_false_not_given/g, '判断题逻辑混淆')
    .replace(/passage_location/g, '原文定位困难');
}

export function knowledgeStatusLabel(status?: string | null): string {
  switch (status) {
    case 'needs_practice': return '需要继续练习';
    case 'transfer_verified': return '独立迁移已通过';
    case 'stable': return '当前掌握状态稳定';
    case 'needs_diagnosis': return '需要进一步诊断';
    case 'insufficient_evidence': return '证据不足';
    default: return '暂无知识状态';
  }
}

/** Follow persisted review sessions without including another session on the same topic. */
export function reviewsForSession(session: Pick<SessionDetail, 'id' | 'learner_id' | 'topic_id'>, items: ReviewItem[]): ReviewItem[] {
  const matching = items.filter(item => item.learner_id === session.learner_id && item.topic_id === session.topic_id);
  const sessionIds = new Set([session.id]);
  const linked = new Map<string, ReviewItem>();
  // A subsequent review points to the preceding review session.
  while (true) {
    const size = linked.size;
    for (const item of matching) {
      if (linked.has(item.id)) continue;
      if ((item.session_id && sessionIds.has(item.session_id)) || item.review_session_id === session.id) {
        linked.set(item.id, item);
        if (item.review_session_id) sessionIds.add(item.review_session_id);
      }
    }
    if (linked.size === size) return [...linked.values()];
  }
}

export function isVerifiedRetention(item: ReviewItem): boolean {
  return item.status === 'completed' && Boolean(item.attempt_id)
    && item.is_correct === true && item.retention_verified === true;
}

export function evidenceTimeline(sessionId: string, attempts: AttemptSummary[], reviews: ReviewItem[]) {
  const reviewAttempts = new Set(reviews.map(item => item.attempt_id).filter(Boolean));
  const events = attempts.filter(attempt => attempt.session_id === sessionId && !reviewAttempts.has(attempt.id)).map(attempt => ({
    id: attempt.id,
    title: questionRoleLabel(attempt.question_role),
    time: attempt.submitted_at,
    result: attempt.group_evaluation?.outcome === 'partial'
      ? `部分正确 · ${attempt.group_evaluation.correct_count}/${attempt.group_evaluation.total_count}`
      : attempt.is_correct === true ? '本题通过' : attempt.is_correct === false ? '本题未通过' : '尚待评价',
    summary: attempt.evaluation_summary,
    answer: attempt.structured_answer ? Object.entries(attempt.structured_answer).map(([item, heading]) => `${item} → ${heading}`).join(' · ') : attempt.submitted_answer,
    questionId: attempt.question_id,
  }));
  for (const item of reviews) {
    if (item.status !== 'completed' || !item.attempt_id) continue;
    const result = isVerifiedRetention(item) ? '本次保持验证通过'
      : item.is_correct === false ? '复习未通过'
      : item.is_correct === true ? '复习通过，未取得保持证据' : '尚待评价';
    events.push({ id: item.attempt_id, title: '延迟复习', time: item.submitted_at ?? item.completed_at ?? '',
      result, summary: item.evaluation_summary, answer: '', questionId: item.question_id ?? '' });
  }
  return events.sort((a, b) => (Date.parse(a.time) || 0) - (Date.parse(b.time) || 0));
}

const draftKey = (sessionId: string, questionId: string) => `unlearnloop.real.answer-draft.v1:${sessionId}:${questionId}`;

export function readAnswerDraft(storage: Pick<Storage, 'getItem'>, sessionId: string, questionId?: string | null): string {
  return questionId ? storage.getItem(draftKey(sessionId, questionId)) ?? '' : '';
}

export function storeAnswerDraft(storage: Pick<Storage, 'setItem' | 'removeItem'>, sessionId: string, questionId: string, answer: string): void {
  const key = draftKey(sessionId, questionId);
  if (answer) storage.setItem(key, answer);
  else storage.removeItem(key);
}
