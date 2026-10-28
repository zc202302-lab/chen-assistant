/* Exercise actual page controllers and wx.request with a minimal native API fake. */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');
const root = path.join(__dirname, '..', 'miniprogram');
const appConfig = require(path.join(root, 'app.json'));
const sitemap = require(path.join(root, 'sitemap.json'));
assert.equal(appConfig.sitemapLocation, 'sitemap.json');
assert.equal(sitemap.rules[0].action, 'allow');
const {parseInvite, inviteFromOptions} = require(path.join(root, 'utils/entry'));
const invite = 'test_invitation_for_contract_only_123';
assert.equal(parseInvite(`https://jituan.zbassistant.site/number-submit/${invite}`), invite);
assert.equal(parseInvite('https://evil.example/number-submit/' + invite), '');
assert.equal(parseInvite('admin'), '');
assert.equal(inviteFromOptions({scene: encodeURIComponent('invite=' + invite)}), invite);
assert.equal(inviteFromOptions({scene: '%'}), '');
// Boot actual app and every declared page with isolated CommonJS modules.
// This catches missing files/imports and startup dependence on network or Babel globals;
// it does not replace WeChat's own WXML compiler or device rendering.
for (const pagePath of appConfig.pages) {
  for (const extension of ['js', 'json', 'wxml', 'wxss'])
    assert(fs.existsSync(path.join(root, pagePath + '.' + extension)), pagePath + '.' + extension);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root, pagePath + '.json'))).usingComponents, {});
}
function boot(storageThrows) {
  let appInstance, pageDefinition;
  const cache = new Map();
  const context = vm.createContext({
    App(value) { appInstance = value; },
    Page(value) { pageDefinition = value; },
    getApp() { return appInstance; },
    wx: {
      getStorageSync() { if (storageThrows) throw new Error('storage unavailable'); return ''; },
      request() { throw new Error('startup must not need a network request'); }
    }
  });
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports;
    const module = {exports: {}};
    cache.set(filename, module);
    const source = fs.readFileSync(filename, 'utf8');
    // No regenerator runtime is shipped in this native project.
    assert(!/\basync\s+|\bawait\s+|regeneratorRuntime/.test(source), filename);
    const factory = vm.runInContext('(function(require,module,exports){' + source + '\n})', context);
    factory(request => load(path.resolve(path.dirname(filename), request + '.js')), module, module.exports);
    return module.exports;
  }
  load(path.join(root, 'app.js'));
  for (const pagePath of appConfig.pages) {
    load(path.join(root, pagePath + '.js'));
    const instance = Object.assign({}, pageDefinition, {
      data: JSON.parse(JSON.stringify(pageDefinition.data || {})),
      setData(value) { Object.assign(this.data, value); }
    });
    if (instance.onLoad) instance.onLoad({});
    if (pagePath === appConfig.pages[0]) {
      assert.equal(instance.data.rows.length, 1);
      assert.equal(instance.data.error, '');
      assert.equal(instance.data.submitting, false);
    }
  }
}
boot(false);
boot(true);
let calls = [], navigation = [], requests = [];
const app = {globalData: {lastResult: null}};
global.getApp = () => app;
global.wx = {
  navigateTo: value => navigation.push(value.url),
  navigateBack: value => navigation.push('back'),
  redirectTo: value => navigation.push(value.url),
  request: request => { calls.push(request); requests.push(request); },
  requirePrivacyAuthorize() { throw new Error('manual number input must not force a privacy API popup'); }
};
let definition;
global.Page = value => { definition = value; };
require(path.join(root, 'pages/index/index.js'));
function applyData(instance, update) {
  instance.patches = instance.patches || [];
  instance.patches.push(update);
  for (const [key, value] of Object.entries(update)) {
    const parts = key.replace(/\[(\d+)\]/g, '.$1').split('.');
    let target = instance.data;
    for (const part of parts.slice(0, -1)) target = target[part];
    target[parts.at(-1)] = value;
  }
}
function page(options = {invite}) {
  const instance = {...definition, data: JSON.parse(JSON.stringify(definition.data)),
    setData(update) { applyData(this, update); }};
  instance.onLoad(options);
  return instance;
}
const event = (id, value) => ({currentTarget: {dataset: {id}}, detail: {value}});
const tick = () => new Promise(resolve => setImmediate(resolve));
async function main() {
  const typing = page();
  const firstId = typing.data.rows[0].id;
  typing.focusNumber(event(firstId, ''));
  typing.patches = [];
  const fullNumber = '13800000101';
  for (let i = 1; i <= fullNumber.length; i++) {
    typing.changeNumber(event(firstId, fullNumber.slice(0, i)));
    assert.equal(typing.data.focusedRow, firstId, 'input patch must not reset user focus');
  }
  assert.equal(typing.data.rows[0].value, fullNumber);
  assert(typing.patches.every(patch => !Object.hasOwn(patch, 'rows') && !Object.hasOwn(patch, 'focusedRow')),
    'typing must patch only the current value, never replace input list or reset focus');
  typing.addRow();
  const secondId = typing.data.rows[1].id;
  typing.blurNumber(event(firstId, fullNumber));
  assert.equal(typing.data.focusedRow, secondId, 'late blur of old row must not blur a newly added row');
  typing.focusNumber(event(secondId, ''));
  typing.changeNumber(event(secondId, '13900000102'));
  assert.equal(typing.data.rows[0].value, fullNumber);
  assert.equal(typing.data.rows[1].value, '13900000102');
  const bound = fs.readFileSync(path.join(root, 'pages/index/index.wxml'), 'utf8');
  assert(bound.includes('bindfocus="focusNumber"') && bound.includes('bindblur="blurNumber"'));
  const p = page();
  await p.submit();
  assert.equal(calls.length, 0, 'empty input must not write');
  p.changeNumber(event(p.data.rows[0].id, '13800000101'));
  const sending = p.submit();
  await p.submit();
  await tick();
  assert.equal(calls.length, 1, 'double tap must not double submit');
  const request = requests.shift();
  assert.equal(request.url, 'https://jituan.zbassistant.site/number-submit/mini/submit');
  assert.equal(request.header.Authorization, 'Bearer ' + invite);
  assert.deepEqual(request.data, {numbers: ['13800000101'], consent: true});
  request.fail();
  await sending;
  assert.equal(p.data.rows[0].value, '13800000101', 'network failure retains input');
  assert.equal(p.data.submitting, false);
  const retry = p.submit(); await tick();
  requests.shift().success({statusCode: 200, data: {ok: true, received: 1, added: 1, duplicates: 0, batch: 'batch_for_contract'}});
  await retry;
  assert.equal(app.globalData.lastResult.added, 1);
  assert.equal(p.data.rows[0].value, '');
  assert.equal(navigation.at(-1), '/pages/pending/pending?result=success');
  assert.equal(app.globalData.lastBatch.batch, 'batch_for_contract');
  for (let i = 0; i < 120; i++) p.addRow();
  assert.equal(p.data.rows.length, 100);
  assert.equal(p.data.focusedRow, p.data.rows[99].id, 'adding a row focuses the new input');
  const removed = p.data.rows[8].id; p.removeRow(event(removed));
  assert.equal(p.data.rows.some(row => row.id === removed), false);
  assert.notEqual(p.data.rows[7].id, p.data.rows[8].id);
  const shareQuery = p.onShareAppMessage().path.split('?')[1];
  assert.equal(page(Object.fromEntries(new URLSearchParams(shareQuery))).invite, invite);
  assert.equal(page({scene: encodeURIComponent(invite)}).invite, invite);
  const replacement = 'replacement_invitation_for_contract_456';
  wx.getEnterOptionsSync = () => ({path: 'pages/index/index', query: {invite: replacement}});
  p.onShow(); assert.equal(p.invite, replacement); assert.equal(p.data.rows[0].value, '');
  delete wx.getEnterOptionsSync;
  const bad = page({invite: 'invalid'});
  bad.changeNumber(event(bad.data.rows[0].id, '13800000102'));
  const before = calls.length; await bad.submit();
  assert.equal(calls.length, before, 'invalid explicit invitation must not fall back');
  assert.match(bad.data.error, /失效/);
  const direct = page({});
  assert.equal(direct.data.error, '', 'direct open must show the original clean form');
  direct.changeNumber(event(direct.data.rows[0].id, '13800000103'));
  const directSend = direct.submit(); await tick();
  const entryRequest = requests.shift();
  assert(entryRequest.url.endsWith('/number-submit/mini/entry'));
  entryRequest.success({statusCode: 200, data: {ok: true, invite}}); await tick();
  const directRequest = requests.shift();
  assert.equal(directRequest.header.Authorization, 'Bearer ' + invite);
  directRequest.success({statusCode: 200, data: {ok: true, received: 1, added: 0, duplicates: 1, batch: 'duplicate_batch'}});
  await directSend;
  assert.equal(navigation.at(-1), '/pages/pending/pending?result=duplicate');
  await direct.viewPending(); await tick();
  assert.equal(navigation.at(-1), '/pages/pending/pending');
  const markup = fs.readFileSync(path.join(root, 'pages/index/index.wxml'), 'utf8');
  assert(markup.includes('查看未加号码'));
  assert(!/entry-input|saveEntry|入口码|设置收集入口|checkbox|consent-row|platform-link/.test(markup));
  // Exercise the actual pending controller: latest batch, refresh, failures and back.
  require(path.join(root, 'pages/pending/pending.js'));
  const pending = {...definition, data: JSON.parse(JSON.stringify(definition.data)), setData(v) { Object.assign(this.data, v); }};
  pending.onLoad({result: 'duplicate'});
  const loading = pending.onShow(); await tick();
  const list = requests.shift();
  assert(list.url.includes('/number-submit/mini/pending?batch=duplicate_batch'));
  assert.equal(list.header.Authorization, 'Bearer ' + invite);
  const items = [{number: '13800000103', submitted_display: '10-27 15:00', is_new: false}];
  list.success({statusCode: 200, data: {ok: true, items}}); await loading;
  assert.deepEqual(pending.data.items, items);
  const failed = pending.refresh();
  assert.equal(pending.data.result, '', 'manual refresh clears the submit banner like the web link');
  await tick(); requests.shift().fail(); await failed;
  assert.deepEqual(pending.data.items, items, 'refresh failure retains visible list');
  assert.match(pending.data.error, /网络/);
  global.getCurrentPages = () => [Object.assign(direct, {route: 'pages/index/index'}), pending];
  direct.changeNumber(event(direct.data.rows[0].id, '13800000999'));
  pending.continueCollecting(); assert.equal(navigation.at(-1), 'back');
  assert.equal(direct.data.rows.length, 1); assert.equal(direct.data.rows[0].value, '');
  delete global.getCurrentPages;
  const {submitNumbers} = require(path.join(root, 'utils/api'));
  const malformed = submitNumbers(invite, ['13800000101']); await tick();
  requests.shift().success({statusCode: 200, data: {ok: true, received: 1, added: 3, duplicates: 0}});
  await assert.rejects(malformed);
  const {resolveEntry} = require(path.join(root, 'utils/api'));
  for (const [reason, expected] of [
    [{errMsg: 'request:fail url not in domain list', errno: 600002}, /request 合法域名.*600002/],
    [{errMsg: 'request:fail ssl hand shake error'}, /HTTPS 证书/],
    [{errMsg: 'request:fail timeout'}, /超时/],
    [{errMsg: 'request:fail net::ERR_CONNECTION_RESET'}, /ERR_CONNECTION_RESET/],
    [{errMsg: 'request:fail net::ERR_INTERNET_DISCONNECTED'}, /网络不可用/]
  ]) {
    const failure = resolveEntry(); await tick(); requests.shift().fail(reason);
    await assert.rejects(failure, expected);
  }
  console.log('native mini program passed: direct entry, invitation isolation, submission, dedupe, double tap, failures, shared entry, pending list, batch, refresh and back');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
