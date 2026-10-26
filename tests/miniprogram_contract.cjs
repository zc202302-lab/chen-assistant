/* Exercise actual page controllers and wx.request with a minimal native API fake. */
const assert = require('node:assert/strict');
const path = require('node:path');
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
let calls = [], navigation = [], saved = {}, requests = [], privacyMode = 'allow', privacyContracts = 0;
const app = {globalData: {lastResult: null}};
global.getApp = () => app;
global.wx = {
  getStorageSync: key => saved[key], setStorageSync: (key, value) => { saved[key] = value; },
  removeStorageSync: key => { delete saved[key]; },
  navigateTo: value => navigation.push(value.url),
  requirePrivacyAuthorize: options => privacyMode === 'allow' ? options.success() : options.fail(),
  openPrivacyContract: options => { privacyContracts += 1; options?.success?.(); },
  request: request => { calls.push(request); requests.push(request); }
};
let definition;
global.Page = value => { definition = value; };
require(path.join(root, 'pages/index/index.js'));
function page() {
  const instance = {...definition, data: JSON.parse(JSON.stringify(definition.data)),
    setData(update) { Object.assign(this.data, update); }};
  instance.onLoad({invite});
  return instance;
}
const event = (id, value) => ({currentTarget: {dataset: {id}}, detail: {value}});
async function main() {
  const p = page();
  p.changeNumber(event(p.data.rows[0].id, '13800000101'));
  await p.submit();
  assert.equal(calls.length, 0, 'consent is required before any network write');
  p.consentChanged({detail: {value: ['agree']}});
  const sending = p.submit();
  await p.submit();
  assert.equal(calls.length, 1, 'double tap must not double submit');
  const request = requests.shift();
  assert.equal(request.url, 'https://jituan.zbassistant.site/number-submit/mini/submit');
  assert.equal(request.header.Authorization, 'Bearer ' + invite);
  assert.deepEqual(request.data, {numbers: ['13800000101'], consent: true});
  request.fail();
  await sending;
  assert.equal(p.data.rows[0].value, '13800000101', 'network failure retains input');
  assert.equal(p.data.submitting, false);
  const retry = p.submit();
  requests.shift().success({statusCode: 200, data: {ok: true, received: 1, added: 1, duplicates: 0}});
  await retry;
  assert.equal(app.globalData.lastResult.added, 1);
  assert.equal(p.data.rows[0].value, '');
  assert.equal(navigation.at(-1), '/pages/result/result');
  for (let i = 0; i < 120; i++) p.addRow();
  assert.equal(p.data.rows.length, 100);
  const removed = p.data.rows[8].id;
  p.removeRow(event(removed));
  assert.equal(p.data.rows.some(row => row.id === removed), false);
  assert.notEqual(p.data.rows[7].id, p.data.rows[8].id);
  assert(p.onShareAppMessage().path.includes('?invite='));
  p.clearEntry();
  assert.equal(saved['collection-invite'], undefined);
  assert.equal(p.onShareAppMessage().path, '/pages/index/index');
  p.openPlatformPrivacy();
  assert.equal(privacyContracts, 1);
  const denied = page();
  denied.changeNumber(event(denied.data.rows[0].id, '13800000102'));
  denied.consentChanged({detail: {value: ['agree']}});
  privacyMode = 'deny';
  const callsBeforeDenial = calls.length;
  await denied.submit();
  assert.equal(calls.length, callsBeforeDenial, 'privacy cancellation must not submit');
  assert.equal(denied.data.rows[0].value, '13800000102', 'privacy cancellation retains input');
  assert.match(denied.data.error, /取消隐私授权/);
  privacyMode = 'allow';
  const {submitNumbers} = require(path.join(root, 'utils/api'));
  const malformed = submitNumbers(invite, ['13800000101']);
  requests.shift().success({statusCode: 200, data: {ok: true, received: 1, added: 3, duplicates: 0}});
  await assert.rejects(malformed);
  console.log('native mini program passed: entry parsing, platform privacy, consent, payload, cancellation retention, double tap, failure retention, results, row identity and cleared sharing');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
