'use strict';
const BASE_URL = 'https://jituan.zbassistant.site';
function networkError(reason, retainsInput) {
  const message = reason && typeof reason.errMsg === 'string' ? reason.errMsg : '';
  let text = '网络连接失败，请稍后重试';
  if (/not in domain list|domain.*not.*(?:allowed|valid)|合法域名/i.test(message))
    text = '微信未允许连接收集服务器，请管理员配置 request 合法域名：jituan.zbassistant.site';
  else if (/ssl|certificate|cert_|tls/i.test(message))
    text = '微信与收集服务器的 HTTPS 证书连接失败，请联系管理员检查';
  else if (/timeout|timed out/i.test(message))
    text = '连接收集服务器超时，请稍后重试';
  else if (/network.*(?:unavailable|offline)|internet.*disconnected|not connected/i.test(message))
    text = '当前网络不可用，请检查手机网络后重试';
  const nativeCode = message.match(/\bERR_[A-Z0-9_]{1,60}\b/);
  if (nativeCode) text += '（' + nativeCode[0] + '）';
  // Keep bounded diagnostic codes, never headers, credentials or response bodies.
  const code = reason && (reason.errno || reason.errCode);
  if (typeof code === 'number' && Number.isFinite(code)) text += '（微信错误码 ' + code + '）';
  if (retainsInput) text += '；已填写的号码会保留';
  return new Error(text);
}
function submitNumbers(invite, numbers) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE_URL + '/number-submit/mini/submit',
      method: 'POST', timeout: 15000,
      header: {'content-type': 'application/json', Authorization: 'Bearer ' + invite},
      data: {numbers, consent: true},
      success(response) {
        const data = response.data || {};
        if (response.statusCode === 200 && data.ok === true &&
            ['received', 'added', 'duplicates'].every(key => Number.isInteger(data[key]) && data[key] >= 0) &&
            data.received === data.added + data.duplicates && data.received === numbers.length) {
          resolve(data);
        } else {
          const message = typeof data.detail === 'string' ? data.detail : '提交未完成，请稍后重试';
          reject(new Error(message));
        }
      },
      fail(reason) { reject(networkError(reason, true)); }
    });
  });
}
module.exports = {submitNumbers};

function getJSON(path, invite) {
  return new Promise((resolve, reject) => wx.request({
    url: BASE_URL + path, method: 'GET', timeout: 15000,
    header: invite ? {Authorization: 'Bearer ' + invite} : {},
    success(response) {
      const data = response.data || {};
      if (response.statusCode === 200 && data.ok === true) resolve(data);
      else reject(new Error(typeof data.detail === 'string' ? data.detail : '加载失败，请稍后重试'));
    },
    fail(reason) { reject(networkError(reason, false)); }
  }));
}
function resolveEntry() {
  return getJSON('/number-submit/mini/entry').then(data => {
    const {parseInvite} = require('./entry');
    const invite = parseInvite(data.invite);
    if (!invite) throw new Error('暂时无法连接，请稍后重试');
    return invite;
  });
}
function pendingNumbers(invite, batch) {
  return getJSON('/number-submit/mini/pending?batch=' + encodeURIComponent(batch || ''), invite).then(data => {
    if (!Array.isArray(data.items) || !data.items.every(item =>
      typeof item.number === 'string' && typeof item.submitted_display === 'string' && typeof item.is_new === 'boolean'))
      throw new Error('列表加载失败，请重试');
    return data.items;
  });
}
module.exports.resolveEntry = resolveEntry;
module.exports.pendingNumbers = pendingNumbers;
