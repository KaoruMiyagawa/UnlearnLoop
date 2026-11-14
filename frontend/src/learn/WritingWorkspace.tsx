import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiClientError } from '../api/client';
import {
  getWritingRevision, openWriting, saveWritingDraft, submitWriting,
  type WritingRevision, type WritingSession, type WritingSubmission,
} from '../api/writing';
import type { WorkspaceId } from '../app-shell/navigation';
import { compareWriting, countWritingWords } from './writingText';
import './writing.css';

type Navigate = (workspace: WorkspaceId) => void;
type Recovery = { body: string; version: number; pending: WritingSubmission | null };

function cacheKey(id: string) {
  return `verbatrail.writing.draft.v1:${id}`;
}

function loadRecovery(id: string): Recovery | null {
  try {
    const cached = JSON.parse(localStorage.getItem(cacheKey(id)) ?? 'null');
    return cached && typeof cached.body === 'string' && Number.isSafeInteger(cached.version)
      ? cached : null;
  } catch {
    return null;
  }
}

function storeRecovery(id: string, value: Recovery | null): boolean {
  try {
    if (value) localStorage.setItem(cacheKey(id), JSON.stringify(value));
    else localStorage.removeItem(cacheKey(id));
    return true;
  } catch {
    return false;
  }
}

const formatDate = (value: string) => new Date(value).toLocaleString();
const isConflict = (error: unknown) => error instanceof ApiClientError && error.status === 409;

export function WritingWorkspace({ onNavigate }: { onNavigate: Navigate }) {
  const [session, setSession] = useState<WritingSession | null>(null);
  const [reload, setReload] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    openWriting(controller.signal).then(value => {
      if (!controller.signal.aborted) setSession(value);
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => controller.abort();
  }, [reload]);

  return <div className="learn-page writing-page">
    <button className="focus-button-quiet learn-back-link" onClick={() => onNavigate('home')}>← 返回 Learn</button>
    <header className="focus-page-header">
      <p className="focus-eyebrow">IELTS WRITING · TASK 2</p>
      <h1 className="focus-page-title" data-workspace-heading tabIndex={-1}>Writing · 写作</h1>
    </header>
    {session ? <WritingEditor key={session.session_id} session={session} onNavigate={onNavigate} />
      : failed ? <div className="focus-notice danger" role="alert">暂时无法打开写作。已保存的草稿仍可在连接恢复后读取。
        <button className="focus-button-quiet" onClick={() => setReload(n => n + 1)}>重试打开</button>
      </div> : <p role="status">正在加载写作练习…</p>}
  </div>;
}

