import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const { SMOKE_UI_URL: ui, SMOKE_API_URL: api, SMOKE_CDP_URL: cdp, SMOKE_OUTPUT_DIR: output, PHASE5_CLOCK: clock } = process.env;
assert.ok(ui && api && cdp && output && clock, 'Use the isolated Python browser runner.');
const tabs = await (await fetch(`${cdp}/json/list`)).json();
const target = tabs.find(tab => tab.type === 'page');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
const pending = new Map();
const traffic = new Map();
const checks = {};
const shots = [];
const browserErrors = [];
const learnConsoleErrors = [];
let checkingLearn = false;
let sequence = 0;
let heldResponse;
let heldRestore;
let restoreTarget;
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
  pending.set(id, message => {
    clearTimeout(timer);
    if (message.error) reject(new Error(`${method}: ${JSON.stringify(message.error)}`));
    else resolve(message.result);
  });
  socket.send(JSON.stringify({ id, method, params }));
});
socket.onmessage = ({ data }) => {
  const message = JSON.parse(data);
  if (message.id) {
    pending.get(message.id)?.(message);
    pending.delete(message.id);
    return;
  }
  const p = message.params;
  if (message.method === 'Runtime.exceptionThrown') browserErrors.push(p.exceptionDetails.text);
  if (message.method === 'Runtime.consoleAPICalled' && p.type === 'error') {
    browserErrors.push(p.args.map(arg => arg.description ?? arg.value).join(' '));
  }
  if (checkingLearn && message.method === 'Log.entryAdded' && p.entry.level === 'error') {
    learnConsoleErrors.push({ message: p.entry.text, url: p.entry.url });
  }
  if (message.method === 'Fetch.requestPaused') {
    if (restoreTarget && p.request.method === 'GET' && p.request.url.endsWith(restoreTarget)) {
      heldRestore = p.requestId;
    } else if (p.request.method === 'POST') heldResponse = { status: p.responseStatusCode, url: p.request.url };
    else void send('Fetch.continueResponse', { requestId: p.requestId }).catch(error => browserErrors.push(error.message));
  }
  if (message.method === 'Network.requestWillBeSent' && p.request.url.startsWith(`${api}/api/v1/`)) {
    traffic.set(p.requestId, { method: p.request.method, url: p.request.url, request: p.request.postData });
  }
  const entry = traffic.get(p?.requestId);
  if (entry && message.method === 'Network.responseReceived') entry.status = p.response.status;
  if (entry && message.method === 'Network.loadingFailed') entry.failure = p.errorText;
};
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const evaluate = async expression => {
  const value = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  assert.ok(!value.exceptionDetails, JSON.stringify(value.exceptionDetails));
  return value.result.value;
};
const wait = async (predicate, label) => {
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    const value = await predicate();
    if (value) return value;
    await delay(100);
  }
  const page = await evaluate('document.body.innerText.slice(-2600)');
  throw new Error(`Timed out: ${label}\n${page}`);
};
const js = JSON.stringify;
const text = value => wait(() => evaluate(`document.body.innerText.includes(${js(value)})`), value);
const press = (label, scope = 'body') => wait(() => evaluate(`(() => {
  const button = [...document.querySelectorAll(${js(scope + ' button')})].find(
    b => b.textContent.trim() === ${js(label)} && !b.disabled);
  if (!button) return false;
  button.click();
  return true;
})()`), `button ${label}`);
const navigate = path => send('Page.navigate', { url: `${ui}${path}` });
const theme = async name => {
  if (await evaluate('document.documentElement.dataset.theme') !== name) {
    await evaluate("document.querySelector('.focus-theme-toggle').click()");
  }
  await wait(() => evaluate(`document.documentElement.dataset.theme === ${js(name)}`), name);
};
const layout = async (width, height) => {
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 });
  await send('Emulation.setTouchEmulationEnabled', { enabled: width < 500 });
  await wait(() => evaluate(`innerWidth === ${width}`), `${width}px`);
  const geometry = await evaluate(`(() => {
    const grid = document.querySelector('.mh-grid');
    const option = document.querySelector('.mh-options li span');
    return { width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
      columns: grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : null,
      minTarget: grid ? Math.min(...[...grid.querySelectorAll('select, .mh-field a, button')].map(e => e.getBoundingClientRect().height)) : null,
      readingPaper: grid ? getComputedStyle(grid.querySelector('.mh-passage')).backgroundColor : null,
      optionWrap: option ? getComputedStyle(option).overflowWrap : null };
  })()`);
  assert.ok(geometry.scrollWidth <= width, `Horizontal overflow: ${js(geometry)}`);
  if (geometry.columns !== null) {
    assert.equal(geometry.columns, width === 390 ? 1 : 2);
    assert.ok(geometry.minTarget >= 44);
    assert.equal(geometry.readingPaper, 'rgb(247, 244, 234)');
    assert.equal(geometry.optionWrap, 'anywhere');
  }
  return geometry;
};
const capture = async (name, selector = 'main', width = 1440, height = 1000) => {
  const geometry = await layout(width, height);
  await evaluate(`document.querySelector(${js(selector)})?.scrollIntoView({block:'start'})`);
  await delay(220);
  const { data } = await send('Page.captureScreenshot', { format: 'png', fromSurface: true });
  await writeFile(join(output, `${name}.png`), Buffer.from(data, 'base64'));
  shots.push({ screenshot: `${name}.png`, theme: await evaluate('document.documentElement.dataset.theme'), ...geometry });
};
const read = async path => {
  const response = await fetch(`${api}/api/v1${path}`);
  assert.ok(response.ok, `${path} ${response.status}`);
  return response.json();
};
const sessionId = () => evaluate("sessionStorage.getItem('unlearnloop.real.active-session.v1')");
const initialPack = JSON.parse(await readFile(new URL('../../backend/app/content/ielts_matching_headings_pack.json', import.meta.url)));
const diagnosticPack = JSON.parse(await readFile(new URL('../../backend/app/content/ielts_matching_headings_diagnostics.json', import.meta.url)));
const privateFixtures = new Map([...initialPack.topics.flatMap(topic => topic.questions),
  ...Object.values(diagnosticPack.questions).flat()].map(question => [question.id, question.reading_group.private_rules.answers]));
