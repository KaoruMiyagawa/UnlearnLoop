import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { SMOKE_UI_URL: ui, SMOKE_CDP_URL: cdp, SMOKE_OUTPUT_DIR: output, SMOKE_API_URL: api } = process.env;
assert.ok(ui && cdp && output && api, 'Use the isolated Writing browser runner.');
const page = (await (await fetch(`${cdp}/json/list`)).json()).find(tab => tab.type === 'page');
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
const pending = new Map();
const errors = [];
const screenshots = [];
let sequence = 0;
let dropSubmission = false;
let droppedResponses = 0;
let interceptionError;
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 10000);
  pending.set(id, message => { clearTimeout(timeout); message.error ? reject(message.error) : resolve(message.result); });
  socket.send(JSON.stringify({ id, method, params }));
});
socket.onmessage = async ({ data }) => {
  const message = JSON.parse(data);
  if (message.id) {
    pending.get(message.id)?.(message);
    pending.delete(message.id);
  } else if (message.method === 'Runtime.exceptionThrown') {
    errors.push(message.params.exceptionDetails.text);
  } else if (message.method === 'Fetch.requestPaused') {
    const { requestId, request, responseStatusCode } = message.params;
    try {
      if (dropSubmission && request.method === 'POST' && responseStatusCode === 200) {
        dropSubmission = false;
        droppedResponses++;
        await send('Fetch.failRequest', { requestId, errorReason: 'ConnectionClosed' });
      } else await send('Fetch.continueRequest', { requestId });
    } catch (error) { interceptionError = error; }
  }
};
const js = JSON.stringify;
const evaluate = async expression => {
  const response = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  assert.ok(!response.exceptionDetails, js(response.exceptionDetails));
  return response.result.value;
};
async function wait(expression) {
  for (let i = 0; i < 120; i++) {
    if (interceptionError) throw interceptionError;
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${expression}\n${await evaluate('document.body.innerText.slice(-1400)')}`);
}
const has = text => wait(`document.body.innerText.includes(${js(text)})`);
async function click(text) {
  assert.ok(await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${js(text)} && !b.disabled);
    if (!button) return false;
    button.click();
    return true;
  })()`), `Missing enabled button: ${text}`);
}
async function press(key, code, modifiers = 0) {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key, windowsVirtualKeyCode: code, modifiers });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key, windowsVirtualKeyCode: code, modifiers });
}
async function replaceEssay(text) {
  await wait("!document.querySelector('#writing-essay').readOnly");
  await evaluate("document.querySelector('#writing-essay').focus()");
  await press('a', 65, 2);
  await send('Input.insertText', { text });
  assert.equal(await evaluate("document.querySelector('#writing-essay').value"), text);
}
async function screenshot(name) {
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(join(output, name), Buffer.from(data, 'base64'));
  screenshots.push(name);
}
const essay = [
  'Local councils often have to decide how to use a small plot of public land. I would favour a community garden in an area that already has a place to exercise.',
  'Gardens give neighbours a common project. A shared compost bin and a weekly watering rota can help strangers get to know each other.',
  'On the other hand, an outdoor court gives children a safe place to play. In neighbourhoods where families cannot afford sports clubs, that may be the more urgent need.',
].join('\n\n');
const revision = essay.replace('that may be the more urgent need.', 'a court could serve more people than a garden.');

