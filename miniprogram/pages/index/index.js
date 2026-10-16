'use strict';
const {parseInvite, inviteFromOptions} = require('../../utils/entry');
const {submitNumbers} = require('../../utils/api');
let rowId = 0;
const emptyRow = () => ({id: ++rowId, value: ''});
Page({
  data: {rows: [], entryText: '', entryReady: false, entryExpanded: true,
    consent: false, submitting: false, error: ''},
  onLoad(options) {
    const shared = inviteFromOptions(options || {});
    let saved = '';
    try { saved = parseInvite(wx.getStorageSync('collection-invite')); } catch (_) {}
    this.invite = shared || saved;
    this.setData({rows: [emptyRow()], entryReady: !!this.invite, entryExpanded: !this.invite});
    if (shared) this.rememberInvite(shared);
  },
  rememberInvite(invite) {
    try { wx.setStorageSync('collection-invite', invite); } catch (_) {}
  },
  changeEntryText(e) { this.setData({entryText: e.detail.value}); },
  toggleEntry() {
    if (!this.data.submitting) this.setData({entryExpanded: !this.data.entryExpanded});
  },
  saveEntry() {
    if (this.data.submitting) return;
    const invite = parseInvite(this.data.entryText);
    if (!invite) return this.setData({error: '请填写入口提供者发给你的完整收集链接或入口码'});
    this.invite = invite;
    this.rememberInvite(invite);
    this.setData({entryReady: true, entryExpanded: false, entryText: '', error: ''});
  },
  clearEntry() {
    if (this.data.submitting) return;
    this.invite = '';
    try { wx.removeStorageSync('collection-invite'); } catch (_) {}
    this.setData({entryReady: false, entryExpanded: true, entryText: '', error: ''});
  },
  changeNumber(e) {
    if (this.data.submitting) return;
    const rows = this.data.rows.map(row => row.id === Number(e.currentTarget.dataset.id)
      ? {...row, value: e.detail.value} : row);
    this.setData({rows, error: ''});
  },
  addRow() {
    if (!this.data.submitting && this.data.rows.length < 100)
      this.setData({rows: [...this.data.rows, emptyRow()]});
  },
  removeRow(e) {
    if (this.data.submitting) return;
    const rows = this.data.rows.filter(row => row.id !== Number(e.currentTarget.dataset.id));
    this.setData({rows: rows.length ? rows : [emptyRow()]});
  },
  consentChanged(e) { this.setData({consent: e.detail.value.includes('agree')}); },
  openPrivacy() { wx.navigateTo({url: '/pages/privacy/privacy'}); },
  async submit() {
    if (this.data.submitting) return;
    if (!this.invite) return this.setData({entryExpanded: true, error: '请先设置收集入口'});
    if (!this.data.consent) return this.setData({error: '请先阅读并同意号码收集说明'});
    const numbers = this.data.rows.map(row => row.value.trim()).filter(Boolean);
    if (!numbers.length) return this.setData({error: '请至少填写一个号码'});
    this.setData({submitting: true, error: ''});
    try {
      const result = await submitNumbers(this.invite, numbers);
      getApp().globalData.lastResult = result;
      this.setData({rows: [emptyRow()]});
      wx.navigateTo({url: '/pages/result/result'});
    } catch (error) {
      this.setData({error: error.message || '提交失败，请重试'});
    } finally { this.setData({submitting: false}); }
  },
  onShareAppMessage() {
    return {title: '请填写待添加的集团成员号码',
      path: '/pages/index/index' + (this.invite ? '?invite=' + encodeURIComponent(this.invite) : '')};
  }
});