const assigned = async () => (await read(`/sessions/${await sessionId()}`)).current_question;
const assertGroup = async role => {
  await wait(() => evaluate(`document.querySelector('.mh-question .focus-eyebrow')?.textContent.includes('Matching Headings')`), 'rendered Matching Headings');
  const question = await assigned();
  assert.equal(question.question_role, role);
  assert.ok(question.group_version_id && question.group_display);
  const exposed = JSON.stringify(question);
  assert.ok(!/"(?:standard_answer|answers|private_rules|distractors|probes|task_versions|answer_explanation)"/.test(exposed));
  return question;
};
const fill = async selections => {
  for (const [item, value] of Object.entries(selections)) {
    await wait(() => evaluate(`(() => {
      const select = [...document.querySelectorAll('.mh-field')].find(e => e.dataset.itemId === ${js(item)})?.querySelector('select');
      if (!select || select.matches(':disabled') || [...select.options].find(o => o.value === ${js(value)})?.disabled) return false;
      select.value = ${js(value)};
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`), `select ${item}`);
  }
};
const start = async (variant, matching = true) => {
  await navigate('/');
  await wait(() => evaluate(`(() => {
    const button = [...document.querySelectorAll('.exam-choice')].find(b => b.textContent.includes(${js(variant === 'academic' ? 'Academic' : 'General Training')}));
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`), 'exam choice');
  await wait(() => evaluate(`[...document.querySelectorAll('.exam-choice')].some(b => b.getAttribute('aria-pressed') === 'true' && b.textContent.includes(${js(variant === 'academic' ? 'Academic' : 'General Training')}))`), 'saved exam');
  await openReading();
  await wait(() => evaluate(`Boolean(document.querySelector('.wb-topic-option, .focus-session-meta'))`), 'reading catalog or restored session');
  if (await evaluate("Boolean(document.querySelector('.focus-session-meta'))")) await press('选择其他阅读任务');
  await wait(() => evaluate(`(() => {
    const button = [...document.querySelectorAll('.wb-topic-option')].find(b => ${matching ? "b.textContent.includes('Matching Headings')" : "/True|TFNG|判断/i.test(b.textContent)"});
    if (!button) return false;
    button.click();
    return true;
  })()`), 'eligible reading topic');
  await press('开始阅读');
  if (matching) await assertGroup('initial');
  else await wait(() => evaluate("Boolean(document.querySelector('textarea#real-answer'))"), 'legacy answer textarea');
  return sessionId();
};
const diagnoseAndPractice = async (probeSelections, screenshot) => {
  await text('规则模式');
  await press('继续收集证据');
  await assertGroup('diagnostic_followup');
  await fill(probeSelections);
  await press('提交作答');
  await press('继续收集证据');
  const practice = await assertGroup('targeted_practice');
  if (screenshot) await capture(screenshot, '.mh-question');
  await fill(privateFixtures.get(practice.id));
  await press('提交作答');
  await text('专项训练已通过');
  return practice;
};
const transfer = async () => {
  await press('请求独立迁移题');
  const question = await assertGroup('transfer_check');
  await wait(() => evaluate("location.pathname === '/transfer'"), 'transfer workspace');
  await fill(privateFixtures.get(question.id));
  await press('提交迁移验证');
  await text('本次独立迁移验证通过');
  await text('尚未到期');
  const detail = await read(`/sessions/${await sessionId()}`);
  assert.equal(detail.knowledge_state_status, 'transfer_verified');
  return detail;
};
const getReviewFor = async session => {
  const items = await read('/reviews?status=pending');
  const item = items.find(item => item.session_id === session && item.retention_eligible);
  assert.ok(item?.id, 'A real retention review must be scheduled');
  return item;
};
const startReview = async (topicTitle) => {
  await navigate('/review');
  await wait(() => evaluate(`(() => {
    const row = [...document.querySelectorAll('.focus-review-row')].find(e => e.textContent.includes(${js(topicTitle)}) && !e.querySelector('button')?.disabled && e.querySelector('button'));
    if (!row) return false;
    row.querySelector('button').click();
    return true;
  })()`), 'start due review');
};
const beginReview = async (session, shouldPass) => {
  const item = await getReviewFor(session);
  assert.equal(item.is_due, true);
  await startReview(item.topic_title);
  await text('逐段选择标题');
  const current = await read(`/reviews/${item.id}`);
  assert.equal(current.current_question.question_role, 'review');
  assert.equal(current.current_question.group_version_id, current.group_version_id);
  const selections = { ...privateFixtures.get(current.question_id) };
  if (shouldPass) {
    const [first] = Object.entries(selections);
    await fill(Object.fromEntries([first]));
    await send('Page.reload');
    await text('已完成 1/3');
    await capture('E-review-draft-restored', '.mh-answer', 390, 844);
  }
  if (!shouldPass) {
    const [a, b] = Object.keys(selections);
    [selections[a], selections[b]] = [selections[b], selections[a]];
  }
  await fill(selections);
  await press('提交复习作答');
  await text(shouldPass ? '本次获得延迟保持证据' : '本次复习未通过');
  const done = await read(`/reviews/${item.id}`);
  assert.equal(done.retention_verified, shouldPass);
  assert.ok(done.group_evaluation && done.attempt_id);
  return done;
};
const probeMain = { 'probe-main': 'probe-main-distractor', 'probe-keyword': 'probe-keyword-heading' };
const probeKeyword = { 'probe-main': 'probe-main-heading', 'probe-keyword': 'probe-keyword-distractor' };
const academicPartial = { 'paragraph-a': 'ii', 'paragraph-b': 'iii', 'paragraph-c': 'iv' };
const gtWrong = { 'paragraph-a': 'i', 'paragraph-b': 'v', 'paragraph-c': 'iv' };
const offline = offline => send('Network.emulateNetworkConditions', { offline, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
const key = async (name, code) => {
  const params = { key: name, code: name === ' ' ? 'Space' : name, windowsVirtualKeyCode: code };
  await send('Input.dispatchKeyEvent', { ...params, type: 'rawKeyDown' });
  await send('Input.dispatchKeyEvent', { ...params, type: 'keyUp' });
};
const openReading = async () => {
  await wait(() => evaluate(`(() => {
    const link = document.querySelector('.learn-skill-card[href="/learning"]');
    if (!link) return false;
    link.click();
    return true;
  })()`), 'Learn → Reading');
  await wait(() => evaluate("location.pathname === '/learning' && Boolean(document.querySelector('.focus-reading-page'))"), 'real Reading workspace');
};
const touch = async selector => {
  const point = await evaluate(`(() => {
    const target = document.querySelector(${js(selector)});
    target.scrollIntoView({block: 'center', behavior: 'instant'});
    const {left, top, width, height} = target.getBoundingClientRect();
    return {x: left + width / 2, y: top + height / 2};
  })()`);
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] });
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
};
const verifyLearn = async () => {
  checkingLearn = true;
  await navigate('/');
  await text('IELTS 学习中心');
  await text('未评估');
  const nav = await evaluate(`(() => {
    const nav = document.querySelector('.focus-product-nav');
    return {actions: [...nav.querySelectorAll('a,button')].map(item => item.textContent.trim()),
      planned: [...nav.querySelectorAll('.focus-product-planned')].map(item => item.textContent.trim())};
  })()`);
  assert.deepEqual(nav, { actions: ['Learn'], planned: ['Discover规划中', 'Adapt规划中'] });
  const cards = await evaluate(`[...document.querySelectorAll('a.learn-skill-card')].map(card => ({
    skill: card.querySelector('h2').textContent, route: card.getAttribute('href'), status: card.querySelector('.focus-state-tag').textContent.trim()
  }))`);
  assert.deepEqual(cards, [
    { skill: 'Listening', route: '/learn/listening', status: '规划中' },
    { skill: 'Speaking', route: '/learn/speaking', status: '规划中' },
    { skill: 'Reading', route: '/learning', status: '可练习' },
    { skill: 'Writing', route: '/learn/writing', status: '规划中' },
  ]);
  for (const name of ['premium', 'noir']) {
    await theme(name);
    for (const [width, height, size] of [[1440, 1000, 'desktop'], [390, 844, 'mobile']]) {
      await layout(width, height);
      const geometry = await evaluate(`(() => ({
        columns: getComputedStyle(document.querySelector('.learn-skill-grid')).gridTemplateColumns.split(' ').length,
        targets: [...document.querySelectorAll('.focus-top-nav button, .learn-skill-card, .exam-choice')].map(element => {
          const {width, height, left, right} = element.getBoundingClientRect();
          return {width, height, left, right};
        }),
        lastCardBottom: document.querySelector('.learn-skill-card:last-child').getBoundingClientRect().bottom
      }))()`);
      assert.equal(geometry.columns, width === 390 ? 1 : 2);
      assert.ok(geometry.lastCardBottom <= height, 'All four skills are visible in the first viewport');
      if (width === 390) assert.ok(geometry.targets.every(target =>
        target.width >= 44 && target.height >= 44 && target.left >= 0 && target.right <= width), js(geometry));
      await capture(`learn-${name}-${size}`, 'body', width, height);
    }
  }
  await theme('premium');
  await layout(1440, 1000);
  await evaluate("document.querySelector('.focus-mode-switch button:last-child').focus()");
  for (const { skill } of cards) {
    await key('Tab', 9);
    assert.ok(await evaluate(`(() => {
      const active = document.activeElement;
      return active.matches('.learn-skill-card:focus-visible') && active.querySelector('h2').textContent === ${js(skill)} &&
        getComputedStyle(active).outlineStyle === 'solid' && parseInt(getComputedStyle(active).outlineWidth, 10) >= 3;
    })()`), `Visible keyboard focus on ${skill}`);
  }
  await capture('learn-keyboard-focus', 'body');
  await key('Enter', 13);
  await text('Writing · 写作');
  assert.equal(await evaluate("document.activeElement.tagName"), 'H1');
  assert.equal(await evaluate("location.pathname"), '/learn/writing');
  await text('结构、语言与任务完成度反馈');
  await capture('learn-writing-desktop', 'body');
  await evaluate('history.back()');
  await text('IELTS 学习中心');
  await layout(390, 844);
  await touch('.learn-skill-card[href="/learn/listening"]');
  await text('Listening · 听力');
  await text('音频片段与题目关联');
  assert.equal(await evaluate("document.querySelector('main').querySelectorAll('audio, video, button, input').length"), 0);
  await capture('learn-listening-mobile', 'body', 390, 844);
  await touch('.learn-back-link');
  await text('IELTS 学习中心');
  await touch('.learn-skill-card[href="/learn/speaking"]');
  await text('Speaking · 口语');
  await send('Page.reload');
  await text('录音与转写');
  await text('表达反馈与 AI 口语评价');
  assert.equal(await evaluate("document.querySelector('main').querySelectorAll('audio, video, button, input').length"), 0);
  await theme('noir');
  await capture('learn-speaking-mobile', 'body', 390, 844);
  await touch('.learn-back-link');
  await text('IELTS 学习中心');
  await touch('.learn-skill-card[href="/learning"]');
  await text('请先在 Learn 保存考试类型。');
  assert.equal(await evaluate("location.pathname"), '/learning');
  await navigate('/learn/reading');
  await text('选择阅读任务');
  assert.deepEqual(learnConsoleErrors, []);
  checkingLearn = false;
  return { nav, cards, keyboard: true, touch: true, consoleErrors: learnConsoleErrors };
};
const fillByKeyboard = async selections => {
  for (const [item, choice] of Object.entries(selections)) {
    const control = `[data-item-id="${item}"] select`;
    const steps = await evaluate(`(() => {
      const field = document.querySelector(${js(control)});
      field.focus();
      return [...field.options].filter(option => !option.disabled).findIndex(option => option.value === ${js(choice)});
    })()`);
    assert.ok(steps > 0);
    await key('Home', 36);
    for (let index = 0; index < steps; index++) await key('ArrowDown', 40);
    assert.equal(await evaluate(`document.querySelector(${js(control)}).value`), choice);
  }
};

