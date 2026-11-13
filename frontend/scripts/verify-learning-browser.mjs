// Run against an isolated seeded backend with MODEL_PROVIDER=fake and an Edge
// instance started with --remote-debugging-port. No browser package is required.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const ui = process.env.SMOKE_UI_URL ?? 'http://127.0.0.1:15174';
const api = process.env.SMOKE_API_URL ?? 'http://127.0.0.1:18001';
const cdp = process.env.SMOKE_CDP_URL ?? 'http://127.0.0.1:19223';
const output = process.env.SMOKE_OUTPUT_DIR;
const targets = await (await fetch(`${cdp}/json/list`)).json();
const target = targets.find((item) => item.type === 'page' && (item.url === 'about:blank' || item.url.startsWith(ui)));
assert.ok(target, 'A blank or application browser page must be available.');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let sequence = 0;
const pending = new Map();
const browserErrors = [];
const captureWarnings = [];
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
const visible = (text) => evaluate(`document.body.innerText.includes(${JSON.stringify(text)})`);
const getSession = async () => {
  const id = await evaluate(`sessionStorage.getItem('unlearnloop.real.active-session.v1')`);
  return id ? (await fetch(`${api}/api/v1/sessions/${id}`)).json() : null;
};
const waitQuestion = async (role) => {
  await wait(async () => {
    const session = await getSession();
    return session?.current_question?.question_role === role && await visible(session.current_question.prompt_text);
  }, `server-assigned ${role} shown in the center workspace`);
  return getSession();
};
const answer = async (text, label = '提交作答') => {
  assert.equal(await evaluate(`(() => { const field = document.querySelector('textarea'); if (!field || field.disabled) return false; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, ${JSON.stringify(text)}); field.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`), true);
  await wait(() => click(label), 'enabled submit button');
};
const capture = async (name, width, height) => {
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 });
  await send('Page.bringToFront');
  await new Promise((resolve) => setTimeout(resolve, 250));
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, `${width}px viewport has no page overflow`);
  if (output) {
    await mkdir(output, { recursive: true });
    try {
      const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false, fromSurface: true });
      await writeFile(join(output, `${name}.png`), Buffer.from(data, 'base64'));
    } catch (error) { captureWarnings.push(`${name}: ${error.message}`); }
  }
};

