const CACHE='chen-assistant-v170-shell';
const ASSETS=['/static/icon-180.png','/static/icon-512.png','/manifest.webmanifest','/static/offline.html','/static/reminders.css'];
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)))});
self.addEventListener('activate',e=>{e.waitUntil(Promise.all([
  caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))),
  self.clients.claim()
]))});
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=='GET'||u.origin!==location.origin)return;
  if(ASSETS.includes(u.pathname)){
    e.respondWith(fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));return r}).catch(()=>caches.match(e.request)));
  }
  else if(e.request.mode==='navigate'){
    e.respondWith(fetch(e.request).catch(()=>caches.match('/static/offline.html')));
  }
  // Private pages stay network-fresh; no customer data is cached.
});


// Always display a visible notification, including on iPhone while pages are closed.
self.addEventListener('push',event=>{
  event.waitUntil((async()=>{
    let data={};try{data=event.data?event.data.json():{};}catch{}
    let target=new URL('/reminders',self.location.origin);
    try{const candidate=new URL(data.url||'/reminders',self.location.origin);if(candidate.origin===self.location.origin)target=candidate;}catch{}
    await self.registration.showNotification(data.title||'晨的助手提醒',{
      body:data.body||'你有一条新提醒',icon:'/static/icon-180.png',
      tag:data.id?`chen-reminder-${data.id}`:'chen-reminder',
      data:{url:Number.isInteger(data.id)?new URL(`/reminders/open/${data.id}`,self.location.origin).href:target.href,id:data.id},renotify:false
    });
    if('setAppBadge' in self.navigator&&Number.isInteger(data.unread_count)){
      await (data.unread_count>0?self.navigator.setAppBadge(data.unread_count):self.navigator.clearAppBadge()).catch(()=>{});
    }
  })());
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  event.waitUntil((async()=>{
    let url=new URL('/reminders',self.location.origin);
    try{const candidate=new URL(event.notification.data?.url||'/reminders');if(candidate.origin===self.location.origin)url=candidate;}catch{}
    const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const current=windows.find(c=>c.url===url.href);
    if(current)return current.focus();
    // Open the exact feature path; do not silently focus an unrelated open page.
    return self.clients.openWindow(url.href);
  })());
});