try {
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Log.enable');
  await layout(1440, 1000);
  checks.learn = await verifyLearn();
  await layout(1440, 1000);
  const a = await start('academic');
  await theme('premium');
  await capture('I-premium-desktop', '.mh-question');
  await fill({ 'paragraph-a': 'ii' });
  assert.equal(await evaluate("document.querySelectorAll('.mh-field select')[1].querySelector('option[value=ii]').disabled"), true);
  assert.equal(await evaluate("document.querySelector('.mh-answer button').disabled"), true);
  await theme('noir');
  await capture('I-noir-desktop', '.mh-question');
  await send('Page.reload');
  await text('已完成 1/3');
  assert.equal(await evaluate("document.querySelector('.mh-field select').value"), 'ii');
  await capture('I-noir-mobile', '.mh-question', 390, 844);
  await theme('premium');
  await capture('I-premium-mobile', '.mh-question', 390, 844);
  // Use actual keyboard events in the select and a touch event on a passage link.
  await evaluate("document.querySelector('.mh-field select').focus()");
  await key('Home', 36);
  await key('ArrowDown', 40);
  assert.ok(await evaluate("document.querySelector('.mh-field select').matches(':focus-visible')"));
  assert.notEqual(await evaluate("document.querySelector('.mh-field select').value"), 'ii');
  const link = await evaluate(`(() => {
    const link = document.querySelector('.mh-field a');
    link.scrollIntoView({block:'center',behavior:'instant'});
    const r = link.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  })()`);
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [link] });
  await delay(100);
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await wait(() => evaluate("location.hash.includes('paragraph-')"), 'touch passage link');
  await wait(() => evaluate(`(() => {
    const paragraph = document.getElementById(location.hash.slice(1));
    const nav = document.querySelector('.focus-top-nav');
    return paragraph.getBoundingClientRect().top >= nav.getBoundingClientRect().bottom;
  })()`), 'paragraph is visible below the sticky mobile navigation');
  await fillByKeyboard(privateFixtures.get((await assigned()).id));
  await capture('L-mobile-answer', '.mh-answer', 390, 844);
  await offline(true);
  await key('Tab', 9);
  assert.ok(await evaluate("document.activeElement === document.querySelector('.mh-answer button')"));
  await key(' ', 32);
  await text('NETWORK_ERROR');
  const pendingBefore = await evaluate(`sessionStorage.getItem('unlearnloop.real.pending-attempt.v1.' + ${js(a)})`);
  assert.ok(pendingBefore);
  await capture('J-offline', '[role=alert].wb-alert');
  await offline(false);
  await send('Page.reload');
  await text('保存着一次尚未确认结果的作答');
  assert.equal(await evaluate(`sessionStorage.getItem('unlearnloop.real.pending-attempt.v1.' + ${js(a)})`), pendingBefore);
  await press('恢复上次作答结果');
  await text('3/3 · 全部正确');
  const aAttempts = await read(`/sessions/${a}/attempts`);
  assert.equal(aAttempts.length, 1);
  assert.equal(aAttempts[0].group_evaluation.outcome, 'correct');
  await capture('A-academic-correct', '.mh-result');
  checks.A = aAttempts[0];
  checks.I = { themes: ['premium', 'noir'], restored: true };
  checks.L = { keyboardSelectedAllAndSubmitted: true, visibleFocus: true, touchedPassageLink: true };

  // Hold the old session response while mounting the workspace. A new task must
  // not be offered until restoration has settled, even under React StrictMode.
  restoreTarget = `/sessions/${a}`;
  await send('Fetch.enable', { patterns: [{ urlPattern: `${api}/api/v1/sessions/${a}`, requestStage: 'Response' }] });
  await navigate('/learning');
  await wait(() => heldRestore, 'delayed old session response');
  await text('正在恢复学习会话');
  assert.equal(await evaluate("Boolean(document.querySelector('.wb-topic-option'))"), false);
  await send('Fetch.continueResponse', { requestId: heldRestore });
  restoreTarget = undefined;
  await send('Fetch.disable');
  await text('选择其他阅读任务');
  checks.sessionRestoreRace = { delayedOldSession: a, catalogBlockedUntilRestored: true };

  const b = await start('academic');
  assert.notEqual(b, a);
  await delay(300);
  assert.equal(await sessionId(), b, 'Old restoration overwrote the new session');
  checks.sessionRestoreRace.newSession = b;
  await fill(academicPartial);
  await send('Fetch.enable', { patterns: [{ urlPattern: `${api}/api/v1/sessions/${b}/attempts`, requestStage: 'Response' }] });
  await press('提交作答');
  await wait(() => heldResponse?.status === 201, 'committed answer response held by CDP');
  await text('REQUEST_TIMEOUT');
  await capture('J-timeout', '[role=alert].wb-alert');
  await send('Fetch.disable');
  await send('Page.reload');
  await text('2/3 · 部分正确');
  await text('规则模式');
  assert.equal(await evaluate(`sessionStorage.getItem('unlearnloop.real.pending-attempt.v1.' + ${js(b)})`), null);
  const bAttempts = await read(`/sessions/${b}/attempts`);
  assert.equal(bAttempts.length, 1);
  checks.J = { replayedOfflineIntent: JSON.parse(pendingBefore).payload.idempotency_key,
    recoveredTimeoutAttempt: bAttempts[0].id, interceptedCommittedStatus: heldResponse.status };
  assert.ok([...traffic.values()].some(entry => entry.status === 201 && entry.request
    && JSON.parse(entry.request).idempotency_key === checks.J.replayedOfflineIntent));
  checks.B = bAttempts[0];
  await capture('B-academic-partial', '.mh-result');
  await evaluate("document.querySelector('.error-dna-audit').open = true");
  await text('评分规则');
  await capture('B-error-dna', '#error-dna');
  await diagnoseAndPractice(probeMain);
  checks.D = await transfer();
  await capture('D-academic-transfer-not-due', '.mh-result');
  assert.equal((await getReviewFor(b)).is_due, false);

  const c = await start('general_training');
  await fill(gtWrong);
  await press('提交作答');
  await text('全部错误');
  const gtPractice = await diagnoseAndPractice(probeMain, 'C-gt-structured-practice');
  assert.equal(gtPractice.id, 'ielts-mh-gt-main-practice');
  checks.C = { sessionId: c, practice: gtPractice.id };
  await capture('C-gt-targeted-training', '#error-dna');
  await transfer();
  await writeFile(clock, '1');
  checks.E = await beginReview(b, true);
  await capture('E-academic-retention-pass', '.focus-review-session');
  checks.F = await beginReview(c, false);
  await capture('F-gt-retention-fail', '.focus-review-session');

  const g = await start('academic');
  await fill(academicPartial);
  await press('提交作答');
  await diagnoseAndPractice(probeMain);
  await press('请求独立迁移题');
  await text('暂无符合当前诊断目标的独立迁移文章');
  await send('Page.reload');
  await text('暂无符合当前诊断目标的独立迁移文章');
  assert.equal(await evaluate("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === '请求独立迁移题')"), false);
  checks.G = await read(`/sessions/${g}`);
  assert.equal(checks.G.can_dispatch_transfer, false);
  await capture('G-transfer-exhausted', '#error-dna');

  await writeFile(clock, '4');
  const reviewItems = await read('/reviews?status=pending');
  const next = reviewItems.find(item => item.session_id === b && item.review_stage === 1);
  assert.ok(next?.is_due);
  await startReview(next.topic_title);
  await text('当前没有可用的独立复习题');
  await send('Page.reload');
  await text('当前没有可用的独立复习题');
  checks.H = await read(`/reviews/${next.id}`);
  assert.equal(checks.H.question_unavailable, true);
  assert.equal(checks.H.retention_verified, false);
  assert.equal(checks.H.attempt_id, null);
  await capture('H-review-exhausted', '.focus-review-session');

  const k = await start('academic', false);
  await wait(() => evaluate("Boolean(document.querySelector('textarea#real-answer'))"), 'legacy answer textarea');
  const legacy = await assigned();
  assert.equal(legacy.question_type, 'multiple_choice');
  await capture('K-tfng-regression', '.focus-question-card');
  await evaluate(`(() => {
    const input = document.querySelector('#real-answer');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'FALSE');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await press('提交作答');
  await text('最近一次作答评价');
  checks.K = (await read(`/sessions/${k}/attempts`))[0];
  assert.equal(checks.K.submitted_answer, 'FALSE');
  assert.equal(checks.K.group_evaluation, null);
  assert.deepEqual(browserErrors, []);
  console.log(`Passed ${Object.keys(checks).length} browser scenarios; ${shots.length} screenshots; ${traffic.size} browser API requests.`);
} finally {
  await writeFile(join(output, 'browser-http-evidence.json'), JSON.stringify({ checks, screenshots: shots, traffic: [...traffic.values()], browserErrors }, null, 2));
  await send('Browser.close').catch(() => {});
  socket.close();
}