try {
  for (const domain of ['Runtime', 'Page', 'Network']) await send(`${domain}.enable`);
  await send('Page.navigate', { url: ui });
  await wait("!!document.querySelector('.learn-skill-card[href=\"/learn/writing\"]')");
  await evaluate("document.querySelector('.learn-skill-card[href=\"/learn/writing\"]').focus()");
  await press('Enter', 13);
  await has('Shared spaces for neighbourhoods');
  assert.equal(await evaluate('location.pathname'), '/learn/writing');
  assert.equal(await evaluate('document.activeElement.tagName'), 'H1');
  await evaluate("document.querySelector('.learn-back-link').focus()");
  await press('Tab', 9);
  assert.equal(await evaluate('document.activeElement.id'), 'writing-essay');
  assert.ok(await evaluate("document.activeElement.matches(':focus-visible')"));
  await send('Input.insertText', { text: essay });
  await has('服务器草稿已保存');
  await send('Page.reload');
  await wait(`document.querySelector('#writing-essay')?.value === ${js(essay)}`);

  await send('Network.setBlockedURLs', { urls: [`${api}/api/v1/writing/*/draft*`] });
  await replaceEssay(revision);
  await has('草稿未同步到服务器');
  await send('Page.reload');
  await wait(`document.querySelector('#writing-essay')?.value === ${js(revision)}`);
  await has('草稿未同步到服务器');
  await send('Network.setBlockedURLs', { urls: [] });
  await click('保存草稿');
  await has('服务器草稿已保存');

  await send('Fetch.enable', { patterns: [{ urlPattern: `${api}/api/v1/writing/*/revisions*`, requestStage: 'Response' }] });
  dropSubmission = true;
  await click('提交作文');
  await has('暂时无法确认提交结果');
  assert.equal(droppedResponses, 1);
  await send('Page.reload');
  await has('重试提交');
  assert.equal(await evaluate("document.querySelector('#writing-essay').value"), revision);
  await click('重试提交');
  await has('自动文本检测');
  await wait("!document.querySelector('#writing-essay').readOnly");
  assert.equal(await evaluate("document.querySelectorAll('.writing-selects label:first-child option').length"), 1);
  await send('Fetch.disable');

  const finalText = revision + '\n\n<img src=x onerror="window.writingExecuted=true"> 🌱';
  await replaceEssay(finalText);
  await has('服务器草稿已保存');
  await click('提交修订版');
  await has('相比第 1 版，字数变化');
  await wait("document.querySelector('pre[aria-label=正文变化]')?.textContent.includes('<img')");
  assert.equal(await evaluate("!!window.writingExecuted || !!document.querySelector('.writing-diff img')"), false);
  assert.equal(await evaluate("document.querySelectorAll('.writing-selects label:first-child option').length"), 2);

  for (const theme of ['premium', 'noir']) {
    if (await evaluate('document.documentElement.dataset.theme') !== theme) {
      await evaluate("document.querySelector('.focus-theme-toggle').click()");
    }
    await wait(`document.documentElement.dataset.theme === ${js(theme)}`);
    for (const [width, height] of [[1440, 1000], [390, 844]]) {
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 });
      await wait(`innerWidth === ${width}`);
      assert.ok(await evaluate(`document.documentElement.scrollWidth <= ${width}`));
      if (width < 500) assert.ok(await evaluate("[...document.querySelectorAll('.writing-page button,.writing-page select')].every(x=>x.getBoundingClientRect().height>=42)"));
      await evaluate("window.scrollTo({ top: 0, behavior: 'instant' })");
      await screenshot(`writing-${theme}-${width}.png`);
      await evaluate("document.querySelector('.writing-history').scrollIntoView({ behavior: 'instant' })");
      await screenshot(`comparison-${theme}-${width}.png`);
    }
  }
  await click('查看学习档案 →');
  await has('写作提交 · 第 2 版');
  await has('写作提交 · 第 1 版');
  await click('打开写作工作区');
  await wait(`document.querySelector('#writing-essay')?.value === ${js(finalText)}`);
  assert.deepEqual(errors, []);
  await writeFile(join(output, 'browser-evidence.json'), JSON.stringify({
    browser: 'Headless Chrome', viewports: [[1440, 1000], [390, 844]], themes: ['premium', 'noir'],
    keyboard: true, automatic_save: true, reload: true, save_failure_recovery: true,
    dropped_committed_response_replayed: droppedResponses === 1, revision_comparison: true,
    literal_html: true, shared_history: true, runtime_exceptions: errors, screenshots,
  }, null, 2) + '\n');
  console.log(`Writing browser passed, ${screenshots.length} screenshots.`);
} finally {
  socket.close();
}
