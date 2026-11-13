import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { SMOKE_UI_URL: ui, SMOKE_CDP_URL: cdp, SMOKE_OUTPUT_DIR: output } = process.env;
assert.ok(ui && cdp && output, 'Use verify_listening_browser.py to start isolated services.');
const targets = await (await fetch(`${cdp}/json/list`)).json();
const target = targets.find(item => item.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
const pending = new Map(); const errors = []; const requests = []; let seq = 0;
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq; const timeout = setTimeout(() => reject(new Error(`CDP timeout ${method}`)), 20000);
  pending.set(id, msg => { clearTimeout(timeout); msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result); });
  ws.send(JSON.stringify({ id, method, params }));
});
ws.onmessage = ({ data }) => { const msg = JSON.parse(data); if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); } else if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.text); else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') errors.push(msg.params.args.map(x => x.description ?? x.value).join(' ')); else if (msg.method === 'Network.requestWillBeSent' && msg.params.request.url.includes('/api/v1/listening/')) requests.push({ requestId: msg.params.requestId, method: msg.params.request.method, url: msg.params.request.url, status: null }); else if (msg.method === 'Network.responseReceived' && msg.params.response.url.includes('/api/v1/listening/')) { const entry = requests.find(x => x.requestId === msg.params.requestId); if(entry) entry.status = msg.params.response.status; } };
await Promise.all(['Runtime.enable', 'Page.enable', 'Network.enable', 'Log.enable'].map(method => send(method)));
const wait = async (test, label) => { for (let i=0;i<150;i++) { const v = await evalJs(test); if (v) return v; await new Promise(r => setTimeout(r, 150)); } throw new Error(`Timed out: ${label}; ${await evalJs('document.body.innerText.slice(-1000)')}`); };
const evalJs = async expression => { const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text); return result.result.value; };
const click = async selector => { const ok = await evalJs(`(() => { const e=document.querySelector(${JSON.stringify(selector)}); if(!e)return false; e.click(); return true })()`); assert.ok(ok, `Missing ${selector}`); };
const nav = async path => { await send('Page.navigate', { url: `${ui}${path}` }); await wait("Boolean(document.querySelector('h1'))", `navigation ${path}`); };
const setTheme = async theme => { if (await evalJs('document.documentElement.dataset.theme') !== theme) await click('.focus-theme-toggle'); await wait(`document.documentElement.dataset.theme === ${JSON.stringify(theme)}`, `theme ${theme}`); };
const size = async (width, height) => { await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 }); await send('Emulation.setTouchEmulationEnabled', { enabled: width < 500 }); await wait(`innerWidth === ${width}`, `${width}px viewport`); const widthCheck=await evalJs('document.documentElement.scrollWidth'); assert.ok(widthCheck <= width, `Horizontal overflow at ${width}: ${widthCheck}`); };
const screenshot = async name => { const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }); await writeFile(join(output, name), Buffer.from(data, 'base64')); };
const bodyHas = async txt => wait(`document.body.innerText.includes(${JSON.stringify(txt)})`, txt);

