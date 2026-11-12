import type { EvidenceValidityStatus } from './api/types';

export function evidenceValidityLabel(status: EvidenceValidityStatus): string {
  switch (status) {
    case 'invalidated': return '已失效';
    case 'review_required': return '待核实';
    case 'eligible': return '可用于当前判断';
  }
}

export function learnerEvidenceValidityReason(status: EvidenceValidityStatus, reason?: string | null): string {
  if (reason?.includes('This ReviewItem depends on an invalidated transfer or review result')) {
    return '这项复习依赖的迁移或前序复习题目版本已失效。原始作答和当时评分仍保留，但不再作为当前保持证据。';
  }
  if (reason?.includes('immutable task version is invalidated')) {
    return '这次历史作答使用的题目版本已确认存在评分问题。原始作答和当时评分仍保留，但不再用于判断当前能力。';
  }
  if (reason?.includes('lacks a resolvable immutable group version')) {
    return '这条历史作答缺少可核对的题组版本来源。完成来源核实前，不用于判断当前能力。';
  }
  if (reason?.includes('Historical Matching Headings transfer evidence was invalidated')) {
    return '历史迁移证据使用了已失效或待核实的题目版本。当前状态已按仍有效的证据重新计算；这不代表学习者能力下降。';
  }
  if (reason) return reason;
  return status === 'invalidated'
    ? '这条历史记录目前不作为当前能力或保持证据。'
    : status === 'review_required'
      ? '这条历史记录的题目版本来源尚待核实。'
      : '这条证据可以用于当前学习状态判断。';
}
