const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source=fs.readFileSync('app/static/navigation-transitions.js','utf8');
for(const name of ['login.html','account_recovery.html']){
  const auth=fs.readFileSync('app/templates/'+name,'utf8');
  assert(auth.includes('/static/navigation-transitions.js?v=1714" blocking="render"'));
  assert(auth.indexOf('/static/navigation-transitions.css?v=1715')<auth.indexOf('/static/navigation-transitions.js'));
  assert(auth.indexOf('/static/navigation-transitions.js')<auth.indexOf('</head>'));
}
const handlers={};
vm.runInNewContext(source,{window:{addEventListener:(name,handler)=>handlers[name]=handler}});
assert.deepEqual(Object.keys(handlers),['pageswap','pagereveal']);
for(const type of Object.keys(handlers)){
  handlers[type]({});
  let reject;
  handlers[type]({viewTransition:{ready:{catch:handler=>{reject=handler;}}}});
  reject({name:'AbortError'});reject({name:'InvalidStateError'});
  reject(new Error('Transition was aborted because of invalid state. ViewTransition opt-in disabled'));
  const unexpected=new Error('unexpected animation failure');
  assert.throws(()=>reject(unexpected), error=>error===unexpected);
}
const base=fs.readFileSync('app/templates/base.html','utf8');
assert(base.indexOf('/static/navigation-transitions.js')<base.indexOf('</head>'));
assert(base.includes('navigation-transitions.js?v=1714" blocking="render"'));
assert(base.indexOf('/static/navigation-transitions.css?v=1715') < base.indexOf('/static/navigation-transitions.js'));
assert(fs.readFileSync('app/static/navigation-transitions.css','utf8').includes('@view-transition{navigation:auto}'));
console.log('navigation transition contract passed: early observer, expected cancellation and unexpected errors');
