'use strict';
Page({
  openPlatformPrivacy() {
    if (typeof wx.openPrivacyContract !== 'function') return;
    wx.openPrivacyContract({fail: () => wx.showToast({title: '暂时无法打开', icon: 'none'})});
  }
});
