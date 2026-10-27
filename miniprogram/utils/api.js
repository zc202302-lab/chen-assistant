'use strict';
const BASE_URL = 'https://jituan.zbassistant.site';
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
      fail() { reject(new Error('网络连接失败，请稍后重试；已填写的号码会保留')); }
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
    fail() { reject(new Error('网络连接失败，请稍后重试')); }
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