function WritingEditor({ session, onNavigate }: { session: WritingSession; onNavigate: Navigate }) {
  const { session_id: id, task } = session;
  const [recovery] = useState(() => loadRecovery(id));
  const [saved, setSaved] = useState(session.draft);
  const [body, setBody] = useState(recovery?.body ?? saved.body);
  const [pending, setPending] = useState(recovery?.pending ?? null);
  const [conflict, setConflict] = useState(!!recovery && !recovery.pending
    && recovery.version !== saved.version && recovery.body !== saved.body);
  const [busy, setBusy] = useState<'save' | 'submit' | 'refresh' | null>(null);
  const [error, setError] = useState('');
  const [cacheAvailable, setCacheAvailable] = useState(true);
  const [revisions, setRevisions] = useState(session.revisions);
  const [selected, setSelected] = useState(session.revisions[0]?.id ?? '');
  const [previous, setPrevious] = useState(session.revisions[1]?.id ?? '');
  const [texts, setTexts] = useState<Record<string, WritingRevision>>({});
  const [previewError, setPreviewError] = useState('');
  const [previewRetry, setPreviewRetry] = useState(0);
  const working = useRef(false);
  const currentBody = useRef(body);
  const words = countWritingWords(body);
  const dirty = body !== saved.body;
  const latest = revisions[0];
  const latestBody = latest ? texts[latest.id]?.body : undefined;
  const canSubmit = !!pending || (!!words && body !== latestBody && (!latest || latestBody !== undefined || dirty));

  function cache(next: Recovery | null) {
    setCacheAvailable(storeRecovery(id, next));
  }

  async function save() {
    if (working.current || conflict || pending || !dirty) return;
    working.current = true;
    setBusy('save');
    setError('');
    const text = currentBody.current;
    try {
      const result = await saveWritingDraft(id, { body: text, version: saved.version });
      setSaved(result);
      cache(currentBody.current === result.body ? null : {
        body: currentBody.current, version: result.version, pending: null,
      });
    } catch (failure) {
      if (isConflict(failure)) setConflict(true);
      else setError('草稿未同步到服务器。文本仍在编辑器中，可以重试保存。');
    } finally {
      working.current = false;
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!dirty || busy || error || pending || conflict) return;
    const timer = window.setTimeout(() => void save(), 650);
    return () => window.clearTimeout(timer);
  }, [body, saved, busy, error, pending, conflict]);

  useEffect(() => {
    const missing = [...new Set([selected, previous, latest?.id ?? ''])]
      .filter(revision => revision && !texts[revision]);
    if (!missing.length) return;
    let active = true;
    setPreviewError('');
    Promise.all(missing.map(revision => getWritingRevision(id, revision))).then(loaded => {
      if (active) setTexts(values => ({ ...values, ...Object.fromEntries(loaded.map(item => [item.id, item])) }));
    }).catch(() => {
      if (active) setPreviewError('暂时无法读取历史正文。');
    });
    return () => { active = false; };
  }, [id, selected, previous, latest?.id, texts, previewRetry]);

  async function submit() {
    if (working.current || conflict || !canSubmit) return;
    const intent = pending ?? { body, version: saved.version, idempotency_key: crypto.randomUUID() };
    working.current = true;
    setPending(intent);
    setBusy('submit');
    setError('');
    cache({ body, version: saved.version, pending: intent });
    try {
      const result = await submitWriting(id, intent);
      // Reload the current server version even when the request replays an old submission.
      const updated = await openWriting();
      setRevisions(updated.revisions);
      setTexts(values => ({ ...values, [result.id]: result }));
      setSelected(result.id);
      setPrevious(result.source_revision_id ?? '');
      setSaved(updated.draft);
      setPending(null);
      setConflict(updated.draft.body !== result.body);
      cache(updated.draft.body === result.body ? null : { body, version: intent.version, pending: null });
    } catch (failure) {
      if (isConflict(failure) || (failure instanceof ApiClientError && failure.status === 422)) {
        setPending(null);
        cache({ body, version: saved.version, pending: null });
        if (isConflict(failure)) setConflict(true);
        else setError('服务器无法接受这篇作文。请检查文本长度、内容或异常字符后重试。');
      } else {
        setError('暂时无法确认提交结果。原文仍保留，重试将使用同一个提交编号。');
      }
    } finally {
      working.current = false;
      setBusy(null);
    }
  }

  async function resolveConflict(useLocal: boolean) {
    if (working.current) return;
    working.current = true;
    setBusy('refresh');
    try {
      const updated = await openWriting();
      setRevisions(updated.revisions);
      if (useLocal && currentBody.current !== updated.draft.body) {
        // The user explicitly chose local text over the latest server draft.
        const result = await saveWritingDraft(id, { body: currentBody.current, version: updated.draft.version });
        setSaved(result);
      } else {
        currentBody.current = updated.draft.body;
        setBody(updated.draft.body);
        setSaved(updated.draft);
      }
      cache(null);
      setError('');
      setConflict(false);
    } catch {
      setError('无法同步最新草稿，本地编辑内容仍保留。');
    } finally {
      working.current = false;
      setBusy(null);
    }
  }

  const chosen = revisions.find(item => item.id === selected);
  const earlier = revisions.find(item => item.id === previous);
  const chosenText = texts[selected]?.body;
  const earlierText = texts[previous]?.body;
  const changes = useMemo(() => earlierText !== undefined && chosenText !== undefined
    ? compareWriting(earlierText, chosenText) : null, [earlierText, chosenText]);

  return <>
    <section className="focus-card focus-card-quiet writing-task" aria-labelledby="writing-task-title">
      <h2 id="writing-task-title" lang="en">{task.title}</h2>
      <p lang="en">{task.prompt}</p>
      <p lang="en">{task.instruction}</p>
      <p>请用英语讨论双方观点并给出自己的看法。建议至少 {task.suggested_words} 词。</p>
    </section>
    <form className="focus-card writing-editor" onSubmit={event => { event.preventDefault(); void submit(); }}>
      <div className="writing-toolbar">
        <label htmlFor="writing-essay">作文草稿</label>
        <span id="writing-word-count">{words} 词 · 建议至少 {task.suggested_words} 词</span>
      </div>
      <textarea id="writing-essay" className="focus-textarea" lang="en" spellCheck
        value={body} maxLength={task.max_characters} readOnly={!!pending || busy === 'refresh'}
        aria-describedby="writing-word-count writing-save-status"
        onChange={event => {
          const text = event.target.value;
          currentBody.current = text;
          setBody(text);
          if (!conflict) setError('');
          cache({ body: text, version: recovery && conflict ? recovery.version : saved.version, pending: null });
        }} />
      <div className="writing-toolbar">
        <span id="writing-save-status" role="status">
          {busy === 'save' ? '正在保存草稿…' : pending ? '提交结果待确认'
            : dirty || conflict ? '有未同步的修改'
              : `服务器草稿已保存 · ${formatDate(saved.updated_at)}`}
        </span>
        <div className="focus-actions">
          <button className="focus-button-secondary" type="button" disabled={!!busy || !!pending || conflict || !dirty}
            onClick={() => void save()}>保存草稿</button>
          <button className="focus-button" type="submit"
            disabled={!!busy || conflict || !canSubmit}>
            {busy === 'submit' ? '正在提交…' : pending ? '重试提交' : latest ? '提交修订版' : '提交作文'}
          </button>
        </div>
      </div>
      {!cacheAvailable && <p role="alert">浏览器无法保存本地副本。请在离开前确认草稿已同步到服务器。</p>}
      {error && <p className="focus-notice danger" role="alert">{error}</p>}
      {conflict && <div className="focus-notice warning">
        <p role="alert">服务器已有另一份草稿。请选择保留当前编辑，或用服务器文本替换编辑器中的草稿。</p>
        <div className="focus-actions">
          <button className="focus-button-secondary" type="button" disabled={!!busy}
            onClick={() => void resolveConflict(true)}>用当前文本覆盖服务器草稿</button>
          <button className="focus-button-secondary" type="button" disabled={!!busy}
            onClick={() => void resolveConflict(false)}>使用服务器草稿</button>
        </div>
      </div>}
    </form>
    <section className="focus-card focus-card-quiet writing-history" aria-labelledby="writing-history-title">
      <div className="writing-toolbar">
        <h2 id="writing-history-title">提交历史与反馈</h2>
        <button className="focus-button-quiet" onClick={() => onNavigate('profile')}>查看学习档案 →</button>
      </div>
      {chosen ? <>
        <div className="writing-selects">
          <label>查看版本
            <select value={selected} onChange={event => {
              const revision = revisions.find(item => item.id === event.target.value)!;
              setSelected(revision.id);
              setPrevious(revision.source_revision_id ?? '');
            }}>
              {revisions.map(item => <option key={item.id} value={item.id}>第 {item.number} 版 · {formatDate(item.submitted_at)}</option>)}
            </select>
          </label>
          <label>与早期版本比较
            <select value={previous} onChange={event => setPrevious(event.target.value)}>
              <option value="">只查看正文</option>
              {revisions.filter(item => item.number < chosen.number).map(item =>
                <option key={item.id} value={item.id}>第 {item.number} 版</option>)}
            </select>
          </label>
        </div>
        <h3>自动文本检测</h3>
        <p>{chosen.feedback.word_count} 词 · {chosen.feedback.paragraph_blocks} 个由空行分隔的文本段落。
          {chosen.feedback.below_suggested_words ? ` 低于建议的 ${task.suggested_words} 词。` : ' 达到建议字数。'}
        </p>
        {earlier && <p>相比第 {earlier.number} 版，字数变化：{chosen.feedback.word_count - earlier.feedback.word_count} 词。</p>}
        {previewError && <p role="alert">{previewError} <button className="focus-button-quiet" onClick={() => setPreviewRetry(n => n + 1)}>重试读取</button></p>}
        {!previewError && (chosenText === undefined || (earlier && earlierText === undefined)) && <p role="status">正在加载正文…</p>}
        {changes ? <div className="writing-diff">
          <p>按行比较：+ 新增，− 删除，空白标记表示相同。</p>
          <pre aria-label="正文变化" lang="en">{changes.map((line, index) =>
            <span key={index} className={`writing-line ${line.kind}`}>{line.kind === 'same' ? '  ' : line.kind === 'added' ? '+ ' : '− '}{line.text}{'\n'}</span>)}</pre>
        </div> : chosenText !== undefined && <div className="writing-diff">
          {earlierText !== undefined && <><p>行数较多，以下并列显示两版正文。</p><pre aria-label="较早正文" lang="en">{earlierText}</pre></>}
          <pre aria-label="提交正文" lang="en">{chosenText}</pre>
        </div>}
      </> : <p>提交后可以查看文本检测结果和每一版的正文。</p>}
      <p><strong>尚未评估：</strong>论证、内容质量、词汇、语法准确性和 IELTS Band。</p>
      <details className="focus-disclosure">
        <summary>通用 Task 2 写作自查</summary>
        <ul>{task.checklist.map(item => <li key={item}>{item}</li>)}</ul>
      </details>
    </section>
  </>;
}
