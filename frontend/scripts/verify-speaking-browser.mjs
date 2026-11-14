import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { SMOKE_UI_URL: ui, SMOKE_CDP_URL: cdp, SMOKE_API_URL: api, SMOKE_OUTPUT_DIR: output } = process.env;
assert.ok(ui && cdp && api && output);
const page = (await (await fetch(`${cdp}/json/list`)).json()).find(item => item.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
const pending = new Map();
const exceptions = [];
const requests = [];
let sequence = 0;
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timer = setTimeout(() => reject(Error(`CDP timeout: ${method}`)), 15000);
  pending.set(id, message => { clearTimeout(timer); message.error ? reject(Error(JSON.stringify(message.error))) : resolve(message.result); });
  ws.send(JSON.stringify({ id, method, params }));
});
ws.onmessage = ({ data }) => {
  const message = JSON.parse(data);
  if (message.id) { pending.get(message.id)?.(message); pending.delete(message.id); }
  if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails.text);
  if (message.method === 'Network.requestWillBeSent' && message.params.request.url.includes('/api/v1/speaking/')) {
    requests.push({ method: message.params.request.method, url: message.params.request.url,
      body: message.params.request.postData ?? null });
  }
};
const evaluate = async expression => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
  return result.result.value;
};
const wait = async expression => {
  for (let i = 0; i < 150; i++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw Error(`Timeout: ${expression}\n${await evaluate('document.body.innerText.slice(-2000)')}`);
};
const text = value => wait(`document.body.innerText.includes(${JSON.stringify(value)})`);
async function click(label) {
  assert.equal(await evaluate(`(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === ${JSON.stringify(label)} && !x.disabled);
    if (!b) return false;
    b.click();
    return true;
  })()`), true, label);
}
async function record() {
  await click('开始录音');
  await text('正在录音');
  await new Promise(resolve => setTimeout(resolve, 1300));
  await click('停止录音');
  await text('录音已保存到此浏览器');
}
async function screenshot(name) {
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(output, name), Buffer.from(data, 'base64'));
}
try {
  for (const domain of ['Page', 'Runtime', 'Network']) await send(`${domain}.enable`);
  await send('Page.navigate', { url: `${ui}/learn/speaking` });
  await text('What part of your daily routine');
  assert.equal(await evaluate("document.querySelector('h1').textContent.includes('Speaking')"), true);
  await evaluate(`(() => { const select=document.querySelector('#speaking-prompt');
    select.value='study-place'; select.dispatchEvent(new Event('change', {bubbles:true})); })()`);
  await text('Where do you prefer to study');
  await evaluate(`(() => { const select=document.querySelector('#speaking-prompt');
    select.value='daily-routine'; select.dispatchEvent(new Event('change', {bubbles:true})); })()`);
  await text('What part of your daily routine');
  await record();
  await record();
  assert.equal(await evaluate("document.querySelectorAll('.speaking-recording audio').length"), 2);
  await send('Page.reload');
  await wait("document.querySelectorAll('.speaking-recording audio').length === 2");
  const playback = await evaluate(`(async () => {
    const elements = [...document.querySelectorAll('.speaking-recording audio')];
    const results = [];
    for (const audio of elements) {
      await audio.play();
      await new Promise(resolve => setTimeout(resolve, 500));
      results.push({ time: audio.currentTime, paused: audio.paused, src: audio.currentSrc });
      audio.pause();
    }
    return results;
  })()`);
  assert.ok(playback.every(item => item.time > 0 && !item.paused && item.src.startsWith('blob:')));
  const stored = await evaluate(`new Promise((resolve,reject) => {
    const req=indexedDB.open('verbatrail-speaking-v1');
    req.onerror=()=>reject(req.error);
    req.onsuccess=()=>{const db=req.result; const read=db.transaction('recordings').objectStore('recordings').getAll();
      read.onsuccess=()=>{resolve(read.result.map(x=>({size:x.blob.size,type:x.blob.type})));db.close();};};
  })`);
  assert.equal(stored.length, 2);
  assert.ok(stored.every(item => item.size > 100));
  await send('Network.setBlockedURLs', { urls: [`${api}/api/v1/speaking/practices*`] });
  await click('完成练习');
  await text('练习记录未确认');
  assert.equal(await evaluate("document.querySelectorAll('audio').length"), 2);
  await send('Network.setBlockedURLs', { urls: [] });
  await click('重试完成练习');
  await text('练习元数据已保存到学习历史');
  await wait("document.body.innerText.includes('录音仅本地可用')");
  await send('Page.reload');
  await wait("document.querySelectorAll('.speaking-recording audio').length === 2");
  await text('练习已记录');
  await click('删除本地录音');
  await text('本地录音已删除');
  await text('本地录音不可用');
  assert.equal(await evaluate("document.querySelectorAll('.speaking-recording audio').length"), 1);
  await click('删除历史记录');
  await text('练习历史记录已删除');
  await click('查看共享学习历史 →');
  await text('学习历史');

  await send('Page.navigate', { url: `${ui}/learn/speaking` });
  await text('What part of your daily routine');
  await evaluate(`(() => { window.originalMic = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError'); }; })()`);
  await click('开始录音');
  await text('麦克风权限被拒绝');
  await evaluate(`navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Missing', 'NotFoundError'); }`);
  await click('开始录音');
  await text('未找到麦克风');
  await evaluate('navigator.mediaDevices.getUserMedia = window.originalMic');
  await evaluate(`navigator.mediaDevices.getUserMedia = async (...args) => {
    const stream = await window.originalMic(...args);
    window.testStream = stream;
    return stream;
  }`);
  await click('开始录音');
  await text('正在录音');
  await evaluate("window.testStream.getAudioTracks()[0].dispatchEvent(new Event('ended'))");
  await text('麦克风已断开');
  await evaluate('navigator.mediaDevices.getUserMedia = window.originalMic');
  await evaluate(`window.originalRecorder = window.MediaRecorder;
    window.MediaRecorder = class {
      constructor() { this.state='inactive'; this.mimeType=''; }
      start() { this.state='recording'; }
      stop() { this.state='inactive'; setTimeout(() => this.onstop?.(), 0); }
    };`);
  await click('开始录音');
  await text('正在录音');
  await new Promise(resolve => setTimeout(resolve, 250));
  await click('停止录音');
  await text('录音为空或时间太短');
  await evaluate('window.MediaRecorder = window.originalRecorder');
  await evaluate(`window.originalPut = IDBObjectStore.prototype.put; IDBObjectStore.prototype.put = function() { throw new DOMException('Full', 'QuotaExceededError'); }`);
  await click('开始录音');
  await text('正在录音');
  await new Promise(resolve => setTimeout(resolve, 1200));
  await click('停止录音');
  await text('录音保存失败');
  await evaluate('IDBObjectStore.prototype.put = window.originalPut');
  await click('重试保存录音');
  await text('录音已保存到此浏览器');

  for (const theme of ['premium', 'noir']) {
    if (await evaluate('document.documentElement.dataset.theme') !== theme) await evaluate("document.querySelector('.focus-theme-toggle').click()");
    await wait(`document.documentElement.dataset.theme === ${JSON.stringify(theme)}`);
    for (const [width, height] of [[1440, 1000], [390, 844]]) {
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 });
      await wait(`innerWidth === ${width}`);
      assert.ok(await evaluate(`document.documentElement.scrollWidth <= ${width}`));
      await evaluate("window.scrollTo({top:0,behavior:'instant'})");
      await screenshot(`speaking-${theme}-${width}.png`);
      await evaluate("document.querySelector('.speaking-recording')?.scrollIntoView({behavior:'instant'})");
      await screenshot(`recordings-${theme}-${width}.png`);
    }
  }
  await evaluate("document.querySelector('.learn-back-link').focus()");
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  assert.ok(await evaluate("document.activeElement.matches(':focus-visible')"));
  assert.ok(requests.filter(r => r.method === 'POST').every(r => !r.body || (!r.body.includes('base64') && !r.body.includes('audio/'))));
  assert.deepEqual(exceptions, []);
  await writeFile(join(output, 'browser-evidence.json'), JSON.stringify({
    browser: 'Headless Chrome with simulated microphone; physical hardware not tested',
    recording_count: stored.length, recorded_blob_sizes: stored.map(x => x.size), playback_seconds: playback.map(x => x.time),
    refresh: true, retry_after_network_failure: true, deletion_and_missing_audio: true,
    permission_denied: true, device_missing: true, device_disconnected: true,
    empty_recording_rejected: true, indexeddb_failure_and_retry: true,
    themes: ['premium', 'noir'], viewports: [[1440, 1000], [390, 844]],
    runtime_exceptions: exceptions,
  }, null, 2) + '\n');
  console.log('Speaking Chrome verification passed with a simulated microphone.');
} finally { ws.close(); }
