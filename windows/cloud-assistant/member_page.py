"""Read-only page probes and isolated control actions for the business UI."""
_SEARCH_MATCH = r"""(() => {
  const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
  const compact=e=>String(e.innerText||e.value||e.textContent||'').replace(/\s/g,'');
  const labelled=e=>(e.id==='search_btn'&&e.classList.contains('input_search_right')&&e.closest('#topSearchDiv'))||[compact(e),e.getAttribute('title'),e.getAttribute('alt'),e.getAttribute('aria-label')].some(t=>String(t||'').replace(/\s/g,'')==='搜索');
  // Legacy pages may render the caption in font/b/td or in an image.
  const all=[...document.querySelectorAll('*')].filter(visible).filter(labelled);
  const buttons=all.filter(e=>!all.some(c=>c!==e&&e.contains(c)));
  const inputs=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
  const pairs=[];
  for(const button of buttons){const br=button.getBoundingClientRect();for(const input of inputs){const r=input.getBoundingClientRect();const dy=Math.abs((r.top+r.bottom-br.top-br.bottom)/2);const gap=br.left-r.right;if(gap>=-3&&gap<=150&&dy<=18)pairs.push({input,button,score:dy+Math.max(0,gap)/10});}}
  pairs.sort((a,b)=>a.score-b.score);
  if(!pairs.length)return {ok:false,reason:'未找到同一行相邻的搜索框和搜索按钮',inputs:inputs.length,buttons:buttons.length,diagnostic:{tags:[...new Set([...document.querySelectorAll('*')].filter(visible).filter(e=>compact(e).includes('搜索')).map(e=>e.tagName))].slice(0,20),images:[...document.querySelectorAll('img,input[type=image]')].filter(visible).slice(0,15).map(e=>({tag:e.tagName,title:e.getAttribute('title'),alt:e.getAttribute('alt')}))}};
  if(pairs.length>1&&Math.abs(pairs[0].score-pairs[1].score)<1)return {ok:false,reason:'搜索控件匹配不唯一'};
  return {ok:true,input:pairs[0].input,button:pairs[0].button};
})()"""

_FIND_SEARCH_INPUT = "(() => {const match=" + _SEARCH_MATCH + ";return {ok:match.ok,reason:match.reason,inputs:match.inputs,buttons:match.buttons,diagnostic:match.diagnostic};})()"
_SET_SEARCH_AND_CLICK = "((queryValue) => {const match=" + _SEARCH_MATCH + r""";
  if(!match.ok)return {ok:false,reason:match.reason};
  const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
  setter.call(match.input,queryValue);match.input.dispatchEvent(new Event('input',{bubbles:true}));match.input.dispatchEvent(new Event('change',{bubbles:true}));match.button.click();return {ok:true};
})(%s)"""


_CLICK_LABEL = r"""((labelText) => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const compact=e=>(e.innerText||e.value||e.textContent||'').replace(/\s+/g,' ').trim();
 const all=[...document.querySelectorAll('a,button,input[type=button],input[type=submit],[role=tab],li,span,div,td')].filter(visible).filter(e=>compact(e)===labelText);
 const minimal=all.filter(e=>![...e.children].some(c=>compact(c)===labelText));
 const candidates=minimal.length?minimal:all;
 if(candidates.length!==1)return {ok:false,count:candidates.length};
 let target=candidates[0];
 for(let i=0;i<4&&target.parentElement;i++){if(target.matches('a,button,[role=tab]'))break;target=target.parentElement;if(target.matches('a,button,[role=tab]'))break;}
 target.click();return {ok:true};
})(%s)"""

_MEMBER_DUPLICATE = r"""((number) => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const rows=[...document.querySelectorAll('tr')].filter(visible);
 return rows.some(row=>[...row.querySelectorAll('td')].some(cell=>(cell.innerText||cell.textContent||'').replace(/\s/g,'')===number));
})(%s)"""

