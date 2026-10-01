(() => {
  'use strict';
  const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (!standalone) return;
  document.documentElement.classList.add('chen-pwa');
  const scope = document.body.dataset.pwaScope;
  if (!scope) return;
  const prefix = `chen:pwa:${scope}:`;
  const ttl = 2 * 60 * 60 * 1000;
  const read = key => {try {const v=JSON.parse(sessionStorage.getItem(key));return v && Date.now()-v.at<ttl ? v : null;}catch{return null;}};
  const write = (key,value) => {try {sessionStorage.setItem(key,JSON.stringify({...value,at:Date.now()}));return true;}catch{return false;}};
  const remove = key => {try {sessionStorage.removeItem(key);}catch{}};
  // Session-only state is isolated by authenticated session; never cache pages.
  try {for(const key of Object.keys(sessionStorage))if(key.startsWith('chen:pwa:') && (!key.startsWith(prefix)||!read(key)))remove(key);}catch{}
  const path=location.pathname+location.search;
  const positionKey=prefix+'position:'+path;
  const navigation=performance.getEntriesByType('navigation')[0]?.type;
  let historyState;
  try {historyState=JSON.parse(sessionStorage.getItem('chen-assistant:history-nav:v1432')||'null');}catch{}
  const returning=['back_forward','reload'].includes(navigation)||historyState?.pending?.target?.split('#')[0]===path;
  const saved=read(positionKey);
  const viewFields=[...new Set(document.querySelectorAll('form[method="get"] input:not([type="hidden"]),#serviceFilter,#businessFilter'))].filter(f=>!['password','file','checkbox','radio','submit'].includes(f.type));
  if(returning && saved) {
    viewFields.forEach((field,i)=>{const value=saved.filters?.[i];if(value?.name===field.name && field.value!==value.value){field.value=value.value;field.dispatchEvent(new Event('input',{bubbles:true}));}});
    requestAnimationFrame(()=>requestAnimationFrame(()=>window.scrollTo({top:saved.y,behavior:'instant'})));
  }
  window.addEventListener('pagehide',()=>write(positionKey,{y:window.scrollY,filters:viewFields.map(f=>({name:f.name,value:f.value}))}));
  for(const link of document.querySelectorAll('.bottom-nav a')) {
    const target=new URL(link.href,location.href);
    if(target.pathname===location.pathname){link.setAttribute('aria-current','page');link.classList.add('pwa-active');}
  }
  // Existing history buttons and route links remain authoritative.
  const protectedFields = new Set(['csrf','revision','list_revision','password','token','secret']);
  const eligible = form => [...form.elements].filter(field=>field.name && !protectedFields.has(field.name) &&
    !/password|secret|token/i.test(field.name) && !field.disabled && !field.readOnly &&
    ['INPUT','TEXTAREA','SELECT'].includes(field.tagName) && !['hidden','password','file','submit','button','reset'].includes(field.type));
  const serialize = form => eligible(form).map(field=>({name:field.name,type:field.type,value:field.value,
    checked:['checkbox','radio'].includes(field.type)?field.checked:undefined}));
  const dirtyForms = new Set();
  for(const form of document.querySelectorAll('form[data-pwa-draft]')) {
    const key=prefix+'draft:'+path+':'+form.dataset.pwaDraft;
    const fields=eligible(form);
    const baseline=JSON.stringify(serialize(form));
    let discarded=false;
    const bar=document.createElement('div');bar.className='pwa-draft-bar';
    const label=document.createElement('span');label.setAttribute('role','status');label.textContent='草稿仅保留在本次应用会话';
    const restore=document.createElement('button');restore.type='button';restore.textContent='恢复草稿';restore.hidden=!read(key);
    const clear=document.createElement('button');clear.type='button';clear.textContent='删除草稿';clear.hidden=!read(key);
    bar.append(label,restore,clear);form.prepend(bar);
    const persist=()=>{
      if(discarded)return;
      const values=serialize(form);
      if(JSON.stringify(values)===baseline){dirtyForms.delete(form);return;}
      dirtyForms.add(form);
      const ok=write(key,{values});
      label.textContent=ok?'草稿已暂存':'无法暂存草稿，请及时保存';clear.hidden=!ok;
    };
    const changed=()=>{discarded=false;persist();};
    form.addEventListener('input',changed);form.addEventListener('change',changed);
    restore.addEventListener('click',()=>{
      const draft=read(key);if(!draft)return;
      // Never silently overwrite a server-rendered value; restore is explicit.
      for(let i=0;i<fields.length;i++) {
        const value=draft.values?.[i],field=fields[i];
        if(!value||value.name!==field.name||value.type!==field.type)continue;
        if(['checkbox','radio'].includes(field.type)) {if(value.value!==field.value)continue;field.checked=!!value.checked;}
        else field.value=value.value;
        field.dispatchEvent(new Event('input',{bubbles:true}));
        field.dispatchEvent(new Event('change',{bubbles:true}));
      }
      restore.hidden=true;label.textContent='草稿已恢复，请检查后保存';
    });
    clear.addEventListener('click',()=>{discarded=true;remove(key);restore.hidden=true;clear.hidden=true;label.textContent='草稿已删除，当前输入保留';});
    form.addEventListener('submit',event=>{
      // A draft is cleared only after a successful redirect to its detail page.
      queueMicrotask(()=>{if(!event.defaultPrevented)write(prefix+'submitted',{key,success:form.dataset.pwaSuccess});});
    });
    window.addEventListener('pagehide',persist);
  }
  const submitted=read(prefix+'submitted');
  if(submitted?.success) {
    const patterns={customer:/^\/customers\/\d+$/,info:/^\/info\/\d+$/,list:/^\/work\/lists\/\d+$/};
    if(patterns[submitted.success]?.test(location.pathname)){remove(submitted.key);remove(prefix+'submitted');}
  }
  // Track other edits too so an update cannot discard an unprotected form.
  document.addEventListener('input',event=>{const form=event.target.closest?.('form');if(form && form.method.toLowerCase()==='post')dirtyForms.add(form);});
  for(const input of document.querySelectorAll('input[name="number"], input[name="phone"], input[name="mobile"], input[type="tel"]')) {
    if(!input.hasAttribute('inputmode'))input.setAttribute('inputmode','tel');
  }
  const viewport=window.visualViewport;
  const keyboard=()=>document.documentElement.classList.toggle('pwa-keyboard',!!viewport && window.innerHeight-viewport.height>150 && !!document.activeElement?.matches('input,textarea,select'));
  viewport?.addEventListener('resize',keyboard);
  document.addEventListener('focusin',keyboard);document.addEventListener('focusout',()=>setTimeout(keyboard,0));
  // Explicit activation: background updates never reload a user's form.
  if('serviceWorker' in navigator) {
    const showUpdate=reg=>{
      if(!reg.waiting || document.getElementById('pwa-update'))return;
      const box=document.createElement('div');box.id='pwa-update';box.className='pwa-update';box.setAttribute('role','status');
      const message=document.createElement('span');message.textContent='新版本已就绪';
      const button=document.createElement('button');button.type='button';button.textContent='更新';
      const later=document.createElement('button');later.type='button';later.textContent='稍后';
      later.addEventListener('click',()=>box.remove());
      button.addEventListener('click',()=>{
        if(dirtyForms.size){message.textContent='请先保存并离开编辑页，再更新';return;}
        if(!reg.waiting){location.reload();return;}
        navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});
        reg.waiting.postMessage({type:'SKIP_WAITING'});
      });
      box.append(message,button,later);document.body.append(box);
    };
    navigator.serviceWorker.register('/sw.js',{scope:'/'}).then(reg=>{
      showUpdate(reg);
      reg.addEventListener('updatefound',()=>reg.installing?.addEventListener('statechange',()=>showUpdate(reg)));
      document.addEventListener('visibilitychange',()=>{if(!document.hidden){showUpdate(reg);reg.update().catch(()=>{});}});
    }).catch(()=>{});
  }
})();
