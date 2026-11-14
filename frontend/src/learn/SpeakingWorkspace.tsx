import { useEffect, useRef, useState } from 'react';
import {
  completeSpeaking, deleteSpeakingPractice, getSpeakingPractices, getSpeakingPrompts,
  type SpeakingPractice, type SpeakingPrompt,
} from '../api/speaking';
import type { WorkspaceId } from '../app-shell/navigation';
import { deleteRecording, listRecordings, saveRecording, type LocalRecording } from './speakingStorage';
import './speaking.css';

const LEARNER = 'default_learner';
const CHECKS = [
  ['direct', '我是否直接回答了问题？'],
  ['detail', '我是否提供了具体信息或例子？'],
  ['pauses', '我是否留意了明显的长时间停顿？'],
  ['improvement', '第二次表达有哪些改善？'],
] as const;

function Playback({ recording, onError }: { recording: LocalRecording; onError: () => void }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    const value = URL.createObjectURL(recording.blob);
    setUrl(value);
    return () => URL.revokeObjectURL(value);
  }, [recording.blob]);
  return url ? <audio controls preload="metadata" src={url} aria-label="播放本地录音" onError={onError} /> : null;
}

export function SpeakingWorkspace({ onNavigate }: { onNavigate: (workspace: WorkspaceId) => void }) {
  const [prompts, setPrompts] = useState<SpeakingPrompt[]>([]);
  const [selected, setSelected] = useState('');
  const [local, setLocal] = useState<LocalRecording[]>([]);
  const [remote, setRemote] = useState<SpeakingPractice[]>([]);
  const [checks, setChecks] = useState<string[]>([]);
  const [recording, setRecording] = useState(false);
  const [starting, setStarting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [storageReady, setStorageReady] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const started = useRef(0);
  const mounted = useRef(true);
  const aborted = useRef(false);
  const activePrompt = useRef<SpeakingPrompt | null>(null);
  const chunks = useRef<Blob[]>([]);
  const pendingBlob = useRef<LocalRecording | null>(null);

  const prompt = prompts.find(item => item.id === selected);
  const stopTracks = () => {
    stream.current?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    stream.current = null;
  };

  async function refreshLocal() {
    const items = await listRecordings(LEARNER);
    if (mounted.current) {
      setLocal(items.sort((a, b) => b.metadata.recorded_at.localeCompare(a.metadata.recorded_at)));
      setStorageReady(true);
    }
  }

  async function refreshRemote() {
    const items = await getSpeakingPractices(LEARNER);
    if (mounted.current) setRemote(items);
  }

  useEffect(() => {
    mounted.current = true;
    void getSpeakingPrompts().then(items => {
      if (mounted.current) { setPrompts(items); setSelected(items[0]?.id ?? ''); }
    }).catch(() => { if (mounted.current) setError('无法加载题目，请检查网络后重新进入。'); });
    void refreshLocal().catch(() => { if (mounted.current) setError('无法读取本地录音存储，请检查浏览器设置。'); });
    void refreshRemote().catch(() => { if (mounted.current) setError('无法读取服务端练习记录，本地录音仍可使用。'); });
    return () => {
      mounted.current = false;
      aborted.current = true;
      if (recorder.current?.state === 'recording') recorder.current.stop();
      stopTracks();
    };
  }, []);

  useEffect(() => {
    if (!recording) return;
    const timer = window.setInterval(() => setSeconds(Math.floor((performance.now() - started.current) / 1000)), 250);
    return () => window.clearInterval(timer);
  }, [recording]);

  async function persist(item: LocalRecording) {
    setBusy(true);
    try {
      await saveRecording(item);
      pendingBlob.current = null;
      await refreshLocal();
      setError('');
      setMessage('录音已保存到此浏览器。');
    } catch {
      pendingBlob.current = item;
      setError('录音保存失败，可能是存储空间不足或浏览器禁止存储。录音暂留在此页面，请重试保存。');
    } finally { if (mounted.current) setBusy(false); }
  }

  async function start() {
    if (starting || recording || busy || !prompt) return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError('麦克风需要安全环境（localhost 或 HTTPS）和浏览器麦克风支持。');
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setError('此浏览器不支持录音，请使用支持 MediaRecorder 的浏览器。');
      return;
    }
    if (!storageReady || pendingBlob.current) {
      setError('请先恢复本地存储并保存上一段录音。');
      return;
    }
    setStarting(true);
    setError('');
    setMessage('');
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) { media.getTracks().forEach(track => track.stop()); return; }
      stream.current = media;
      activePrompt.current = prompt;
      chunks.current = [];
      aborted.current = false;
      const instance = new MediaRecorder(media);
      recorder.current = instance;
      instance.ondataavailable = event => { if (event.data.size) chunks.current.push(event.data); };
      instance.onerror = () => {
        aborted.current = true;
        setError('录音设备出现错误，请检查麦克风并重试。');
        if (instance.state !== 'inactive') instance.stop();
        else setRecording(false);
        stopTracks();
      };
      media.getAudioTracks().forEach(track => {
        track.onended = () => {
          aborted.current = true;
          setError('麦克风已断开，本次录音未保存。');
          if (instance.state !== 'inactive') instance.stop();
        };
      });
      instance.onstop = () => {
        const elapsed = Math.min(600, Math.max(0, (performance.now() - started.current) / 1000));
        stopTracks();
        recorder.current = null;
        if (!mounted.current) return;
        setRecording(false);
        if (aborted.current) return;
        const blob = new Blob(chunks.current, { type: instance.mimeType || chunks.current[0]?.type });
        if (!blob.size || elapsed < 0.1 || !activePrompt.current) {
          setError('录音为空或时间太短，请重新录制。');
          return;
        }
        const task = activePrompt.current;
        void persist({
          blob, pending: false,
          metadata: {
            learner_id: LEARNER, recording_id: crypto.randomUUID(), prompt_id: task.id,
            prompt_version: task.version, duration_seconds: Number(elapsed.toFixed(2)),
            recorded_at: new Date().toISOString(), self_check: [],
          },
        });
      };
      started.current = performance.now();
      setSeconds(0);
      instance.start();
      setRecording(true);
    } catch (failure) {
      stopTracks();
      const name = failure instanceof DOMException ? failure.name : '';
      setError(name === 'NotAllowedError' ? '麦克风权限被拒绝，请在浏览器设置中允许访问。'
        : name === 'NotFoundError' ? '未找到麦克风，请连接设备后重试。'
          : '无法启动麦克风，请检查设备和浏览器设置。');
    } finally {
      if (mounted.current) setStarting(false);
    }
  }

  useEffect(() => {
    if (recording && seconds >= 600 && recorder.current?.state === 'recording') recorder.current.stop();
  }, [recording, seconds]);

  async function complete(item: LocalRecording) {
    setBusy(true);
    setError('');
    try {
      // Persist the exact request before sending so a lost response can be retried safely.
      const pending = item.pending ? item : { ...item, pending: true, metadata: { ...item.metadata, self_check: checks } };
      await saveRecording(pending);
      await refreshLocal();
      await completeSpeaking(pending.metadata);
      await saveRecording({ ...pending, pending: false });
      await refreshLocal();
      await refreshRemote();
      setMessage('练习元数据已保存到学习历史。音频仍只在本浏览器。');
    } catch {
      setError('练习记录未确认。录音保留在本地，请重试完成练习。');
    } finally { setBusy(false); }
  }

  async function removeLocal(item: LocalRecording) {
    setBusy(true);
    try {
      await deleteRecording(item.metadata.recording_id);
      await refreshLocal();
      setMessage('本地录音已删除。若已有学习历史，元数据仍会标记为本地不可用。');
    } catch { setError('删除本地录音失败，请重试。'); }
    finally { setBusy(false); }
  }

  async function removeHistory(id: string) {
    setBusy(true);
    try {
      await deleteSpeakingPractice(id, LEARNER);
      await refreshRemote();
      setMessage('练习历史记录已删除。');
    } catch { setError('无法删除练习历史，请检查网络后重试。'); }
    finally { setBusy(false); }
  }

  const visible = local.filter(item => item.metadata.prompt_id === selected);
  return <div className="learn-page speaking-page">
    <button className="focus-button-quiet learn-back-link" onClick={() => onNavigate('home')}>← 返回 Learn</button>
    <header className="focus-page-header">
      <p className="focus-eyebrow">IELTS SPEAKING · PART 1</p>
      <h1 className="focus-page-title" data-workspace-heading tabIndex={-1}>Speaking · 口语</h1>
      <p>选择一道原创问题，练习约 30 秒。录音只保存在当前浏览器，清除网站数据可能导致丢失。</p>
      <p>完成练习仅记录元数据，不评定口语水平、迁移或长期保持。</p>
    </header>
    {error && <div role="alert" className="focus-notice danger">{error}
      {pendingBlob.current && <button className="focus-button-secondary" onClick={() => void persist(pendingBlob.current!)}>重试保存录音</button>}
      {!storageReady && <button className="focus-button-secondary" onClick={() => void refreshLocal().catch(() => setError('本地存储仍不可用。'))}>重试本地存储</button>}
    </div>}
    {message && <p role="status" className="focus-notice neutral">{message}</p>}
    <section className="focus-card speaking-card">
      <label htmlFor="speaking-prompt">选择问题</label>
      <select id="speaking-prompt" value={selected} disabled={recording || starting}
        onChange={event => setSelected(event.target.value)}>
        {prompts.map((item, index) => <option key={item.id} value={item.id}>问题 {index + 1}</option>)}
      </select>
      {prompt && <><p className="focus-eyebrow">PART {prompt.part} · 建议 {prompt.suggested_seconds} 秒</p>
        <h2 lang="en">{prompt.text}</h2></>}
      <p aria-live="polite">{starting ? '等待麦克风权限…' : recording ? `正在录音 · ${seconds} 秒` : '麦克风未录音'}</p>
      <div className="focus-actions">
        <button className="focus-button" disabled={starting || busy || !selected || !storageReady || recording} onClick={() => void start()}>开始录音</button>
        <button className="focus-button-secondary" disabled={!recording} onClick={() => recorder.current?.stop()}>停止录音</button>
      </div>
    </section>
    <section className="focus-card speaking-card">
      <h2>自主检查</h2><p>以下为自我检查问题，系统不会自动判断回答内容。</p>
      {CHECKS.map(([id, label]) => <label className="speaking-check" key={id}><input type="checkbox" checked={checks.includes(id)}
        onChange={event => setChecks(value => event.target.checked ? [...value, id] : value.filter(item => item !== id))} /> {label}</label>)}
    </section>
    <section className="focus-card speaking-card">
      <h2>录音版本</h2><p>选择同一问题的两段录音，分别播放并自行比较。</p>
      {!visible.length && <p>当前问题还没有本地录音。</p>}
      {visible.map((item, index) => {
        const saved = remote.some(entry => entry.recording_id === item.metadata.recording_id);
        return <article className="speaking-recording" key={item.metadata.recording_id}>
          <h3>版本 {visible.length - index}</h3>
          <p>{new Date(item.metadata.recorded_at).toLocaleString()} · {item.metadata.duration_seconds.toFixed(1)} 秒</p>
          <Playback recording={item} onError={() => setError('无法播放此录音，浏览器可能不支持该格式或文件已损坏。')} />
          <div className="focus-actions">
            <button className="focus-button-secondary" disabled={busy || saved} onClick={() => void complete(item)}>
              {saved ? '练习已记录' : item.pending ? '重试完成练习' : '完成练习'}
            </button>
            <button className="focus-button-quiet" disabled={busy} onClick={() => void removeLocal(item)}>删除本地录音</button>
          </div>
        </article>;
      })}
    </section>
    <section className="focus-card speaking-card">
      <h2>练习历史</h2><p>服务端仅保存练习元数据。音频只在原浏览器可用。</p>
      {remote.map(item => {
        const available = local.some(entry => entry.metadata.recording_id === item.recording_id);
        return <article className="speaking-recording" key={item.recording_id}>
          <p lang="en">{item.prompt_text}</p>
          <p>{new Date(item.recorded_at).toLocaleString()} · {item.duration_seconds.toFixed(1)} 秒 · {available ? '录音仅本地可用' : '本地录音不可用'}</p>
          <button className="focus-button-quiet" disabled={busy} onClick={() => void removeHistory(item.recording_id)}>删除历史记录</button>
        </article>;
      })}
      <button className="focus-button-quiet" onClick={() => onNavigate('profile')}>查看共享学习历史 →</button>
    </section>
  </div>;
}
