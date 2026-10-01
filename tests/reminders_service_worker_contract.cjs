const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');
let activations=0;
const handlers={},shown=[],opened=[],badges=[],origin='https://assistant.ziboxiaozhushou.cn';
const self={location:{origin},addEventListener:(name,fn)=>handlers[name]=fn,skipWaiting(){activations++;return Promise.resolve();},
 registration:{showNotification:async(title,data)=>shown.push({title,...data})},
 navigator:{setAppBadge:async n=>badges.push(n),clearAppBadge:async()=>badges.push(0)},
 clients:{claim:async()=>{},matchAll:async()=>[{url:origin+'/work',focus:()=>{throw Error('wrong page focused')}}],openWindow:async u=>opened.push(u)}};
vm.runInNewContext(fs.readFileSync('app/static/sw.js','utf8'),{self,location:{origin},URL,Number,Promise,caches:{},fetch(){}});
async function fire(name,event){let pending;handlers[name]({...event,waitUntil:p=>pending=p});await pending;}
(async()=>{
 await fire('push',{data:{json:()=>({title:'新号码',body:'有2个号码',url:'/work/number-inbox',id:42,unread_count:3})}});
 assert.equal(shown[0].tag,'chen-reminder-42');assert.equal(shown[0].data.url,origin+'/reminders/open/42');assert.equal(badges[0],3);
 let closed=false;await fire('notificationclick',{notification:{data:shown[0].data,close:()=>closed=true}});
 assert(closed);assert.equal(opened[0],origin+'/reminders/open/42');
 await fire('push',{data:{json:()=>{throw Error('malformed')}}});assert.equal(shown[1].title,'晨的助手提醒');
 await fire('notificationclick',{notification:{data:{url:'https://evil.test/'},close(){}}});assert.equal(opened[1],origin+'/reminders');
 await fire('push',{data:{json:()=>({url:'https://evil.test/',unread_count:0})}});assert.equal(shown[2].data.url,origin+'/reminders');assert.equal(badges[1],0);
 assert.equal(activations,0);await fire('message',{data:{type:'UNKNOWN'}});assert.equal(activations,0);await fire('message',{data:{type:'SKIP_WAITING'}});assert.equal(activations,1);
 console.log('Service Worker contracts passed: closed-page push, visible fallback, deep link, same-origin validation, focus behavior, badge');
})().catch(e=>{console.error(e);process.exit(1)});

