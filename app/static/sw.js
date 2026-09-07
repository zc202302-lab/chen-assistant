const CACHE='chen-assistant-v02-static';
const ASSETS=['/static/app.css','/static/app.js','/static/icon-180.png','/static/icon-512.png','/manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=='GET'||u.origin!==location.origin)return;
  if(u.pathname.startsWith('/static/')||u.pathname==='/manifest.webmanifest'){
    e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)));
  }
  // 私密动态页面（客户、账户、密码）不做离线缓存。
});
