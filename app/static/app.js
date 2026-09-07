const toast=(msg)=>{let el=document.createElement('div');el.textContent=msg;Object.assign(el.style,{position:'fixed',left:'50%',bottom:'92px',transform:'translateX(-50%)',background:'#111827',color:'#fff',padding:'9px 12px',borderRadius:'10px',zIndex:'999',fontSize:'13px'});document.body.appendChild(el);setTimeout(()=>el.remove(),1200)};
const copyText=async(value)=>{try{await navigator.clipboard.writeText(value)}catch{const ta=document.createElement('textarea');ta.value=value;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove()}};

document.addEventListener('click',async(e)=>{
  const b=e.target.closest('.copy-btn,.identifier-copy');
  if(b){
    const value=b.dataset.copy||''; if(!value)return;
    await copyText(value);
    if(b.classList.contains('identifier-copy')){
      const kind=b.dataset.kind||'内容'; toast(`已复制${kind}`); b.classList.add('copied'); setTimeout(()=>b.classList.remove('copied'),700);
      document.querySelectorAll('[data-payment-row].is-current').forEach(x=>x.classList.remove('is-current'));
      const row=b.closest('[data-payment-row]'); if(row){row.classList.add('is-current'); const input=row.querySelector('.quick-amount'); if(input){input.focus(); input.select();}}
    }else toast('已复制');
  }
  const disabled=e.target.closest('a[aria-disabled="true"]'); if(disabled)e.preventDefault();
});

document.addEventListener('submit',(e)=>{const f=e.target;if(f.dataset.confirm&&!confirm(f.dataset.confirm))e.preventDefault()});

const filter=document.getElementById('serviceFilter');
if(filter){filter.addEventListener('input',()=>{const q=filter.value.trim().toLowerCase();document.querySelectorAll('.service-group').forEach(group=>{let matched=0;group.querySelectorAll('.service-card').forEach(el=>{const show=!q||el.dataset.serviceText.toLowerCase().includes(q);el.style.display=show?'block':'none';if(show)matched++});if(q&&matched)group.open=true;if(q)group.style.display=matched?'block':'none';else group.style.display='block'})})}

const reveal=document.getElementById('revealPassword');if(reveal){reveal.addEventListener('click',async()=>{const fd=new FormData();fd.append('csrf',reveal.dataset.csrf);const r=await fetch(`/accounts/${reveal.dataset.accountId}/password`,{method:'POST',body:fd,credentials:'same-origin'});if(!r.ok){toast('读取失败');return}const data=await r.json();document.getElementById('passwordValue').textContent=data.password||'未保存密码';if(data.password){try{await navigator.clipboard.writeText(data.password);toast('密码已显示并复制')}catch{toast('密码已显示')}}})}

const money=(n)=>{const v=Math.round((Number(n)||0)*100)/100;return '¥'+(Number.isInteger(v)?v.toFixed(0):v.toFixed(2).replace(/0+$/,'').replace(/\.$/,''))};
const workbench=document.querySelector('[data-payment-workbench]');

function applyPaymentFilter(kind){
  document.querySelectorAll('.payment-filter').forEach(b=>b.classList.toggle('active',b.dataset.paymentFilter===kind));
  document.querySelectorAll('[data-payment-row]').forEach(row=>{
    let show=true;
    if(kind==='pending')show=row.dataset.confirmed==='0';
    if(kind==='changed')show=row.dataset.changed==='1';
    if(kind==='zero')show=row.dataset.zero==='1';
    row.classList.toggle('is-hidden',!show);
  });
}
document.querySelectorAll('.payment-filter').forEach(b=>b.addEventListener('click',()=>applyPaymentFilter(b.dataset.paymentFilter)));

async function savePayment(input, jumpNext=true){
  if(!workbench||input.dataset.saving==='1')return;
  const raw=input.value.trim(); if(raw===''){toast('金额不能为空；本月无需缴费请填0');input.focus();return;}
  const row=input.closest('[data-payment-row]');
  input.dataset.saving='1'; row?.classList.add('is-saving');
  const fd=new FormData(); fd.append('csrf',workbench.dataset.csrf); fd.append('amount',raw);
  try{
    const r=await fetch(`/services/${input.dataset.serviceId}/payment-current`,{method:'POST',body:fd,credentials:'same-origin'});
    const data=await r.json().catch(()=>({}));
    if(!r.ok||!data.ok){toast(data.error||'保存失败');return;}
    input.value=String(Math.round(Number(data.amount)*100)/100); input.dataset.lastSaved=input.value;
    if(row){
      row.dataset.confirmed='1'; row.dataset.zero=Number(data.amount)===0?'1':'0'; row.dataset.changed=data.delta===null?'0':'1';
      row.classList.remove('is-pending'); row.classList.add('is-current');
      const status=row.querySelector('.amount-label small');
      if(status){status.textContent=row.dataset.mode==='fixed'?'固定':'✓ 已核对';status.className=row.dataset.mode==='fixed'?'':'ok-text';}
      const fb=row.querySelector('.amount-feedback'); if(fb){fb.innerHTML=''; if(data.delta!==null){const span=document.createElement('span');span.className='delta-badge '+(Number(data.delta)>0?'up':'down');span.textContent=(Number(data.delta)>0?'+':'')+(Math.round(Number(data.delta)*100)/100);fb.appendChild(span);}}
    }
    const p=document.getElementById('pendingCount'); if(p)p.textContent=data.pending;
    const c=document.getElementById('changedCount'); if(c)c.textContent=data.changed;
    const z=document.getElementById('zeroCount'); if(z)z.textContent=data.zero;
    const total=document.getElementById('paymentGrandTotal'); if(total)total.textContent=money(data.total);
    const ready=document.getElementById('paymentReadiness'); if(ready)ready.textContent=data.pending?`还有 ${data.pending} 项待核对；金额已沿用上次状态，但尚不能生成正式缴费 TXT。`:'本月需要人工核对的金额已全部确认。';
    const txt=document.getElementById('paymentTxtButton'); if(txt){txt.setAttribute('aria-disabled',data.txt_ready?'false':'true');txt.classList.toggle('disabled',!data.txt_ready);txt.classList.toggle('primary',data.txt_ready);txt.classList.toggle('secondary',!data.txt_ready);}
    toast(data.delta===null?'已确认':'已保存 · 金额有变化');
    if(jumpNext){
      const rows=[...document.querySelectorAll('[data-payment-row]')]; const idx=rows.indexOf(row);
      const ordered=rows.slice(idx+1).concat(rows.slice(0,idx+1));
      const next=ordered.find(x=>x.dataset.confirmed==='0');
      if(next){next.scrollIntoView({behavior:'smooth',block:'center'});const ni=next.querySelector('.quick-amount');setTimeout(()=>{ni?.focus();ni?.select()},180);}
    }
  }catch{toast('网络异常，未保存');}
  finally{delete input.dataset.saving;row?.classList.remove('is-saving');}
}

document.querySelectorAll('.quick-amount').forEach(input=>{
  input.dataset.lastSaved=input.value;
  input.addEventListener('focus',()=>input.select());
  input.addEventListener('click',()=>input.select());
  input.addEventListener('keydown',(e)=>{if(e.key==='Enter'){e.preventDefault();savePayment(input,true)}});
  input.addEventListener('change',()=>{if(input.value!==input.dataset.lastSaved)savePayment(input,false)});
});

if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}))}
