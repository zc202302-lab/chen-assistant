'use strict';
const {pendingNumbers, resolveEntry} = require('../../utils/api');
Page({
  data: {items: [], loading: true, error: '', result: ''},
  onLoad(options) { this.setData({result: options && options.result || ''}); },
  onShow() { return this.loadPending(); },
  refresh() { this.setData({result: ''}); return this.loadPending(); },
  loadPending() {
    if (this.refreshing) return;
    this.refreshing = true;
    this.setData({loading: true, error: ''});
    const state = getApp().globalData;
    return (state.collectionInvite ? Promise.resolve(state.collectionInvite) : resolveEntry())
      .then(invite => {
        state.collectionInvite = invite;
        const last = state.lastBatch || {};
        return pendingNumbers(invite, last.invite === invite ? last.batch : '');
      }).then(items => this.setData({items}))
      .catch(error => this.setData({error: error.message || '列表加载失败，请重试'}))
      .then(() => { this.refreshing = false; this.setData({loading: false}); });
  },
  continueCollecting() {
    if (typeof getCurrentPages === 'function') {
      const pages = getCurrentPages();
      const previous = pages[pages.length - 2];
      if (previous && previous.route === 'pages/index/index' && typeof previous.resetForm === 'function') previous.resetForm();
    }
    wx.navigateBack({delta: 1, fail: () => wx.redirectTo({url: '/pages/index/index'})});
  }
});
