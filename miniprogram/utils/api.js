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