try {
  if (process.env.SMOKE_TRANSFER === 'true') {
    const sessions = await (await fetch(`${api}/api/v1/sessions?learner_id=default_learner`)).json();
    const histories = await Promise.all(sessions.map(async (session) => (await fetch(`${api}/api/v1/sessions/${session.id}/attempts`)).json()));
    assert.equal(histories.flat().some((attempt) => attempt.question_role === 'transfer_check'), false,
      'Full smoke requires a fresh isolated SQLite database; it never deletes or resets existing records.');
  }
  console.log('Browser: opening Focus home');
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.bringToFront');
  // This dedicated test browser may still point at a prior isolated database.
  // Clear only its page-local pointer/intent storage; never delete server records.
  if (target.url.startsWith(ui)) await evaluate('sessionStorage.clear()');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: ui });
  await wait(() => visible('选择学习主题'), 'Focus home');
  await capture('focus-home-desktop', 1440, 1050);
  assert.equal(await evaluate(`(() => { const topic = [...document.querySelectorAll('.wb-topic-option')].find(b => b.textContent.includes('for 循环')); if (!topic) return false; topic.click(); return true; })()`), true);
  const previousSession = await getSession();
  await wait(() => click('为此知识点创建会话'), 'create a real session');
  await wait(async () => { const session = await getSession(); return session && session.id !== previousSession?.id; }, 'created session');
  assert.equal(await click('继续学习'), true);
  await waitQuestion('initial');
  await answer('999');
  await wait(() => visible('正在理解这次作答'), 'real diagnosis');
  await wait(() => click('请求 Agent 执行下一诊断步骤'), 'first Agent step');
  await waitQuestion('diagnostic_followup');
  await answer('需要逐轮跟踪变量，当前还不确定。');
  await wait(() => click('请求 Agent 执行下一诊断步骤'), 'second Agent step');
  const practice = await waitQuestion('targeted_practice');
  console.log('Browser: second Agent step dispatched targeted practice');
  assert.ok(practice.active_diagnostic_case_id);
  assert.equal(await visible('离线模拟模型'), true);
  await evaluate(`document.querySelector('.focus-evidence-disclosure').open = true`);
  assert.ok(await evaluate(`document.querySelectorAll('.wb-diagnostic-hypothesis').length`) >= 2);
  assert.ok(await evaluate(`document.querySelectorAll('.wb-evidence-row').length`) >= 2);
  await capture('focus-practice-diagnosis-desktop', 1440, 1050);
  await capture('focus-practice-diagnosis-mobile', 390, 844);
  await send('Page.reload');
  await waitQuestion('targeted_practice');
  const recovered = await getSession();
  assert.equal(recovered.current_question_id, practice.current_question_id);
  assert.equal(recovered.active_diagnostic_case_id, practice.active_diagnostic_case_id);
  assert.equal(await click('请求 Agent 执行下一诊断步骤'), false, 'unanswered practice prevents another Agent step');
  assert.equal(await click('演示'), true);
  await wait(() => evaluate(`Boolean(document.querySelector('.focus-demo-workspace'))`), 'Demo isolation');
  assert.equal(await evaluate(`Boolean(document.querySelector('#real-answer'))`), false);
  assert.equal(await click('真实'), true);
  await waitQuestion('targeted_practice');
  assert.equal((await getSession()).id, practice.id);
  if (process.env.SMOKE_TRANSFER === 'true') {
    // A browser-level transport failure must preserve the exact submission intent.
    await send('Network.enable');
    await send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
    await answer('6');
    await wait(() => visible('NETWORK_ERROR'), 'real network failure');
    assert.equal(await evaluate(`document.querySelector('textarea').value`), '6');
    const pendingBeforeReload = await evaluate(`sessionStorage.getItem('unlearnloop.real.pending-attempt.v1.${practice.id}')`);
    assert.ok(pendingBeforeReload);
    await send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
    await send('Page.reload');
    await wait(() => visible('恢复上次作答结果'), 'pending attempt restored');
    assert.equal(await evaluate(`sessionStorage.getItem('unlearnloop.real.pending-attempt.v1.${practice.id}')`), pendingBeforeReload);
    assert.equal(await click('恢复上次作答结果'), true);
    const firstTransfer = await waitQuestion('transfer_check');
    assert.equal(firstTransfer.knowledge_state_status, 'insufficient_evidence');
    assert.equal(firstTransfer.current_question.id, 'q_py_loop_transfer_01');
    assert.equal(await click('迁移验证'), true);
    await wait(() => evaluate(`Boolean(document.querySelector('#transfer-answer'))`), 'transfer form');
    await capture('focus-transfer-desktop', 1440, 1050);
    await send('Page.reload');
    await waitQuestion('transfer_check');
    assert.equal((await getSession()).current_question_id, firstTransfer.current_question_id);
    await answer('3 15', '提交迁移验证');
    await wait(async () => (await getSession())?.latest_attempt_result?.next_action === 'transfer_failed_needs_practice' && await visible('迁移验证未通过'), 'failed transfer result');
    assert.equal(await click('返回学习与诊断'), true);
    await wait(() => click('请求 Agent 执行下一诊断步骤'), 'further targeted intervention');
    const secondPractice = await waitQuestion('targeted_practice');
    assert.equal(secondPractice.current_question_id, 'q_py_loop_practice_02');
    await answer('8；逐轮加上 0、1、2、3。');
    const secondTransfer = await waitQuestion('transfer_check');
    assert.equal(secondTransfer.current_question_id, 'q_py_loop_transfer_02');
    assert.equal(secondTransfer.active_diagnostic_case_id, practice.active_diagnostic_case_id);
    assert.equal(await click('迁移验证'), true);
    await wait(() => evaluate(`Boolean(document.querySelector('#transfer-answer'))`), 'second transfer form');
    await answer('3 60', '提交迁移验证');
    await wait(() => visible('本次独立迁移验证通过'), 'independent transfer passes');
    await wait(() => visible('长期保持尚未验证'), 'limited mastery scope');
    const verified = await getSession();
    assert.equal(verified.knowledge_state_status, 'stable');
    assert.equal(verified.latest_attempt_result.diagnostic_case_id, practice.active_diagnostic_case_id);
    assert.equal(verified.latest_attempt_result.evaluation_source, 'rule_check');
    assert.equal(await click('结束本次学习'), true);
    await wait(async () => (await getSession())?.status === 'completed', 'explicit session completion');
    await send('Page.reload');
    await wait(() => visible('本次独立迁移验证通过'), 'persisted transfer evaluation after refresh');
    await capture('focus-transfer-result-mobile', 390, 844);
    const history = await (await fetch(`${api}/api/v1/sessions/${practice.id}/attempts`)).json();
    assert.equal(history.filter((attempt) => attempt.question_id === 'q_py_loop_practice_01').length, 1);
    console.log('Browser: network retry/refresh, practice, failed transfer, new intervention, fresh transfer, completion and result recovery passed');
  }
  assert.deepEqual(browserErrors, []);
  console.log(JSON.stringify({ result: 'passed', session_id: practice.id, diagnostic_case_id: practice.active_diagnostic_case_id, current_question_id: practice.current_question_id, checked: ['Focus desktop/mobile DOM layout', 'server question', 'wrong answer diagnosis', 'followup answer', 'second Agent step assigns practice', 'hypotheses and evidence DOM', 'refresh recovery', 'unanswered-step guard', 'Demo/Real isolation'], screenshots: output ?? null, captureWarnings }, null, 2));
} catch (error) {
  console.error(error);
  try { console.error(await evaluate('document.body.innerText')); } catch { /* Browser may be unavailable. */ }
  process.exitCode = 1;
} finally {
  socket.close();
}
