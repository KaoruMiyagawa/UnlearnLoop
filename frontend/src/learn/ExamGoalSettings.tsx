import { useEffect, useState } from 'react';
import { ApiClientError } from '../api/client';
import { getExamCatalog, getExamProfile, saveExamProfile } from '../api/exams';
import type { ExamCatalogEntry, ExamPreparationProfile, ExamPreparationProfileUpdate } from '../api/types';
import { skills } from './skills';

const learnerId = 'default_learner';
const bandOptions = Array.from({ length: 17 }, (_, index) => (1 + index * 0.5).toFixed(1));

function BandGoal({ label, value, disabled, onChange }: {
  label: string;
  value?: number | null;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return <label>
    {label}
    <select value={value?.toFixed(1) ?? ''} disabled={disabled} onChange={event => onChange(Number(event.target.value))}>
      <option value="" disabled>未设定</option>
      {bandOptions.map(band => <option key={band} value={band}>{band}</option>)}
    </select>
  </label>;
}

export function ExamGoalSettings() {
  const [catalog, setCatalog] = useState<ExamCatalogEntry[]>([]);
  const [profile, setProfile] = useState<ExamPreparationProfile | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getExamCatalog(controller.signal), getExamProfile(learnerId, controller.signal)])
      .then(([items, current]) => {
        if (controller.signal.aborted) return;
        setCatalog(items);
        setProfile(current);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof ApiClientError ? cause.message : '暂时无法读取服务端学习目标。');
        }
      });
    return () => controller.abort();
  }, [loadAttempt]);

  const save = async (update: Partial<ExamPreparationProfileUpdate>) => {
    if (!profile || saving) return;
    setSaving(true);
    setError('');
    try {
      setProfile(await saveExamProfile({
        exam_variant: profile.exam_variant,
        target_overall_band: profile.target_overall_band ?? undefined,
        target_skill_bands: profile.target_skill_bands ?? undefined,
        exam_date: profile.exam_date,
        ...update,
      }, learnerId));
    } catch (cause) {
      setError(cause instanceof ApiClientError ? cause.message : '保存失败，请重试。');
    } finally {
      setSaving(false);
    }
  };

  return <section className="exam-goal" aria-labelledby="exam-goal-heading">
    <header className="exam-goal-header">
      <h2 id="exam-goal-heading">IELTS 备考目标</h2>
      <span className="focus-state-tag">当前水平 · {profile?.actual_level_status === 'assessed' ? '已评估' : '未评估'}</span>
    </header>
    {!profile && !error && <p className="goal-hint" role="status">正在读取已保存的考试目标…</p>}
    {error && <p className="home-error" role="alert">{error}</p>}
    {!profile && error && <button className="focus-button-secondary" type="button" onClick={() => {
      setError('');
      setLoadAttempt(attempt => attempt + 1);
    }}>重试读取</button>}
    {profile && <>
      {!profile.selection_persisted && <p className="goal-hint">首次开始阅读前，请保存考试类型。</p>}
      <div className="exam-choice-row" role="group" aria-label="考试类型">
        {catalog.filter(item => item.availability === 'available').map(item => {
          const selected = profile.selection_persisted && profile.exam_variant === item.code;
          return <button
            key={item.code}
            type="button"
            className={`exam-choice${selected ? ' selected' : ''}`}
            disabled={saving}
            aria-pressed={selected}
            onClick={() => void save({ exam_variant: item.code })}
          >
            <strong lang="en">{item.label}</strong>
            <span>{item.code === 'academic' ? '学术学习与高等教育' : '日常、工作与移民场景'}</span>
          </button>;
        })}
      </div>
      {profile.selection_persisted && <details className="focus-disclosure exam-goal-details">
        <summary>目标分与考试日期</summary>
        <div className="goal-line">
          <BandGoal label="目标总分" value={profile.target_overall_band} disabled={saving} onChange={value => void save({ target_overall_band: value })} />
          {skills.map(skill => <BandGoal
            key={skill.id}
            label={`${skill.localizedLabel}目标分`}
            value={profile.target_skill_bands?.[skill.id]}
            disabled={saving}
            onChange={value => void save({ target_skill_bands: { ...profile.target_skill_bands, [skill.id]: value } })}
          />)}
          <label>
            考试日期
            <input type="date" value={profile.exam_date ?? ''} disabled={saving} onChange={event => void save({ exam_date: event.target.value || null })} />
          </label>
        </div>
      </details>}
    </>}
  </section>;
}
