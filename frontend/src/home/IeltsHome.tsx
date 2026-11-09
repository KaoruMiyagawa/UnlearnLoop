import React, { useEffect, useState } from 'react';
import { ApiClientError } from '../api/client';
import { getExamCatalog, getExamProfile, saveExamProfile } from '../api/exams';
import type { ExamCatalogEntry, ExamPreparationProfile } from '../api/types';
import type { WorkspaceId } from '../app-shell/navigation';

const learnerId = 'default_learner';
const skills = ['listening', 'reading', 'writing', 'speaking'] as const;
const skillNames = { listening: 'Listening', reading: 'Reading', writing: 'Writing', speaking: 'Speaking' };

export const IeltsHome: React.FC<{ onNavigate: (workspace: WorkspaceId) => void }> = ({ onNavigate }) => {
  const [catalog, setCatalog] = useState<ExamCatalogEntry[]>([]);
  const [profile, setProfile] = useState<ExamPreparationProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getExamCatalog(controller.signal), getExamProfile(learnerId, controller.signal)])
      .then(([items, current]) => { if (!controller.signal.aborted) { setCatalog(items); setProfile(current); } })
      .catch((e: unknown) => { if (!controller.signal.aborted) setError(e instanceof ApiClientError ? `${e.code}：${e.message}` : '暂时无法读取服务端学习目标。'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  const update = async (variant: 'academic' | 'general_training') => {
    if (!profile) return;
    setSaving(true); setError('');
    try { setProfile(await saveExamProfile({ exam_variant: variant, target_overall_band: profile.target_overall_band ?? 8, target_skill_bands: profile.target_skill_bands ?? Object.fromEntries(skills.map(s => [s, 8])), exam_date: profile.exam_date }, learnerId)); }
    catch (e) { setError(e instanceof ApiClientError ? `${e.code}：${e.message}` : '保存失败，请重试。'); }
    finally { setSaving(false); }
  };
  const setTarget = async (field: 'overall' | typeof skills[number], value: number) => {
    if (!profile || !profile.target_skill_bands) return;
    setSaving(true); setError('');
    const target_skill_bands = field === 'overall' ? profile.target_skill_bands : { ...profile.target_skill_bands, [field]: value };
    try { setProfile(await saveExamProfile({ exam_variant: profile.exam_variant, target_overall_band: field === 'overall' ? value : profile.target_overall_band ?? 8, target_skill_bands, exam_date: profile.exam_date }, learnerId)); }
    catch (e) { setError(e instanceof ApiClientError ? `${e.code}：${e.message}` : '保存失败，请重试。'); }
    finally { setSaving(false); }
  };
  const setExamDate = async (exam_date: string) => {
    if (!profile || !profile.target_skill_bands) return;
    setSaving(true); setError('');
    try { setProfile(await saveExamProfile({ exam_variant: profile.exam_variant as 'academic' | 'general_training', target_overall_band: profile.target_overall_band ?? 8, target_skill_bands: profile.target_skill_bands, exam_date: exam_date || null }, learnerId)); }
    catch (e) { setError(e instanceof ApiClientError ? `${e.code}：${e.message}` : '保存失败，请重试。'); }
    finally { setSaving(false); }
  };
  const available = catalog.filter(item => item.availability === 'available');
  const planned = catalog.filter(item => item.availability === 'planned');
  return <div className="ielts-home">
    <p className="eyebrow">VERBATRAIL · 暂定名称</p>
    <h1>让每一次练习，都留下进步的证据。</h1>
    <p className="home-intro">从真实阅读任务开始。系统会记录作答、检查证据，并在证据不足时继续追问。</p>
    {loading ? <p role="status">正在读取已保存的考试目标…</p> : error && !profile ? <div role="alert">{error} <button onClick={() => location.reload()}>重试</button></div> : profile && <>
      <section className="exam-goal" aria-labelledby="exam-goal-heading">
        <div><p className="eyebrow">你的备考方向</p><h2 id="exam-goal-heading">选择考试类型</h2></div>
        <div className="exam-choice-row">{available.map(item => <button key={item.code} className={`exam-choice ${profile.selection_persisted && profile.exam_variant === item.code ? 'selected' : ''}`} onClick={() => update(item.code as 'academic' | 'general_training')} disabled={saving} aria-pressed={profile.selection_persisted && profile.exam_variant === item.code}>{item.label}<span>{item.code === 'academic' ? '学术学习与高等教育' : '日常、工作与移民场景'}</span></button>)}</div>
        {!profile.selection_persisted && <p className="goal-hint">请选择 Academic 或 General Training 以保存考试模式，然后开始阅读训练。</p>}
        <div className="goal-line"><label>目标总分 <select aria-label="目标总分" value={profile.target_overall_band ?? 8} disabled={saving} onChange={e => void setTarget('overall', Number(e.target.value))}>{Array.from({ length: 17 }, (_, i) => 1 + i * .5).map(v => <option key={v} value={v}>{v.toFixed(1)}</option>)}</select></label>{skills.map(skill => <label key={skill}>{skillNames[skill]} <select aria-label={`${skillNames[skill]}目标分`} value={profile.target_skill_bands?.[skill] ?? 8} disabled={saving} onChange={e => void setTarget(skill, Number(e.target.value))}>{Array.from({ length: 17 }, (_, i) => 1 + i * .5).map(v => <option key={v} value={v}>{v.toFixed(1)}</option>)}</select></label>)}<span>当前水平：待评估</span><label>考试日期 <input aria-label="考试日期" type="date" value={profile.exam_date ?? ''} disabled={saving} onChange={e => void setExamDate(e.target.value)} /></label></div>
        {error && <p role="alert" className="home-error">{error}</p>}
      </section>
      <section className="skill-section"><div className="section-heading"><div><p className="eyebrow">TODAY'S PRACTICE</p><h2>从哪项能力开始？</h2></div><button className="text-link" onClick={() => onNavigate('profile')}>查看学习档案 →</button></div>
        <div className="skill-grid">{skills.map((skill, i) => <button key={skill} className={`skill-entry ${skill === 'reading' && profile.selection_persisted ? 'ready' : 'planned'}`} onClick={() => skill === 'reading' && profile.selection_persisted && onNavigate('learning')} disabled={skill !== 'reading' || !profile.selection_persisted}><span className="skill-number">0{i + 1}</span><strong>{skillNames[skill]}</strong><span>{skill === 'reading' ? profile.selection_persisted ? '开始原创阅读练习' : '先保存考试模式' : '计划中'}</span><b aria-hidden="true">{skill === 'reading' && profile.selection_persisted ? '→' : '·'}</b></button>)}</div>
      </section>
      <section className="planned-practice" aria-label="计划中的语言训练"><h2>基础能力训练</h2><div>{['Vocabulary · 词汇', 'Grammar · 语法', 'Mock Tests · 模拟考试'].map(label => <button key={label} type="button" disabled>{label}<span>计划中</span></button>)}</div></section>
      <div className="secondary-links"><button onClick={() => onNavigate('review')}>Review · 复习</button><button onClick={() => onNavigate('profile')}>Learning Profile · 学习档案</button></div>
      <section className="planned-exams"><h2>逐步支持更多考试</h2><p>Academic 与 General Training 的听力、口语共享能力模块；阅读与写作按考试版本区分。未开放功能不会进入模拟页面。</p><div>{planned.map(item => <span key={item.code}>{item.label} · 计划中</span>)}</div></section>
    </>}
  </div>;
};
