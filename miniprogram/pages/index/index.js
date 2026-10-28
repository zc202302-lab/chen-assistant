'use strict';
const {inviteFromOptions} = require('../../utils/entry');
const {submitNumbers, resolveEntry} = require('../../utils/api');
let rowId = 0;
const emptyRow = () => ({id: ++rowId, value: ''});
const missingEntryMessage = '收集入口已失效，请重新打开小程序';
Page({
  data: {rows: [emptyRow()], focusedRow: null, submitting: false, error: ''},
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
    if (this.data.submitting) return;
    const explicit = Object.prototype.hasOwnProperty.call(options, 'invite') ||
      Object.prototype.hasOwnProperty.call(options, 'scene');
    const next = inviteFromOptions(options);
    if (!initial && explicit && next === this.invite) return;
    this.invite = next;
    this.explicitEntry = explicit;
    this.entryPromise = null;
    this.resetForm();
  },
  resetForm() { this.setData({rows: [emptyRow()], focusedRow: null, error: ''}); },
  ensureEntry() {
    if (this.invite) return Promise.resolve(this.invite);
    if (this.explicitEntry) return Promise.reject(new Error(missingEntryMessage));
    if (!this.entryPromise) {
      this.entryPromise = resolveEntry().then(invite => {
        this.invite = invite;
        return invite;
      }).catch(error => { this.entryPromise = null; throw error; });
    }
    return this.entryPromise;
  },
  viewPending() {
    if (this.data.submitting) return;
    this.ensureEntry().then(invite => {
      getApp().globalData.collectionInvite = invite;
      wx.navigateTo({url: '/pages/pending/pending'});
    }).catch(error => this.setData({error: error.message}));
  },
  numberIndex(e) {
    return this.data.rows.findIndex(row => row.id === Number(e.currentTarget.dataset.id));
  },
  focusNumber(e) {
    const index = this.numberIndex(e);
    if (index >= 0 && this.data.focusedRow !== this.data.rows[index].id)
      this.setData({focusedRow: this.data.rows[index].id});
  },
  blurNumber(e) {
    const index = this.numberIndex(e);
    if (index < 0) return;
    const patch = {};
    if (e.detail && typeof e.detail.value === 'string') patch['rows[' + index + '].value'] = e.detail.value;
    if (this.data.focusedRow === this.data.rows[index].id) patch.focusedRow = null;
    if (Object.keys(patch).length) this.setData(patch);
  },
  changeNumber(e) {
    if (this.data.submitting) return;
    const index = this.numberIndex(e);
    if (index < 0) return;
    // Keep the native input instance and its current focus/cursor intact on iOS.
    const patch = {};
    patch['rows[' + index + '].value'] = e.detail.value;
    if (this.data.error) patch.error = '';
    this.setData(patch);
  },
  addRow() {
    if (!this.data.submitting && this.data.rows.length < 100) {
      const row = emptyRow();
      this.setData({rows: this.data.rows.concat([row]), focusedRow: row.id});
    }
  },
  removeRow(e) {
    if (this.data.submitting) return;
    const rows = this.data.rows.filter(row => row.id !== Number(e.currentTarget.dataset.id));
    this.setData({rows: rows.length ? rows : [emptyRow()]});
  },
  submit() {
    if (this.data.submitting) return;
    const numbers = this.data.rows.map(row => row.value.trim()).filter(Boolean);
    if (!numbers.length) return this.setData({error: '请至少填写一个号码'});
    if (!this.data.rows[0].value.trim()) return this.setData({error: '请填写号码 1'});
    this.setData({submitting: true, error: ''});
    return this.ensureEntry().then(invite => submitNumbers(invite, numbers)).then(result => {
        getApp().globalData.lastResult = result;
        getApp().globalData.collectionInvite = this.invite;
        getApp().globalData.lastBatch = {invite: this.invite, batch: result.batch || ''};
        this.setData({rows: [emptyRow()]});
        wx.navigateTo({url: '/pages/pending/pending?result=' + (result.added > 0 ? 'success' : 'duplicate')});
      }).catch(error => {
      this.setData({error: error.message || '提交失败，请重试'});
    }).then(() => {
      this.setData({submitting: false});
    });
  },
  onShareAppMessage() {
    return {title: '请填写加集团号码',
      path: '/pages/index/index' + (this.invite ? '?invite=' + encodeURIComponent(this.invite) : '')};
  }
});
