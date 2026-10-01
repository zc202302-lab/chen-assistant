(() => {
  'use strict';
  const center = document.getElementById('reminder-center');
  const badge = document.querySelector('[data-reminder-badge]');
  if (!center && document.querySelector('[data-reminder-available="false"]')) return;
  let state, reg, deviceId, busy = false;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const supported = window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  const $ = id => document.getElementById(id);
  function feedback(text) { if (center) $('reminder-feedback').textContent = text; }
  async function request(path, body) {
    const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':center.dataset.csrf}, body:JSON.stringify(body)};
    const response = await fetch(path, {...options, credentials:'same-origin'});
    if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('登录已过期，请重新登录。');
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '操作失败，请重试。');
    return result;
  }
  function el(tag, text, cls) { const node=document.createElement(tag); if(text !== undefined)node.textContent=text; if(cls)node.className=cls; return node; }
  function date(value) { return value ? new Date(value*1000).toLocaleString('zh-CN') : '尚未发送'; }
  function updateBadge(count) {
    if (badge) { badge.textContent=count ? String(count) : ''; badge.hidden=!count; }
    if ('setAppBadge' in navigator) { (count ? navigator.setAppBadge(count) : navigator.clearAppBadge()).catch(()=>{}); }
  }
  function render() {
    updateBadge(state.unread_count);
    if(!center)return;
    $('reminder-count').textContent=`${state.unread_count} 条未读`;
    const prefs=$('reminder-preferences'); prefs.replaceChildren();
    for(const [kind,label] of Object.entries({all:'手机通知总开关',...state.types})) {
      const wrap=el('label'), input=el('input'); input.type='checkbox'; input.checked=!!state.preferences[kind];
      input.addEventListener('change',()=>action(()=>request('/api/reminders/preferences',{[kind]:input.checked})));
      wrap.append(input,el('span',label)); prefs.append(wrap);
    }
    const devices=$('reminder-devices'); devices.replaceChildren();
    if(!state.devices.length)devices.append(el('p','尚未订阅任何设备。'));
    for(const d of state.devices) {
      const row=el('div',undefined,'reminder-row'), copy=el('div',undefined,'reminder-copy');
      copy.append(el('strong',d.name+(d.id===deviceId?'（本机）':'')),el('small',`${d.enabled?'已开启':'已关闭'} · 最近发送：${date(d.last_sent)}`));
      if(d.error)copy.append(el('small',d.error,'reminder-error'));
      const actions=el('div',undefined,'reminder-device-actions');
      for(const [label,body] of [[d.enabled?'关闭':'开启',{enabled:!d.enabled}],['移除',{delete:true}]]) {
        const button=el('button',label); button.type='button';
        button.addEventListener('click',()=>action(async()=>{
          await request(`/api/reminders/devices/${encodeURIComponent(d.id)}`,body);
          if(body.delete && d.id===deviceId) { const sub=await reg?.pushManager.getSubscription(); if(sub)await sub.unsubscribe(); deviceId=null; }
        })); actions.append(button);
      }
      row.append(copy,actions);devices.append(row);
    }
    const items=$('reminder-items');items.replaceChildren();
    if(!state.items.length)items.append(el('p','暂无提醒。'));
    for(const item of state.items) {
      const row=el('div',undefined,'reminder-row'+(item.read_at||item.resolved_at?' read':'')),copy=el('div',undefined,'reminder-copy');
      const link=el('a',item.title);link.href=item.url;
      link.addEventListener('click',async e=>{e.preventDefault();try{await request(`/api/reminders/${item.id}/read`,{});}catch{} location.assign(item.url);});
      copy.append(link,el('div',item.body),el('small',`${state.types[item.kind]} · ${date(item.created_at)}${item.resolved_at?' · 已处理':''}`));
      row.append(copy);
      if(!item.read_at && !item.resolved_at) {const read=el('button','已读');read.type='button';read.addEventListener('click',()=>action(()=>request(`/api/reminders/${item.id}/read`,{})));row.append(read);}
      items.append(row);
    }
    status();
    const latest=(state.test_deliveries||[]).find(d=>d.device_id===deviceId);
    let delivery='尚未测试后台推送。';
    if(latest) {
      if(latest.state==='sent')delivery='推送服务已接受测试通知。若手机仍未显示，请检查系统通知、锁屏显示和专注模式；这不代表手机已确认收到。';
      else if(latest.error)delivery=`发送未成功：${latest.error}（已尝试 ${latest.attempts} 次）`;
      else if(latest.state==='pending')delivery=latest.next_at>Date.now()/1000?'测试已安排，请返回主屏幕并锁屏等候。':'等待后台发送。';
      else if(latest.state==='skipped')delivery='测试被跳过：提醒已读、已处理，或通知开关已关闭。';
      else delivery='订阅已失效，请重新开启手机提醒。';
    }
    if(state.worker_healthy===false)delivery+=' 后台发送程序尚未运行或运行异常。';
    $('push-delivery').textContent=delivery;
  }
  function status() {
    let message='点击开启手机提醒，允许接收通知。';
    if(ios&&!standalone)message='请先添加到主屏幕，再从主屏幕打开晨的助手。';
    else if(!supported)message='当前环境不支持推送，请使用 HTTPS 和支持通知的浏览器。';
    else if(Notification.permission==='denied')message='通知权限已关闭，请在系统设置中允许晨的助手通知。';
    else if(deviceId)message=state.devices.find(d=>d.id===deviceId)?.enabled?'本机已订阅。点击锁屏测试，然后返回主屏幕并锁屏。':'本机提醒已关闭，点击开启手机提醒可恢复。';
    $('push-status').textContent=message;
    $('push-enable').disabled=busy||!state||!supported||(ios&&!standalone)||Notification.permission==='denied';
    $('push-test').disabled=busy||!deviceId||!state.devices.find(d=>d.id===deviceId)?.enabled||!state.preferences.all||!state.preferences.system;
    $('push-test-lock').disabled=$('push-test').disabled;
    $('push-disable').disabled=busy||!deviceId;
  }
  async function refresh() {state=await request('/api/reminders');render();}
  async function action(fn) {if(busy)return;busy=true;status();try{await fn();await refresh();}catch(e){feedback(e.message);await refresh().catch(()=>{});}finally{busy=false;status();}}
  function keyBytes(value) {const raw=atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));}
  if(center) {
    $('push-enable').addEventListener('click',()=>{
      // Permission must be requested directly in this click, before any await,
      // otherwise iPhone loses the required user-activation gesture.
      const permission=Notification.requestPermission();
      action(async()=>{
        if(await permission!=='granted')throw new Error('尚未允许通知。');
        reg=reg||await navigator.serviceWorker.register('/sw.js',{scope:'/'});
        await navigator.serviceWorker.ready;
        let sub=await reg.pushManager.getSubscription();
        if(sub && sub.options.applicationServerKey && !equalKey(new Uint8Array(sub.options.applicationServerKey),keyBytes(state.public_key))) {await sub.unsubscribe();sub=null;}
        sub=sub||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(state.public_key)});
        const result=await request('/api/reminders/subscriptions',{subscription:sub.toJSON(),name:ios?'iPhone 主屏幕':(/Android/.test(navigator.userAgent)?'Android 手机':'桌面浏览器')});
        deviceId=result.device_id;feedback('手机提醒已开启。请发送测试提醒确认。');
      });
    });
    $('push-test').addEventListener('click',()=>action(async()=>{const r=await request('/api/reminders/test',{device_id:deviceId});feedback(r.message);}));
    $('push-test-lock').addEventListener('click',()=>action(async()=>{const r=await request('/api/reminders/test',{device_id:deviceId,delay:20});feedback(r.message);}));
    $('push-disable').addEventListener('click',()=>action(async()=>{await request(`/api/reminders/devices/${encodeURIComponent(deviceId)}`,{delete:true});const sub=await reg?.pushManager.getSubscription();if(sub)await sub.unsubscribe();deviceId=null;feedback('本机提醒已关闭。');}));
  }
  function equalKey(a,b){return a.length===b.length&&a.every((v,i)=>v===b[i]);}
  (async()=>{
    try {
      await refresh();
      if(center&&supported&&(!ios||standalone)) {
        reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
        await navigator.serviceWorker.ready;
        const sub=await reg.pushManager.getSubscription();
        // Reconcile without silently re-enabling a device disabled remotely.
        if(sub) {
          const data=await request('/api/reminders/subscription-state',{endpoint:sub.endpoint});deviceId=data.device_id;
        }
        render();
      }
    }catch(e){feedback(e.message);}
  })();
  if(center) {
    setInterval(()=>{if(!busy&&!document.hidden)refresh().catch(()=>{});},5000);
    document.addEventListener('visibilitychange',()=>{if(!busy&&!document.hidden)refresh().catch(()=>{});});
  }
})();
