'use strict';
Page({
  data: {result: null},
  onLoad() { this.setData({result: getApp().globalData.lastResult}); },
  continueCollecting() { wx.navigateBack({delta: 1}); }
});
