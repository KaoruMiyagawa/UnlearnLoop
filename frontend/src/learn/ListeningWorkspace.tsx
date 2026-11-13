import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClientError } from '../api/client';
import { getListeningHistory, getListeningSession, startListeningSession, submitListeningSession, type ListeningHistory, type ListeningSession } from '../api/listening';
import type { WorkspaceId } from '../app-shell/navigation';

const SESSION_KEY = 'verbatrail.listening.active.v1';
const DRAFT_KEY = 'verbatrail.listening.draft.v1';
const LEARNER = 'default_learner';
export function ListeningWorkspace({ onNavigate }: { onNavigate: (workspace: WorkspaceId) => void }) {
  const [session, setSession] = useState<ListeningSession | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<ListeningHistory[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [audioError, setAudioError] = useState('');
  const audio = useRef<HTMLAudioElement>(null);
  const loadHistory = useCallback(() => { void getListeningHistory().then(setHistory).catch(() => setHistory([])); }, []);
  useEffect(() => {
    loadHistory();
    const saved = localStorage.getItem(SESSION_KEY);
    if (saved) void getListeningSession(saved).then(data => { setSession(data); setAnswers(data.status === 'completed' ? data.answers : JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}')); }).catch(() => { localStorage.removeItem(SESSION_KEY); });
  }, [loadHistory]);
  const begin = async () => { setBusy(true); setError(''); try { const data = await startListeningSession(LEARNER); setSession(data); setAnswers({}); localStorage.setItem(SESSION_KEY, data.session_id); localStorage.removeItem(DRAFT_KEY); } catch (e) { setError(e instanceof Error ? e.message : '无法开始练习。'); } finally { setBusy(false); } };
  const setAnswer = (id: string, value: string) => { const next = { ...answers, [id]: value }; setAnswers(next); localStorage.setItem(DRAFT_KEY, JSON.stringify(next)); };
  const submit = async () => { if (!session || session.status === 'completed') return; setBusy(true); setError(''); try { const data = await submitListeningSession(session.session_id, answers, `listen-${session.session_id}`); setSession(data); localStorage.removeItem(DRAFT_KEY); loadHistory(); } catch (e) { setError(e instanceof ApiClientError ? `${e.code} · ${e.message}` : '提交失败，请检查连接后重试。'); } finally { setBusy(false); } };
  const jumpTo = async (seconds: number) => { if (!audio.current) return; audio.current.currentTime = seconds; try { await audio.current.play(); } catch { setAudioError('浏览器未能播放音频，请检查音频文件或设备设置。'); } };
  const completed = session?.status === 'completed';
  const allAnswered = !!session && session.lesson.questions.every(q => !!answers[q.id]);
  return <main className="learn-page listening-page">
    <button className="focus-button-quiet learn-back-link" type="button" onClick={() => onNavigate('home')}>← 返回 Learn</button>
    <header className="focus-page-header"><span className="focus-state-tag learn-status-implemented">可练习 · 原创试用练习</span><h1 className="focus-page-title">Listening · 听力</h1><p className="focus-page-subtitle">第一套有限范围的原创 IELTS 风格听力练习。练习成绩仅描述本次作答。</p></header>
    {!session && <section className="focus-card focus-card-quiet listening-intro"><p>生活场景 · 学习技能讲座安排 · 约 64 秒 · 5 道选择题</p><p>先完整聆听，再作答。提交前不会显示答案或听力转写。</p><button type="button" className="wb-btn primary" onClick={() => void begin()} disabled={busy}>{busy ? '正在准备…' : '开始练习'}</button></section>}
    {error && <p role="alert" className="wb-alert danger">{error}</p>}
    {session && <>
      <section className="focus-card focus-card-quiet listening-audio" aria-label="听力音频播放器"><div><h2>{session.lesson.title}</h2><p>{session.lesson.scenario}</p></div><audio ref={audio} controls preload="metadata" src={session.lesson.audio_url} onError={() => setAudioError('音频文件无法加载。请重试；如果问题持续，请返回后再进入练习。')} onCanPlay={() => setAudioError('')} aria-label="英语听力音频"/><p className="listening-audio-note">{session.lesson.audio_source}</p>{audioError && <p role="alert" className="wb-alert danger">{audioError}</p>}</section>
      <section className="listening-questions" aria-label="听力题目">{session.lesson.questions.map(q => <fieldset className="focus-card focus-card-quiet listening-question" key={q.id}><legend>{q.number}. {q.prompt}</legend>{q.options.map(option => <label key={option} className="listening-option"><input type="radio" name={q.id} value={option} checked={answers[q.id] === option} disabled={completed} onChange={() => setAnswer(q.id, option)}/><span>{option}</span></label>)}{completed && <div className="listening-result"><strong>{session.results?.[q.number - 1]?.is_correct ? '回答正确' : `你的答案：${session.results?.[q.number - 1]?.submitted_answer}`}</strong><p>答案：{q.correct_answer}。{q.explanation}</p><button type="button" className="focus-button-quiet" onClick={() => void jumpTo(q.start_seconds ?? 0)}>↗ 听取 {q.start_seconds}–{q.end_seconds} 秒片段</button></div>}</fieldset>)}</section>
      {!completed ? <div className="listening-submit"><p aria-live="polite">草稿会保存在此浏览器，并在恢复本次练习时还原。</p><button className="wb-btn primary" type="button" disabled={busy || !allAnswered} onClick={() => void submit()}>{busy ? '正在评分…' : '提交并查看结果'}</button></div> : <section className="focus-card focus-card-quiet listening-score"><h2>本次结果：{session.score} / {session.lesson.questions.length}</h2><p>{session.assessment_note}</p><p>评价来源：服务端规则校验 · {session.lesson.evaluation_rule_version}</p><button type="button" className="wb-btn primary" onClick={() => { setSession(null); setAnswers({}); localStorage.removeItem(SESSION_KEY); localStorage.removeItem(DRAFT_KEY); }}>再做一次</button></section>}</>}
    <section className="listening-history"><h2>学习历史</h2>{history.length ? <ul>{history.slice(0, 8).map(item => <li key={item.session_id}>{new Date(item.started_at).toLocaleString()} · {item.status === 'completed' ? `本次成绩 ${item.score}/5` : '进行中'}{item.session_id === session?.session_id ? ' · 当前练习' : ''}</li>)}</ul> : <p>完成一次练习后，结果会保存在共享学习历史中。</p>}</section>
  </main>;
}
