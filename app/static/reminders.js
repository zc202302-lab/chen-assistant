(() => {
  'use strict';
  const center = document.getElementById('reminder-center');
  const badge = document.querySelector('[data-reminder-badge]');
  if (!center && document.querySelector('[data-reminder-available="false"]')) return;
  let state, reg, deviceId, busy = false;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const phoneSurface = standalone && (ios || /Android/.test(navigator.userAgent));
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
  function phoneRemindersEnabled() { return state.preferences.all && state.preferences.mobile !== false; }
  function updateBadge(count) {
    if (badge) { badge.textContent=count ? String(count) : ''; badge.hidden=!count; }
    if (!phoneSurface || !('setAppBadge' in navigator)) return;
    const phoneCount = phoneRemindersEnabled() ? count : 0;
    (phoneCount ? navigator.setAppBadge(phoneCount) : navigator.clearAppBadge()).catch(()=>{});
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
    if (!phoneSurface || !state) return;
    try {
      const registration = reg || await navigator.serviceWorker?.getRegistration?.('/');
      if (typeof registration?.getNotifications !== 'function') return;
      const active = new Set((state.active_notification_ids || []).map(id => String(id)));
      const notifications = await registration.getNotifications();
      const paused = !phoneRemindersEnabled();
      for (const notification of notifications) {
        const match = /^chen-reminder(?:-(\d+))?$/.exec(notification.tag || '');
        if (match && (paused || (match[1] && !active.has(match[1])))) notification.close();
      }
    } catch (_) { /* Platforms may not expose delivered notification management. */ }
  }
  function render() {
    updateBadge(state.unread_count);
    if(!center)return;
    $('reminder-count').textContent=`${state.unread_count} 条未读`;
    const setting=(kind,label)=>{
      const wrap=el('label'), input=el('input'); input.type='checkbox'; input.className='reminder-switch'; input.setAttribute('role','switch'); input.setAttribute('aria-label',label); input.checked=!!state.preferences[kind]; input.dataset.preference=kind;
      input.addEventListener('change',()=>action(()=>request('/api/reminders/preferences',{[kind]:input.checked})));
      wrap.append(el('span',label),input); return wrap;
    };
    $('reminder-master').checked=!!state.preferences.all;
    $('reminder-mobile').checked=state.preferences.mobile!==false;
    $('reminder-desktop').checked=state.preferences.desktop!==false;
    $('reminder-desktop-status').textContent=!state.preferences.all?'已暂停 · 通知总开关已关闭':state.preferences.desktop!==false?'电脑提醒已开启':'电脑提醒已关闭';
    $('reminder-mobile-status').textContent=!state.preferences.all?'已暂停 · 总开关已关闭':state.preferences.mobile!==false?'发送到手机桌面图标中的晨的助手。':'手机已暂停，规则保留；不影响 Windows 助手。';
    $('reminder-master-status').textContent=state.preferences.all?'统一控制手机和 Windows 助手。':'已暂停手机和 Windows 助手的所有提醒。';
    $('reminder-modes').replaceChildren(setting('instant','即时提醒'),setting('scheduled','定时提醒'));
    const scopes=$('reminder-task-scopes');
    scopes.replaceChildren(setting('task_global','全局待办'),setting('task_customer','客户待办'));
    const taskGroup=el('div',undefined,'reminder-task-group');taskGroup.append(setting('task','待办'),scopes);
    $('reminder-preferences').replaceChildren(setting('number_inbox','未加号码'),taskGroup);
    $('reminder-other-preferences').replaceChildren(...Object.entries(state.types).filter(([key])=>!['number_inbox','task'].includes(key)).map(([key,label])=>setting(key,label)));
    $('reminder-timing-card').hidden=!state.preferences.scheduled;
    $('reminder-mode-status').textContent=state.preferences.scheduled&&!(state.schedule_slots||[]).length?'定时提醒尚未添加时间':'';
    const days=state.schedule_weekdays||[0,1,2,3,4,5,6];
    {
      $('reminder-repeat-kind').value=days.length===7?'daily':'weekly';
      $('reminder-weekdays').hidden=days.length===7;
      for(const input of $('reminder-weekdays').querySelectorAll('input'))input.checked=days.includes(Number(input.value));
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
    $('reminder-device-count').textContent=`${state.devices.filter(d=>d.name!=='桌面浏览器').length} 条连接`;
    if(!state.devices.some(d=>d.name!=='桌面浏览器'))devices.append(el('p','尚未连接手机'));
    for(const d of state.devices.filter(d=>d.name!=='桌面浏览器')) {
      const row=el('div',undefined,'reminder-row'), copy=el('div',undefined,'reminder-copy');
      copy.append(el('strong',d.name+(d.id===deviceId?'（这部手机）':'')),el('small',d.enabled?'已开启':'已关闭'));
      copy.append(el('small',`连接于 ${date(d.created_at)} · 最近提交推送：${date(d.last_sent)}`));
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
    let message;
    if(!phoneSurface) message=state?.devices.some(d=>d.enabled&&d.name!=='桌面浏览器')?'手机通知已有连接；网站仅管理提醒设置。':'首次使用时，请在手机桌面的晨的助手中连接通知。';
    else {
      message=enabled?'这部手机已连接通知':'这部手机尚未连接通知';
      if(!supported)message='这部手机暂不支持通知';
      else if(Notification.permission==='denied')message='请在手机系统设置中允许晨的助手通知';
    }
    $('push-status').textContent=message;
    $('push-enable').hidden=!phoneSurface||enabled;
    $('push-enable').disabled=busy||!state||!phoneSurface||!supported||Notification.permission==='denied';
    $('push-test').disabled=busy||!phoneSurface||!enabled||!state.preferences.all||state.preferences.mobile===false;
    $('push-test-lock').disabled=$('push-test').disabled;
    for(const control of center.querySelectorAll('[data-preference], #reminder-master, #reminder-mobile, #reminder-desktop, #reminder-repeat-kind, #reminder-weekdays input, #reminder-devices button, #reminder-schedule-list button, #reminder-schedule-add'))control.disabled=busy;
    for(const control of center.querySelectorAll('#reminder-task-scopes input'))control.disabled=busy||!state?.preferences.task;
  }
  async function refresh() {state=await request('/api/reminders');render();await clearStaleNotifications();}
  async function action(fn) {if(busy)return;busy=true;feedback('');$('reminder-schedule-feedback').textContent='';status();try{await fn();await refresh();}catch(e){feedback(e.message);await refresh().catch(()=>{});}finally{busy=false;status();}}
  function keyBytes(value) {const raw=atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));}
  if(center) {
    for (const tab of center.querySelectorAll('[data-reminder-tab]'))
      tab.addEventListener('click',()=>{selectTab(tab.dataset.reminderTab);history.replaceState(null,'',tab.dataset.reminderTab==='settings'?'#settings':location.pathname);});
    selectTab(location.hash==='#settings'?'settings':'inbox');
    $('reminder-desktop').addEventListener('change',()=>action(()=>request('/api/reminders/preferences',{desktop:$('reminder-desktop').checked})));
    $('reminder-mobile').addEventListener('change',()=>action(()=>request('/api/reminders/preferences',{mobile:$('reminder-mobile').checked})));
    $('reminder-master').addEventListener('change',()=>action(()=>request('/api/reminders/preferences',{all:$('reminder-master').checked})));
    $('reminder-repeat-kind').addEventListener('change',()=>action(()=>request('/api/reminders/schedule',{slots:state.schedule_slots||[],weekdays:$('reminder-repeat-kind').value==='daily'?[0,1,2,3,4,5,6]:(state.schedule_weekdays?.length<7?state.schedule_weekdays:[0,1,2,3,4])})));
    $('reminder-weekdays').addEventListener('change',()=>action(async()=>{const days=[...$('reminder-weekdays').querySelectorAll('input:checked')].map(input=>Number(input.value));if(!days.length)throw new Error('请至少选择一天');await request('/api/reminders/schedule',{slots:state.schedule_slots||[],weekdays:days});}));
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
      if(!phoneSurface)return;
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
        const result=await request('/api/reminders/subscriptions',{subscription:sub.toJSON(),name:ios?'iPhone 主屏幕':'Android 手机'});
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
      if(center&&supported&&phoneSurface) {
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
  }
  if(center || phoneSurface) {
    document.addEventListener('visibilitychange',()=>{if(!busy&&!document.hidden)refresh().catch(()=>{});});
  }
})();
