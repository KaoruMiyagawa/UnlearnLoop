import { useCallback } from 'react';
import { getLearnerModel } from '../api/learnerModel';
import { useApiResource } from '../learning-workspace/useApiResource';

const names: Record<string, string> = { listening: 'Listening 听力', speaking: 'Speaking 口语', reading: 'Reading 阅读', writing: 'Writing 写作' };
const levels: Record<string, string> = { practice_activity: '练习记录', practice_performance: '练习表现', independent_transfer: '独立迁移', delayed_review: '延迟复习' };
const validity: Record<string, string> = { eligible: '有效', invalidated: '已失效', review_required: '待复核', not_evaluated: '未评价' };

export function LearnerOverview() {
  const load = useCallback((signal: AbortSignal) => getLearnerModel('default_learner', signal), []);
  const model = useApiResource(load);
  return <section className="focus-page-section" aria-labelledby="learner-model-title">
    <div className="focus-review-section-heading"><div><h2 id="learner-model-title">语言能力概览</h2><p>只展示已有记录和可追溯表现；学习目标不是当前能力。</p></div></div>
    {model.state.status === 'loading' && <div role="status" className="focus-notice neutral">正在读取能力记录…</div>}
    {model.state.status === 'error' && <div role="alert" className="focus-notice danger">能力记录读取失败。<button className="focus-button-quiet" onClick={() => void model.retry()}>重试</button></div>}
    {model.state.status === 'success' && <div className="focus-profile-list">{model.state.data.skills.map(skill => <article className="focus-profile-topic" key={skill.skill_id}>
      <div className="focus-profile-topic-heading"><h3>{names[skill.skill_id]}</h3><span className="focus-state-tag">{skill.has_learning_record ? '有学习记录' : '暂无学习记录'}</span></div>
      <p>{skill.assessment_status === 'observed' ? '已观察到具体练习表现；整体能力尚未评估。' : '能力未评估。'}</p>
      <p>证据：{skill.evidence_levels.map(level => levels[level]).join('、') || '暂无'}</p>
      {skill.limitations.map(item => <p className="focus-help" key={item}>{item}</p>)}
      {skill.evidence.length > 0 && <details className="focus-disclosure"><summary>查看来源与记录（{skill.evidence.length}）</summary><div className="focus-disclosure-content">{skill.evidence.map(e => <p key={`${e.evidence_source}-${e.evidence_reference}`}>{e.observation} · {validity[e.evidence_validity] || e.evidence_validity} · {e.evidence_source} / {e.evidence_reference} · {e.content_version || '版本未记录'} · {new Date(e.observed_at).toLocaleString('zh-CN')}</p>)}</div></details>}
    </article>)}</div>}
  </section>;
}
