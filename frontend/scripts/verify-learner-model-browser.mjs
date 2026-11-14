import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
const { SMOKE_UI_URL: ui, SMOKE_CDP_URL: cdp, SMOKE_OUTPUT_DIR: output } = process.env;
const target = (await (await fetch(`${cdp}/json/list`)).json()).find(x => x.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let seq = 0; const pending = new Map(); const errors = [];
const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++seq; const timer = setTimeout(() => reject(Error(method)), 20000); pending.set(id, m => { clearTimeout(timer); m.error ? reject(Error(JSON.stringify(m.error))) : resolve(m.result); }); ws.send(JSON.stringify({ id, method, params })); });
ws.onmessage = ({data}) => { const m = JSON.parse(data); if (m.id) { pending.get(m.id)?.(m); pending.delete(m.id); } else if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text); };
const evalJs = async expression => { const r = await send('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true}); if(r.exceptionDetails) throw Error(r.exceptionDetails.text); return r.result.value; };
const wait = async expression => { for (let i=0;i<150;i++) { if (await evalJs(expression)) return; await new Promise(r => setTimeout(r, 150)); } throw Error(`Timeout ${expression}`); };
try {
  await mkdir(output, {recursive:true}); await send('Runtime.enable'); await send('Page.enable');
  await send('Page.navigate', {url:`${ui}/profile`});
  await wait("document.querySelectorAll('#learner-model-title ~ *').length || document.body.innerText.includes('Listening 听力')");
  await wait("document.body.innerText.includes('Listening 听力') && document.body.innerText.includes('Speaking 口语') && document.body.innerText.includes('Reading 阅读') && document.body.innerText.includes('Writing 写作')");
  assert.ok(await evalJs("document.body.innerText.includes('有学习记录') && document.body.innerText.includes('能力未评估')"));
  for (const [theme,width,height] of [['premium',1440,1000],['noir',1440,1000],['premium',390,844],['noir',390,844]]) {
    if (await evalJs('document.documentElement.dataset.theme') !== theme) await evalJs("document.querySelector('.focus-theme-toggle').click()");
    await wait(`document.documentElement.dataset.theme === '${theme}'`);
    await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<500});
    await wait(`innerWidth === ${width}`);
    await evalJs("document.querySelector('#learner-model-title').scrollIntoView({block:'start'}); true");
    assert.ok(await evalJs(`document.documentElement.scrollWidth <= ${width}`), `overflow ${width}`);
    const {data} = await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    await writeFile(join(output,`profile-${theme}-${width}.png`),Buffer.from(data,'base64'));
  }
  assert.deepEqual(errors, []); console.log('Learner model browser passed: four skills, populated evidence, both themes, desktop/mobile.');
} finally { ws.close(); }