_FILL_LABEL_INPUT = r"""((labelText,value) => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)===labelText);
 const controls=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
 const pairs=[];
 for(const label of labels){const lr=label.getBoundingClientRect();for(const control of controls){const r=control.getBoundingClientRect();const dy=Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2);if(r.left>=lr.right-2&&dy<=22)pairs.push({label,control,score:dy+Math.max(0,r.left-lr.right)/100});}}
 pairs.sort((a,b)=>a.score-b.score);
 if(!pairs.length)return {ok:false,reason:`${labelText}输入框不存在`};
 const best=pairs[0].score;const winners=[...new Set(pairs.filter(x=>x.score<=best+0.25).map(x=>x.control))];
 if(winners.length!==1)return {ok:false,reason:`${labelText}输入框不唯一`};
 const input=winners[0];const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,value);
 input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));input.dispatchEvent(new Event('blur',{bubbles:true}));
 return {ok:true};
})(%s,%s)"""

_READ_NAME = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)==='姓名');
 const inputs=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
 const pairs=[];for(const label of labels){const lr=label.getBoundingClientRect();for(const input of inputs){const r=input.getBoundingClientRect();const dy=Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2);if(r.left>=lr.right-2&&dy<=22)pairs.push({input,score:dy+Math.max(0,r.left-lr.right)/100});}}
 pairs.sort((a,b)=>a.score-b.score);return pairs.length?{value:pairs[0].input.value||''}:{value:''};
})()"""

_HAS_SERVICE_INPUT = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)==='服务号码');
 const inputs=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
 return labels.some(label=>{const lr=label.getBoundingClientRect();return inputs.some(input=>{const r=input.getBoundingClientRect();return r.left>=lr.right-2&&Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2)<=22;});});
})()"""

_SELECT_CONTACT = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)==='人工识别真实性');
 const selects=[...document.querySelectorAll('select')].filter(visible);const pairs=[];
 for(const label of labels){const lr=label.getBoundingClientRect();for(const select of selects){const r=select.getBoundingClientRect();const dy=Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2);if(r.left>=lr.right-2&&dy<=24)pairs.push({select,score:dy+Math.max(0,r.left-lr.right)/100});}}
 pairs.sort((a,b)=>a.score-b.score);if(!pairs.length)return {ok:false,reason:'人工识别真实性下拉框未找到'};
 const best=pairs[0].score;const winners=[...new Set(pairs.filter(x=>x.score<=best+0.25).map(x=>x.select))];if(winners.length!==1)return {ok:false,reason:'人工识别真实性下拉框不唯一'};
 const select=winners[0];const options=[...select.options].filter(o=>(o.textContent||'').replace(/\s/g,'')==='集团通讯录');if(options.length!==1)return {ok:false,reason:'没有唯一的“集团通讯录”选项'};
 select.value=options[0].value;select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));return {ok:true};
})()"""

_CLICK_CONFIRM = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const compact=e=>(e.innerText||e.value||'').replace(/\s/g,'');
 const buttons=[...document.querySelectorAll('button,input[type=button],input[type=submit],a')].filter(visible).filter(e=>compact(e)==='确定');
 if(buttons.length!==1)return {ok:false,count:buttons.length};
 buttons[0].click();return {ok:true};
})()"""

_READ_OUTCOME = r"""(() => {const text=(document.body?.innerText||'').replace(/\s+/g,'');return {success:/新增成功|添加成功|保存成功|操作成功/.test(text),duplicate:/已是成员|已经存在|重复添加/.test(text),error:/失败|错误|异常/.test(text)};})()"""

# An identifier in arbitrary body text/search results is not a group identity.
_GROUP_IDENTITIES = r"""(() => {
 const visible=e=>{if(!e||!e.getClientRects().length)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return false;}return true;};
 try {for(let w=window;w!==w.parent;w=w.parent){if(!visible(w.frameElement))return [];}} catch(_){return [];}
 const clean=e=>String(e?.value||e?.innerText||e?.textContent||'').trim().replace(/[：:]$/,'').trim();
 const values=[];
 for(const label of document.querySelectorAll('td,th,label,span')){
  if(!visible(label)||!['集团编号','集团编码'].includes(clean(label)))continue;
  let field=label.nextElementSibling;
  if(label.tagName==='LABEL'&&label.htmlFor)field=document.getElementById(label.htmlFor);
  if(!visible(field))continue;
  const value=clean(field.querySelector?.('input')||field);
  if(/^[A-Za-z0-9_-]{3,80}$/.test(value))values.push(value);
 }
 return values;
})()"""

