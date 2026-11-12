import { useId } from 'react';
import type { AttemptResult, SanitizedQuestion, StructuredAnswer } from '../api/types';
import { questionRoleLabel } from './errorDna';
import { headingGroup, validHeadingSelections } from './matchingHeadings';
import './matchingHeadings.css';

function paragraphLabel(index: number): string {
  return index < 26 ? String.fromCharCode(65 + index) : String(index + 1);
}

interface QuestionProps {
  question: SanitizedQuestion;
  selections: StructuredAnswer;
  onChange: (selections: StructuredAnswer) => void;
  onSubmit: () => void;
  submitLabel: string;
  focusId: string;
  busy: boolean;
  locked?: boolean;
}

export function MatchingHeadingsQuestion({
  question, selections, onChange, onSubmit, submitLabel, focusId, busy, locked,
}: QuestionProps) {
  const id = useId();
  const group = headingGroup(question);
  if (!group) return <p role="alert" className="wb-alert danger">题组内容或派发版本缺失。请重新读取服务端任务。</p>;
  const selected = validHeadingSelections(group, selections);
  const answered = Object.keys(selected).length;
  const remaining = group.items.length - answered;
  return <section className="mh-question" aria-labelledby={`${id}-title`}>
    <header className="mh-header">
      <p className="focus-eyebrow">{questionRoleLabel(question.question_role)} · Matching Headings</p>
      <h2 id={`${id}-title`}>匹配段落标题</h2>
      <p lang="en">{question.prompt_text}</p>
    </header>
    <div className="mh-grid">
      <article className="mh-passage" lang="en" aria-labelledby={`${id}-passage`}>
        <h3 id={`${id}-passage`}>{group.passage.title}</h3>
        {group.passage.paragraphs.map((paragraph, index) => <div key={paragraph.id} id={`${id}-paragraph-${index}`} className="mh-paragraph">
          <strong aria-label={`Paragraph ${paragraphLabel(index)}`}>{paragraphLabel(index)}</strong>
          <p>{paragraph.text}</p>
        </div>)}
        <a className="mh-to-answer" href={`#${id}-answer`} lang="zh">前往作答</a>
      </article>
      <form id={`${id}-answer`} className="mh-answer" onSubmit={(event) => {
        event.preventDefault();
        if (!remaining && !busy && !locked) onSubmit();
      }} aria-busy={busy}>
        <h3>标题选项</h3>
        <p id={`${id}-instructions`}>{group.allow_reuse ? '标题可以重复使用。' : '每个标题最多使用一次。'}有些标题可能无需使用。</p>
        <ul className="mh-options" lang="en">
          {group.options.map(option => <li key={option.id}><strong>{option.id}</strong><span>{option.text}</span></li>)}
        </ul>
        <fieldset disabled={busy || locked}>
          <legend>逐段选择标题</legend>
          {group.items.map((item, index) => {
            const paragraphIndex = group.passage.paragraphs.findIndex(p => p.id === item.paragraph_id);
            const fieldId = index === 0 ? focusId : `${focusId}-${index}`;
            const value = Object.prototype.hasOwnProperty.call(selected, item.id) ? selected[item.id] : '';
            const chosen = group.options.find(option => option.id === value);
            return <div className="mh-field" key={item.id} data-item-id={item.id}>
              <div className="mh-field-label"><label htmlFor={fieldId}>段落 {paragraphLabel(paragraphIndex)} 的标题</label>
                <a href={`#${id}-paragraph-${paragraphIndex}`}>定位原文</a></div>
              <select id={fieldId} value={value} required aria-describedby={`${id}-instructions`} onChange={(event) => {
                onChange(validHeadingSelections(group, { ...selected, [item.id]: event.target.value }));
              }}>
                <option value="">选择标题</option>
                {group.options.map(option => <option key={option.id} lang="en" value={option.id}
                  disabled={!group.allow_reuse && option.id !== value && Object.values(selected).includes(option.id)}>
                  {option.id} · {option.text}
                </option>)}
              </select>
              {chosen && <small className="mh-selected" lang="en">{chosen.text}</small>}
            </div>;
          })}
        </fieldset>
        <p className="mh-progress" role="status">已完成 {answered}/{group.items.length} 段{remaining ? ` · 还有 ${remaining} 段必答` : ''}</p>
        <button type="submit" className="wb-btn primary" disabled={Boolean(remaining || busy || locked)}>{busy ? '正在处理…' : submitLabel}</button>
      </form>
    </div>
  </section>;
}

const outcomeLabels = { correct: '全部正确', partial: '部分正确', incorrect: '全部错误' };

export function MatchingHeadingsResult({ result, question }: {
  result: AttemptResult;
  question?: SanitizedQuestion | null;
}) {
  const evaluation = result.group_evaluation;
  if (!evaluation) return null;
  const group = question?.group_version_id === evaluation.group_version_id ? headingGroup(question) : null;
  return <section className="mh-result" aria-label="题组逐项评分">
    <p><strong>{evaluation.correct_count}/{evaluation.total_count} · {outcomeLabels[evaluation.outcome]}</strong></p>
    <ul>
      {Object.entries(evaluation.correct_by_item).map(([itemId, correct]) => {
        const item = group?.items.find(item => item.id === itemId);
        const index = item ? group?.passage.paragraphs.findIndex(p => p.id === item.paragraph_id) : undefined;
        return <li key={itemId}><span>{index !== undefined && index >= 0 ? `段落 ${paragraphLabel(index)}` : `题项 ${itemId}`}</span><strong>{correct ? '正确' : '错误'}</strong></li>;
      })}
    </ul>
    <details className="focus-disclosure"><summary>评分来源</summary><div className="focus-disclosure-content">
      <p>规则评分 · 作答 <code>{result.attempt_id}</code></p>
      <p>题组版本 <code>{evaluation.group_version_id}</code> · 评分规则版本 <code>{evaluation.evaluation_rule_version}</code></p>
    </div></details>
  </section>;
}
