import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const ui = process.env.SMOKE_UI_URL;
const api = process.env.SMOKE_API_URL;
const cdp = process.env.SMOKE_CDP_URL;
const output = process.env.SMOKE_OUTPUT_DIR;
const clockFile = process.env.TFNG_BROWSER_CLOCK;
assert.ok(ui && api && cdp && output && clockFile, 'Use an isolated test server, browser, clock file and output folder.');
const targets = await (await fetch(`${cdp}/json/list`)).json();
const target = targets.find((item) => item.type === 'page' && (item.url === 'about:blank' || item.url.startsWith(ui)));
assert.ok(target, 'A blank or application browser page must be available.');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let sequence = 0;
const pending = new Map();
const browserErrors = [];
socket.onmessage = ({ data }) => {
  const message = JSON.parse(data);
  if (message.id) {
    const operation = pending.get(message.id);
    if (!operation) return;
    pending.delete(message.id);
    if (message.error) operation.reject(new Error(JSON.stringify(message.error)));
    else operation.resolve(message.result);
  } else if (message.method === 'Runtime.exceptionThrown') browserErrors.push(message.params.exceptionDetails.text);
};
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
  pending.set(id, { resolve: (value) => { clearTimeout(timer); resolve(value); }, reject: (error) => { clearTimeout(timer); reject(error); } });
  socket.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const response = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
  return response.result.value;
};
const wait = async (check, description) => {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 120));
  }
  throw new Error(`Timed out: ${description}`);
};
const click = (label) => evaluate(`(() => { const button = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(label)} && !b.disabled); if (!button) return false; button.click(); return true; })()`);
const observations = [];
const request = async (path, method = 'GET', body) => {
  const response = await fetch(`${api}/api/v1${path}`, {
    method, ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  });
  assert.ok(response.ok, `${method} ${path} ${response.status}: ${response.ok ? '' : await response.text()}`);
  return response.json();
};
const shown = text => evaluate(`document.querySelector('#error-dna')?.innerText.includes(${JSON.stringify(text)}) ?? false`);
const press = label => wait(() => click(label), `enabled action ${label}`);
const theme = async value => {
  if (await evaluate('document.documentElement.dataset.theme') !== value) {
    await evaluate(`document.querySelector('.focus-theme-toggle').click()`);
  }
  await wait(async () => await evaluate('document.documentElement.dataset.theme') === value, `${value} theme`);
};
const layout = async (width, height) => {
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 });
  await send('Emulation.setTouchEmulationEnabled', { enabled: width < 500 });
  await wait(async () => await evaluate('innerWidth') === width, `${width}px viewport`);
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'page has no horizontal overflow');
  assert.equal(await evaluate(`(() => { const panel = document.querySelector('#error-dna'); return panel.scrollWidth <= panel.clientWidth; })()`), true, 'inspector has no horizontal overflow');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.error-dna-grid')).gridTemplateColumns.split(' ').length`), width < 500 ? 1 : 2);
  if (width < 500) {
    const targets = await evaluate(`[...document.querySelectorAll('.focus-nav-links button')].map(button => { const { left, right, height } = button.getBoundingClientRect(); return { left, right, height }; })`);
    assert.equal(targets.length, 5);
    targets.forEach((target, i) => {
      assert.ok(target.height >= 44 && target.left >= 0 && target.right <= width);
      if (i > 0) assert.ok(target.left >= targets[i - 1].right, 'navigation targets do not overlap');
    });
  }
};
const tapNavigation = async label => {
  const touch = await evaluate(`(() => { const button = [...document.querySelectorAll('.focus-nav-links button')].find(item => item.textContent.trim() === ${JSON.stringify(label)}); const rect = button.getBoundingClientRect(); return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }; })()`);
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [touch] });
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
};
const luminance = color => {
  const channels = color.match(/\d+(?:\.\d+)?/g).slice(0, 3).map(value => Number(value) / 255);
  const linear = channels.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
};
const capture = async (name, width, height, themeName) => {
  await theme(themeName);
  await layout(width, height);
  await evaluate(`document.querySelector('#error-dna').scrollIntoView()`);
  await new Promise(resolve => setTimeout(resolve, 280));
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false, fromSurface: true });
  await writeFile(join(output, `${name}.png`), Buffer.from(data, 'base64'));
  const details = await evaluate(`(() => { const panel = document.querySelector('#error-dna'); const heading = panel.querySelector('h2'); const overview = panel.querySelector('.error-dna-overview'); return { viewport: [innerWidth, innerHeight], scrollWidth: document.documentElement.scrollWidth, theme: document.documentElement.dataset.theme, heading: heading.textContent, label: panel.getAttribute('aria-labelledby'), overview: overview.innerText, overviewHeight: overview.offsetHeight, conclusion: panel.querySelector('.error-dna-conclusion').innerText, next: panel.querySelector('.error-dna-next').innerText, collapsedEvidence: !panel.querySelector('.error-dna-cause details[open]'), foreground: getComputedStyle(panel.querySelector('header p')).color, background: getComputedStyle(panel).backgroundColor }; })()`);
  const [light, dark] = [luminance(details.foreground), luminance(details.background)].sort((a, b) => b - a);
  const contrast = (light + .05) / (dark + .05);
  assert.ok(contrast >= 4.5, `inspector body text contrast ${contrast}`);
  if (width === 390) assert.ok(details.overviewHeight <= 90, 'mobile status area stays compact');
  observations.push({ screenshot: name, ...details, bodyTextContrast: Number(contrast.toFixed(2)) });
};
const start = async (variant, tag) => {
  await request('/profile/exam-preparation', 'PUT', { exam_variant: variant });
  return request('/sessions', 'POST', { topic_id: `ielts-tfng-${tag}-reading-english`, exam_variant: variant });
};
const openSession = async session => {
  await evaluate(`sessionStorage.setItem('unlearnloop.real.active-session.v1', ${JSON.stringify(session.id)})`);
  await send('Page.navigate', { url: `${ui}/learning` });
  await wait(() => shown('学习证据时间线'), `restored session ${session.id}`);
};
const fill = async (selector, answer) => {
  await wait(() => evaluate(`document.querySelector(${JSON.stringify(selector)})?.disabled === false`), `field ${selector}`);
  assert.equal(await evaluate(`(() => { const field = document.querySelector(${JSON.stringify(selector)}); if (field.disabled) return false; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, ${JSON.stringify(answer)}); field.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`), true);
};
const submit = async (answer, field = '#real-answer', action = '提交作答') => {
  await fill(field, answer);
  await press(action);
};
const waitQuestion = async (sessionId, id) => {
  await wait(async () => {
    const session = await request(`/sessions/${sessionId}`);
    return session.current_question_id === id && await evaluate(`document.querySelector('.focus-question-prompt')?.textContent === ${JSON.stringify(session.current_question?.prompt_text)}`);
  }, `question ${id}`);
};
const diagnoseInBrowser = async (session, tag, target, showTraining = false) => {
  const prefix = `ielts-tfng-${tag}`;
  await submit('FALSE');
  await wait(() => shown('规则模式'), 'rule mode');
  await press('继续收集证据');
  await waitQuestion(session.id, `${prefix}-locate`);
  await submit(target === 'logic' ? 'B' : 'A');
  await press('继续收集证据');
  await waitQuestion(session.id, `${prefix}-logic`);
  await submit(target === 'logic' ? 'FALSE' : 'NOT GIVEN');
  await press('继续收集证据');
  await waitQuestion(session.id, `${prefix}-practice-${target}`);
  await wait(() => shown('获得支持'), 'supported hypothesis visible');
  assert.ok(await shown('支持度降低'));
  if (showTraining) await capture('premium-training-mobile', 390, 844, 'premium');
  await press('继续针对性训练');
  assert.equal(await evaluate('document.activeElement.id'), 'real-answer');
  await submit(target === 'logic' ? 'NOT GIVEN' : 'B');
};
const reviewInBrowser = async (session, answer, expected, showDue = false) => {
  await press('刷新证据');
  await wait(() => shown('已到期'), 'server marks review due');
  if (showDue) await capture('noir-due-mobile', 390, 844, 'noir');
  await press('前往复习');
  await press('开始复习');
  await wait(() => evaluate('document.querySelector("#review-answer") !== null'), 'review answer field');
  await submit(answer, '#review-answer', '提交复习作答');
  await wait(async () => {
    const reviews = await request('/reviews?status=completed');
    return reviews.some(item => item.session_id === session.id && item.attempt_id);
  }, 'completed review persisted');
  await press('阅读');
  await wait(() => shown(expected), expected);
};

