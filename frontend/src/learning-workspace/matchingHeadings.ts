import type { MatchingHeadingsGroup, SanitizedQuestion, StructuredAnswer } from '../api/types.ts';

export function headingGroup(question: SanitizedQuestion | null | undefined): MatchingHeadingsGroup | null {
  return question?.question_type === 'matching_headings' && question.group_version_id
    && question.group_display?.question_type === 'matching_headings' ? question.group_display : null;
}

export function validHeadingSelections(group: MatchingHeadingsGroup, selections: StructuredAnswer): StructuredAnswer {
  const options = new Set(group.options.map(option => option.id));
  const used = new Set<string>();
  const entries: [string, string][] = [];
  for (const item of group.items) {
    if (!Object.prototype.hasOwnProperty.call(selections, item.id)) continue;
    const selected = selections[item.id];
    if (!options.has(selected) || (!group.allow_reuse && used.has(selected))) continue;
    entries.push([item.id, selected]);
    used.add(selected);
  }
  return Object.fromEntries(entries);
}

const draftKey = (sessionId: string, questionId: string, version: string) =>
  `verbatrail.heading-draft.v1:${JSON.stringify([sessionId, questionId, version])}`;

export function readHeadingDraft(
  storage: Pick<Storage, 'getItem'>, sessionId: string, question?: SanitizedQuestion | null,
): StructuredAnswer {
  const group = headingGroup(question);
  if (!group || !question?.group_version_id) return {};
  try {
    const raw: unknown = JSON.parse(storage.getItem(draftKey(sessionId, question.id, question.group_version_id)) ?? 'null');
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) return validHeadingSelections(group, raw as StructuredAnswer);
  } catch {
    // A malformed local draft cannot be used to submit.
  }
  return {};
}

export function storeHeadingDraft(
  storage: Pick<Storage, 'setItem' | 'removeItem'>,
  sessionId: string, questionId: string, version: string, selections: StructuredAnswer,
) {
  const key = draftKey(sessionId, questionId, version);
  if (Object.keys(selections).length) storage.setItem(key, JSON.stringify(selections));
  else storage.removeItem(key);
}
