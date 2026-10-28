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
  function selectTab(tab) {
    if (!center) return;
    for (const name of ['inbox','settings']) {
      center.querySelector('[data-reminder-panel="'+name+'"]').hidden = tab !== name;
      const button = center.querySelector('[data-reminder-tab="'+name+'"]');
      button.classList.toggle('active', tab === name);
      button.setAttribute('aria-pressed', String(tab === name));
    }
  }
  async function clearStaleNotifications() {
    if (!reg || !state || typeof reg.getNotifications !== 'function') return;
    try {
      const active = new Set((state.active_notification_ids || []).map(id => String(id)));
      const notifications = await reg.getNotifications();
      for (const notification of notifications) {
        const match = /^chen-reminder-(\d+)$/.exec(notification.tag || '');
        if (match && !active.has(match[1])) notification.close();
      }
    } catch (_) { /* Platforms may not expose delivered notification management. */ }
  }
  function render() {
    updateBadge(state.unread_count);
    if(!center)return;
    $('reminder-count').textContent=`${state.unread_count} 条未读`;
    const prefs=$('reminder-preferences'); prefs.replaceChildren();
    for(const [kind,label] of Object.entries({all:'手机通知',instant:'即时提醒',...state.types})) {
      const wrap=el('label'), input=el('input'); input.type='checkbox'; input.className='reminder-switch'; input.setAttribute('role','switch'); input.checked=!!state.preferences[kind];
      input.addEventListener('change',()=>action(()=>request('/api/reminders/preferences',{[kind]:input.checked})));
      wrap.append(el('span',label),input); prefs.append(wrap);
    }
    const schedule=$('reminder-schedule-list');schedule.replaceChildren();
    const times=state.schedule_slots||[];
    if(!times.length)schedule.append(el('p','暂无时间','reminder-empty'));
    for(const time of times){
      const row=el('div',undefined,'reminder-schedule-row');
      row.append(el('strong',time));
      const remove=el('button','×','reminder-remove');remove.type='button';remove.setAttribute('aria-label','删除 '+time);
      remove.addEventListener('click',()=>action(()=>request('/api/reminders/schedule',{slots:times.filter(t=>t!==time)})));
      row.append(remove);schedule.append(row);
    }
    const devices=$('reminder-devices'); devices.replaceChildren();
    if(!state.devices.length)devices.append(el('p','暂无设备'));
    for(const d of state.devices) {
      const row=el('div',undefined,'reminder-row'), copy=el('div',undefined,'reminder-copy');
      copy.append(el('strong',d.name+(d.id===deviceId?'（本机）':'')),el('small',d.enabled?'已开启':'已关闭'));
      if(d.error)copy.append(el('small',d.error,'reminder-error'));
      const actions=el('div',undefined,'reminder-device-actions');
      for(const [label,body] of [[d.enabled?'关闭':'开启',{enabled:!d.enabled}],['移除',{delete:true}]]) {
        const button=el('button',body.delete?'×':undefined,body.delete?'reminder-remove':'reminder-switch'); button.type='button';button.setAttribute('aria-label',d.name+(body.delete?'：移除':'：通知'));if(!body.delete){button.setAttribute('role','switch');button.setAttribute('aria-checked',String(!!d.enabled));}
        button.addEventListener('click',()=>action(async()=>{
          await request(`/api/reminders/devices/${encodeURIComponent(d.id)}`,body);
          if(body.delete && d.id===deviceId) { const sub=await reg?.pushManager.getSubscription(); if(sub)await sub.unsubscribe(); deviceId=null; }
        })); actions.append(button);
      }
      row.append(copy,actions);devices.append(row);
    }
    const items=$('reminder-items');items.replaceChildren();
    const activeItems=state.items.filter(item=>!item.resolved_at && !item.read_at);
    if(!activeItems.length)items.append(el('p','目前没有待处理提醒。','reminder-empty'));
    for(const item of activeItems) {
      const row=el('div',undefined,'reminder-row'+(item.read_at||item.resolved_at?' read':'')),copy=el('div',undefined,'reminder-copy');
      const link=el('a',item.title);link.href=item.url;
      link.addEventListener('click',async e=>{e.preventDefault();try{await request(`/api/reminders/${item.id}/read`,{});}catch{} location.assign(item.url);});
      copy.append(link,el('div',item.body),el('small',`${state.types[item.kind]} · ${date(item.created_at)}${item.resolved_at?' · 已处理':''}`));
      row.append(copy);
      if(item.kind !== 'number_inbox' && !item.read_at && !item.resolved_at) {const read=el('button','已读');read.type='button';read.addEventListener('click',()=>action(()=>request(`/api/reminders/${item.id}/read`,{})));row.append(read);}
      items.append(row);
    }
    status();
    const latest=(state.test_deliveries||[]).find(d=>d.device_id===deviceId && Date.now()/1000-d.created_at<300);
    let delivery='';
    if(latest) {
      if(latest.state==='sent')delivery='测试已提交推送';
      else if(latest.error)delivery=`发送失败：${latest.error}`;
      else if(latest.state==='pending')delivery=latest.next_at>Date.now()/1000?'测试已安排 · 20秒':'等待发送';
      else if(latest.state==='skipped')delivery='测试已跳过';
      else delivery='订阅失效，请重新开启';
    }
    if(state.worker_healthy===false)delivery='推送服务异常';
    $('push-delivery').textContent=delivery;
  }
  function status() {
    const enabled=!!state?.devices.find(d=>d.id===deviceId)?.enabled;
    let message=enabled?'已开启':'未开启';
    if(ios&&!standalone)message='请从主屏幕打开';
    else if(!supported)message='当前浏览器不支持通知';
    else if(Notification.permission==='denied')message='请在系统设置中允许通知';
    $('push-status').textContent=message;
    $('push-enable').setAttribute('aria-checked',String(enabled));
    $('push-enable').disabled=busy||!state||(!enabled&&(!supported||(ios&&!standalone)||Notification.permission==='denied'));
    $('push-test').disabled=busy||!enabled||!state.preferences.all||!state.preferences.system;
    $('push-test-lock').disabled=$('push-test').disabled;
    for(const control of center.querySelectorAll('#reminder-preferences input, #reminder-devices button, #reminder-schedule-list button, #reminder-schedule-add'))control.disabled=busy;
  }
  async function refresh() {state=await request('/api/reminders');render();await clearStaleNotifications();}
  async function action(fn) {if(busy)return;busy=true;feedback('');$('reminder-schedule-feedback').textContent='';status();try{await fn();await refresh();}catch(e){feedback(e.message);await refresh().catch(()=>{});}finally{busy=false;status();}}
  function keyBytes(value) {const raw=atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));}
  if(center) {
    for (const tab of center.querySelectorAll('[data-reminder-tab]'))
      tab.addEventListener('click',()=>selectTab(tab.dataset.reminderTab));
    selectTab('inbox');
    $('reminder-schedule-add').addEventListener('click',()=>action(async()=>{
      const time=$('reminder-schedule-time').value;
      if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(time))throw new Error('请选择有效的提醒时间');
      const slots=state.schedule_slots||[];
      if(slots.includes(time))throw new Error('这个时间点已经存在');
      if(slots.length>=12)throw new Error('最多设置12个时间点');
      await request('/api/reminders/schedule',{slots:slots.concat(time)});
      $('reminder-schedule-feedback').textContent='已添加';
    }));
    $('push-enable').addEventListener('click',()=>{
      if(state?.devices.find(d=>d.id===deviceId)?.enabled){
        action(async()=>{await request(`/api/reminders/devices/${encodeURIComponent(deviceId)}`,{delete:true});const sub=await reg?.pushManager.getSubscription();if(sub)await sub.unsubscribe();deviceId=null;});
        return;
      }
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
        deviceId=result.device_id;
      });
    });
    $('push-test').addEventListener('click',()=>action(async()=>{await request('/api/reminders/test',{device_id:deviceId});}));
    $('push-test-lock').addEventListener('click',()=>action(async()=>{await request('/api/reminders/test',{device_id:deviceId,delay:20});}));
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
        render();await clearStaleNotifications();
      }
    }catch(e){feedback(e.message);}
  })();
  if(center) {
    setInterval(()=>{if(!busy&&!document.hidden)refresh().catch(()=>{});},5000);
    document.addEventListener('visibilitychange',()=>{if(!busy&&!document.hidden)refresh().catch(()=>{});});
  }
})();
