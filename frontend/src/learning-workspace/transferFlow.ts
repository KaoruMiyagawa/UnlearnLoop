import type { AttemptResult, AttemptSummary, SessionDetail } from '../api/types.ts';

/** A projection of server facts, not a second learning state machine. */
export function getTransferPresentation(session: SessionDetail | null, attempts: AttemptSummary[], latestResult: AttemptResult | null) {
  const assigned = session?.current_question;
  const question = session && session.status === 'transfer_checking'
    && assigned?.question_role === 'transfer_check'
    && !attempts.some((attempt) => attempt.question_id === assigned.id) ? assigned : null;
  const result = latestResult?.question_role === 'transfer_check' ? latestResult : null;
  return {
    question,
    result,
    canDispatch: session?.status === 'transfer_checking' && session.can_dispatch_transfer === true && !question,
    passed: result?.is_correct === true && ((result.next_action === 'mastery_achieved' && result.knowledge_state_status === 'stable') || (result.next_action === 'transfer_verified' && result.knowledge_state_status === 'transfer_verified')),
  };
}