try {
  await mkdir(output, { recursive: true });
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: `${ui}/learning` });
  await wait(() => evaluate('document.querySelector(".focus-app") !== null'), 'application shell');
  assert.equal((await request('/sessions?learner_id=default_learner')).length, 0, 'fresh isolated server required');
  const academic = await start('academic', 'acad');
  await openSession(academic);
  await wait(() => shown('尚无已保存的作答'), 'empty state');
  await theme('premium');
  await fill('#real-answer', 'FALSE');
  await theme('noir');
  assert.equal(await evaluate('document.querySelector("#real-answer").value'), 'FALSE');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.focus-learning-materials')).backgroundColor`), 'rgb(247, 244, 234)');
  await send('Page.reload');
  await wait(() => evaluate('document.querySelector("#real-answer")?.value === "FALSE"'), 'draft after reload');
  assert.equal(await evaluate('document.documentElement.dataset.theme'), 'noir');
  await diagnoseInBrowser(academic, 'acad', 'logic');
  await waitQuestion(academic.id, 'ielts-tfng-acad-transfer-logic');
  await submit('NOT GIVEN');
  await wait(() => shown('独立迁移已通过'), 'verified transfer');
  await wait(() => shown('尚未到期'), 'pending review');
  assert.ok(await shown('尚无延迟保持证据'));
  assert.equal(await click('前往复习'), false);
  await send('Network.setBlockedURLs', { urls: ['*/api/v1/reviews*', '*/api/v1/diagnoses/*'] });
  await press('刷新证据');
  await wait(() => shown('诊断证据读取失败'), 'diagnosis request error');
  await wait(() => shown('复习记录读取失败'), 'review request error');
  await send('Network.setBlockedURLs', { urls: [] });
  await press('刷新证据');
  await wait(() => shown('尚未到期'), 'recover from failed requests');
  await wait(() => shown('规则模式'), 'diagnosis restored');
  await writeFile(clockFile, '2026-11-13T08:00:00+00:00');
  await reviewInBrowser(academic, 'NOT GIVEN', '本次延迟保持已验证');
  await capture('premium-desktop', 1440, 1000, 'premium');
  await capture('noir-desktop', 1440, 1000, 'noir');
  assert.equal(await evaluate(`document.querySelectorAll('.error-dna details[open]').length`), 0);
  assert.ok(await shown('支持 2 · 削弱 2'));
  await evaluate(`document.querySelector('.error-dna-cause summary').focus()`);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r', unmodifiedText: '\r' });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  await wait(() => shown('按题目规则评判，仅反映本次作答'), 'keyboard opens localized evidence');
  assert.equal(await shown('Deterministic rule evaluation'), false, 'original technical note is in the audit disclosure');
  await capture('premium-expanded-desktop', 1440, 1000, 'premium');
  await evaluate(`document.querySelector('.error-dna-audit summary').click()`);
  assert.ok(await shown('Deterministic rule evaluation'));
  await evaluate(`document.querySelector('.error-dna-audit summary').click(); document.querySelector('.error-dna-cause summary').click()`);
  await evaluate(`document.querySelector('.focus-theme-toggle').focus()`);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  assert.equal(await evaluate(`document.activeElement.matches(':focus-visible') && getComputedStyle(document.activeElement).outlineStyle !== 'none'`), true);
  observations.push({ scenario: 'Academic logic → transfer → delayed review passed', sessionId: academic.id, draftRetainedOnThemeAndReload: true, requestErrorsRecovered: true, keyboardFocusVisible: true, keyboardDisclosureOpened: true, technicalNoteInAudit: true });

  const general = await start('general_training', 'gt');
  await openSession(general);
  await layout(390, 844);
  await tapNavigation('诊断洞察');
  await wait(() => evaluate(`location.pathname === '/diagnosis'`), 'mobile diagnosis navigation');
  await tapNavigation('阅读');
  await wait(() => evaluate(`location.pathname === '/learning'`), 'mobile reading navigation');
  await diagnoseInBrowser(general, 'gt', 'location', true);
  await waitQuestion(general.id, 'ielts-tfng-gt-transfer-location');
  await submit('B');
  await wait(() => shown('独立迁移已通过'), 'location transfer passed');
  await wait(() => shown('尚未到期'), 'location pending review');
  await capture('premium-mobile', 390, 844, 'premium');
  await writeFile(clockFile, '2026-11-15T08:00:00+00:00');
  await reviewInBrowser(general, 'A', '最近一次复习未通过', true);
  await wait(() => shown('需要继续练习'), 'failed review updates state');
  await capture('noir-mobile', 390, 844, 'noir');
  observations.push({ scenario: 'General Training location → transfer → delayed review failed', sessionId: general.id, touchNavigation: true, navMinHeight: 44 });

  const failure = await start('academic', 'acad');
  await openSession(failure);
  await diagnoseInBrowser(failure, 'acad', 'location');
  await waitQuestion(failure.id, 'ielts-tfng-acad-transfer-location');
  await submit('A');
  await wait(() => shown('需要继续练习'), 'transfer failure');
  assert.ok(await shown('本题未通过'));
  observations.push({ scenario: 'Academic transfer failure', sessionId: failure.id });

  const exhausted = await start('academic', 'acad');
  await openSession(exhausted);
  await diagnoseInBrowser(exhausted, 'acad', 'logic');
  await wait(() => shown('暂无匹配的独立迁移题'), 'transfer pool unavailable');
  assert.ok(await shown('证据不足'));
  assert.equal(await evaluate(`[...document.querySelectorAll('.error-dna-next button')].some(button => button.textContent.includes('迁移题'))`), false);
  observations.push({ scenario: 'Academic transfer unavailable after prior use', sessionId: exhausted.id });
  assert.deepEqual(browserErrors, []);
  await writeFile(join(output, 'browser-observations.json'), JSON.stringify({ observations, browserErrors }, null, 2));
  console.log(JSON.stringify(observations, null, 2));
} finally {
  socket.close();
}
