'use strict';
const {parseInvite, inviteFromOptions} = require('../../utils/entry');
const {submitNumbers} = require('../../utils/api');
let rowId = 0;
const emptyRow = () => ({id: ++rowId, value: ''});
const missingEntryMessage = '请从收集人分享的小程序卡片或二维码进入';
Page({
  data: {rows: [emptyRow()], entryReady: false,
    consent: false, privacyChecking: false, submitting: false, error: ''},
  onLoad(options) {
    this.applyEntry(options || {}, true);
  },
  onShow() {
    // WeChat can reuse this page when another invitation brings the app forward.
    if (typeof wx.getEnterOptionsSync !== 'function') return;
    const entry = wx.getEnterOptionsSync();
    if (entry && entry.path === 'pages/index/index' && entry.query &&
        (Object.prototype.hasOwnProperty.call(entry.query, 'invite') ||
         Object.prototype.hasOwnProperty.call(entry.query, 'scene'))) {
      this.applyEntry(entry.query, false);
    }
  },
  applyEntry(options, initial) {
    if (this.data.submitting || this.data.privacyChecking) return;
    const explicit = Object.prototype.hasOwnProperty.call(options, 'invite') ||
      Object.prototype.hasOwnProperty.call(options, 'scene');
    const shared = inviteFromOptions(options);
    let saved = '';
    if (!explicit) {
      try { saved = parseInvite(wx.getStorageSync('collection-invite')); } catch (_) {}
    }
    const next = shared || saved;
    if (!initial && next === this.invite) return;
    this.invite = next;
    this.setData({rows: [emptyRow()], consent: false, entryReady: !!next,
      error: next ? '' : missingEntryMessage});
    try {
      if (next) wx.setStorageSync('collection-invite', next);
      else wx.removeStorageSync('collection-invite');
    } catch (_) {}
    if (next && typeof wx.showShareMenu === 'function') wx.showShareMenu({menus: ['shareAppMessage']});
    if (!next && typeof wx.hideShareMenu === 'function') wx.hideShareMenu();
  },
  changeNumber(e) {
    if (this.data.submitting) return;
    const rows = this.data.rows.map(row => row.id === Number(e.currentTarget.dataset.id)
      ? Object.assign({}, row, {value: e.detail.value}) : row);
    this.setData({rows, error: ''});
  },
  addRow() {
    if (!this.data.submitting && this.data.rows.length < 100)
      this.setData({rows: this.data.rows.concat([emptyRow()])});
  },
  removeRow(e) {
    if (this.data.submitting) return;
    const rows = this.data.rows.filter(row => row.id !== Number(e.currentTarget.dataset.id));
    this.setData({rows: rows.length ? rows : [emptyRow()]});
  },
  consentChanged(e) { this.setData({consent: e.detail.value.includes('agree')}); },
  openPrivacy() { wx.navigateTo({url: '/pages/privacy/privacy'}); },
  openPlatformPrivacy() {
    if (typeof wx.openPrivacyContract !== 'function') return this.setData({error: '请升级微信后查看平台隐私保护指引'});
    wx.openPrivacyContract({fail: () => this.setData({error: '暂时无法打开微信隐私保护指引'})});
  },
  requirePlatformPrivacy() {
    if (typeof wx.requirePrivacyAuthorize !== 'function') return Promise.resolve(true);
    return new Promise(resolve => wx.requirePrivacyAuthorize({success: () => resolve(true), fail: () => resolve(false)}));
  },
  submit() {
    if (this.data.submitting) return;
    if (!this.invite) return this.setData({error: missingEntryMessage});
    if (!this.data.consent) return this.setData({error: '请先阅读并同意号码收集说明'});
    const numbers = this.data.rows.map(row => row.value.trim()).filter(Boolean);
    if (!numbers.length) return this.setData({error: '请至少填写一个号码'});
    if (this.data.privacyChecking) return;
    this.setData({privacyChecking: true, error: ''});
    return this.requirePlatformPrivacy().then(privacyAllowed => {
      this.setData({privacyChecking: false});
      if (!privacyAllowed) {
        this.setData({error: '你已取消隐私授权，号码未提交；填写内容仍保留'});
        return;
      }
      if (this.data.submitting) return;
      this.setData({submitting: true, error: ''});
      return submitNumbers(this.invite, numbers).then(result => {
        getApp().globalData.lastResult = result;
        this.setData({rows: [emptyRow()]});
        wx.navigateTo({url: '/pages/result/result'});
      });
    }).catch(error => {
      this.setData({error: error.message || '提交失败，请重试'});
    }).then(() => {
      this.setData({privacyChecking: false, submitting: false});
    });
  },
  onShareAppMessage() {
    return {title: '请填写待添加的集团成员号码',
      path: '/pages/index/index' + (this.invite ? '?invite=' + encodeURIComponent(this.invite) : '')};
  }
});
