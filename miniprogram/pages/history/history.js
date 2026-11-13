'use strict';
const {historyNumbers, resolveEntry} = require('../../utils/api');
Page({
  data: {items: [], loading: true, error: ''},
  onShow() { return this.loadHistory(); },
  refresh() { return this.loadHistory(); },
  loadHistory() {
    if (this.refreshing) return;
    this.refreshing = true;
    this.setData({loading: true, error: ''});
    const state = getApp().globalData;
    return (state.collectionInvite ? Promise.resolve(state.collectionInvite) : resolveEntry())
      .then(invite => { state.collectionInvite = invite; return historyNumbers(invite); })
      .then(items => this.setData({items: items.map((item, rowKey) => Object.assign({rowKey}, item))}))
      .catch(error => this.setData({error: error.message || '历史号码加载失败，请重试'}))
      .then(() => { this.refreshing = false; this.setData({loading: false}); });
  },
  copyNumber(event) {
    const number = event.currentTarget.dataset.number;
    if (typeof number === 'string') wx.setClipboardData({data: number});
  },
  continueCollecting() {
    wx.navigateBack({delta: 1, fail: () => wx.redirectTo({url: '/pages/index/index'})});
  }
});