try {
  await mkdir(output, { recursive: true });
  await nav('/learn/listening');
  for (const [theme, width, height, name] of [['premium',1440,1000,'listening-desktop-premium-academic.png'],['noir',1440,1000,'listening-desktop-noir-champagne.png'],['premium',390,844,'listening-mobile-premium-academic.png'],['noir',390,844,'listening-mobile-noir-champagne.png']]) {
    await setTheme(theme); await size(width,height); await screenshot(name);
    const geometry = await evalJs(`(() => ({scrollWidth:document.documentElement.scrollWidth,targets:[...document.querySelectorAll('button,a,input,audio')].map(e=>Math.round(e.getBoundingClientRect().height)).filter(Boolean)}))()`);
    assert.ok(geometry.scrollWidth <= width);
    if (width < 500) assert.ok(geometry.targets.every(height => height >= 40), JSON.stringify(geometry));
  }
  await setTheme('premium'); await size(1440,1000);
  await click('.listening-intro button'); await bodyHas('Which room will the workshop use?');
  const media = await wait("(() => { const a=document.querySelector('audio'); return a && a.readyState >= 1 && a.duration > 60 ? {duration:a.duration,readyState:a.readyState,src:a.currentSrc} : false })()", 'real playable audio metadata');
  assert.ok(media.duration < 90, JSON.stringify(media));
  await evalJs("document.querySelector('audio').dispatchEvent(new Event('error')); true"); await bodyHas('音频文件无法加载');
  await evalJs("document.querySelector('audio').dispatchEvent(new Event('canplay')); true");
  const play = await evalJs("(async()=>{const a=document.querySelector('audio'); await a.play(); await new Promise(r=>setTimeout(r,600)); const playing=!a.paused; const time=a.currentTime; a.pause(); return {playing,time,duration:a.duration,paused:a.paused}})()");
  assert.ok(play.playing && play.time > 0 && play.paused, JSON.stringify(play));
  assert.ok(await evalJs("Boolean(document.querySelector('input[type=radio]'))"));
  await evalJs("document.querySelectorAll('input[type=radio]')[0].click(); document.querySelectorAll('input[type=radio]')[3].click(); document.querySelectorAll('input[type=radio]')[6].click(); document.querySelectorAll('input[type=radio]')[9].click(); document.querySelectorAll('input[type=radio]')[12].click(); true");
  const draftBefore = await evalJs("JSON.parse(localStorage.getItem('verbatrail.listening.draft.v1') || '{}')"); assert.equal(Object.keys(draftBefore).length,5);
  await send('Page.reload'); await bodyHas('Which room will the workshop use?');
  const draftAfter = await evalJs("JSON.parse(localStorage.getItem('verbatrail.listening.draft.v1') || '{}')"); assert.deepEqual(draftAfter,draftBefore);
  assert.ok(await evalJs("[...document.querySelectorAll('input[type=radio]')].filter(e=>e.checked).length") === 5);
  await click('.listening-submit button'); await bodyHas('本次结果：'); await bodyHas('听取 9.24–17.39 秒片段'); await bodyHas('回答正确'); await bodyHas('你的答案：');
  assert.ok(await evalJs("document.body.innerText.includes('答案：')"));
  await screenshot('listening-results-premium-academic.png');
  await setTheme('noir'); await screenshot('listening-results-noir-champagne.png');
  const anchorRect = await evalJs("(()=>{const r=document.querySelector('.listening-result button').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()");
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:anchorRect.x,y:anchorRect.y});
  await send('Input.dispatchMouseEvent',{type:'mousePressed',x:anchorRect.x,y:anchorRect.y,button:'left',clickCount:1});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:anchorRect.x,y:anchorRect.y,button:'left',clickCount:1});
  await new Promise(r=>setTimeout(r,600));
  const anchor = await evalJs("(()=>{const a=document.querySelector('audio'); return {time:a.currentTime,playing:!a.paused}})()"); assert.ok(anchor.time >= 9 && anchor.time < 18, JSON.stringify(anchor));
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab'});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab'});
  const focus = await evalJs("({tag:document.activeElement.tagName,visible:document.activeElement.matches(':focus-visible'),outline:getComputedStyle(document.activeElement).outlineStyle})"); assert.ok(focus.visible && focus.outline === 'solid', JSON.stringify(focus));
  await nav('/learn/reading'); await wait("document.body.innerText.includes('阅读') || document.body.innerText.includes('Reading')", 'Reading route regression');
  await bodyHas('会话'); await screenshot('reading-regression.png');
  assert.deepEqual(errors, []);
  await writeFile(join(output,'browser-http-evidence.json'),JSON.stringify(requests,null,2));
  console.log(JSON.stringify({audio:media,playback:play,draftRestored:true,result:await evalJs("document.body.innerText.slice(-300)"),timeAnchor:anchor,reading:true,consoleErrors:errors,httpRequests:requests,screenshots:output},null,2));
} finally { ws.close(); }
