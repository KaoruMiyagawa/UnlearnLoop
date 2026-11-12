import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { SMOKE_UI_URL: ui, SMOKE_CDP_URL: cdp, SMOKE_OUTPUT_DIR: output } = process.env;
assert.ok(ui && cdp && output, 'Use the isolated Phase 6.1 browser runner.');
await mkdir(output, { recursive: true });
const tabs = await (await fetch(`${cdp}/json/list`)).json();
const target = tabs.find(tab => tab.type === 'page');
assert.ok(target, 'Headless Chrome page target is available.');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
const pending = new Map();
const browserErrors = [];
let sequence = 0;
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
  pending.set(id, message => { clearTimeout(timer); message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result); });
  socket.send(JSON.stringify({ id, method, params }));
});
socket.onmessage = ({ data }) => {
  const message = JSON.parse(data);
  if (message.id) { pending.get(message.id)?.(message); pending.delete(message.id); return; }
  if (message.method === 'Runtime.exceptionThrown') browserErrors.push(message.params.exceptionDetails.text);
};
const evaluate = async expression => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
  return result.result.value;
};
const wait = async (predicate, label) => {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const found = await predicate();
    if (found) return found;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${label}: ${await evaluate('document.body.innerText.slice(-1800)')}`);
};
const hasText = value => wait(() => evaluate(`document.body.innerText.includes(${JSON.stringify(value)})`), value);
const setTheme = async name => {
  if (await evaluate('document.documentElement.dataset.theme') !== name) {
    await evaluate("document.querySelector('.focus-theme-toggle')?.click()");
  }
  await wait(() => evaluate(`document.documentElement.dataset.theme === ${JSON.stringify(name)}`), `theme ${name}`);
};
const setSize = async (width, height) => {
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 });
  await send('Emulation.setTouchEmulationEnabled', { enabled: width < 500 });
  const dimensions = await evaluate('({width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth})');
  assert.equal(dimensions.width, width);
  assert.ok(dimensions.scrollWidth <= width, `Horizontal overflow ${JSON.stringify(dimensions)}`);
  return dimensions;
};
const capture = async (name, theme, width, height) => {
  await setTheme(theme);
  const geometry = await setSize(width, height);
  await new Promise(resolve => setTimeout(resolve, 180));
  const shot = await send('Page.captureScreenshot', { format: 'png', fromSurface: true });
  await writeFile(join(output, `${name}.png`), Buffer.from(shot.data, 'base64'));
  return { file: `${name}.png`, theme, ...geometry };
};

await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: `${ui}/profile` });
await hasText('历史验证证据需要重新核对');
await hasText('证据状态：已失效');
await hasText('开始重新验证');
const shots = [];
shots.push(await capture('profile-premium-desktop', 'premium', 1440, 1000));
shots.push(await capture('profile-noir-mobile', 'noir', 390, 844));

// Exercise the actual profile CTA and verify it navigates to the server-created session.
await evaluate("[...document.querySelectorAll('button')].find(button => button.textContent.includes('开始重新验证'))?.click()");
await hasText('Riverside fieldwork v2');

// Resume the completed historical review record as the UI does after a real review submission.
await evaluate("sessionStorage.setItem('unlearnloop.real.active-review.v1', 'phase6-1-review-item')");
await send('Page.navigate', { url: `${ui}/review` });
await hasText('这条历史评分目前不作为保持证据');
shots.push(await capture('invalid-review-premium-desktop', 'premium', 1440, 1000));
shots.push(await capture('invalid-review-noir-mobile', 'noir', 390, 844));

assert.deepEqual(browserErrors, [], `Browser exceptions: ${browserErrors.join('; ')}`);
const report = {
  browser: 'Headless Chrome via Chrome DevTools Protocol',
  api: 'isolated Uvicorn/FastAPI + SQLite fixture; rules provider; remote models disabled',
  verified: ['profile shows invalidated historical evidence and revalidation CTA',
    'revalidation CTA opens the eligible v2 Matching Headings session',
    'completed historical review shows retained history without current retention claim',
    'desktop 1440px and mobile 390px have no horizontal overflow',
    'Premium and Noir themes render with the expected evidence warning'],
  screenshots: shots,
  browser_errors: browserErrors,
};
await writeFile(join(output, 'browser-evidence.json'), JSON.stringify(report, null, 2), 'utf8');
console.log(JSON.stringify(report, null, 2));
socket.close();
