const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(`${__dirname}/admin.js`,'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function page(status, respond=()=>({})) {
  const nodes=new Map(),calls=[];
  class Element {
    constructor(){this.value='';this.textContent='';this.children=[];this.dataset={};this.handlers={};this.hidden=false;this.files=[];}
    append(e){this.children.push(e);} replaceChildren(){this.children=[];} setAttribute(){}
    addEventListener(event,fn){this.handlers[event]=fn;}reset(){this.resetCalled=true;}
  }
  const document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},
    createElement(){return new Element();},querySelectorAll(){return [];}};
  for(const m of fs.readFileSync(`${__dirname}/admin.html`,'utf8').matchAll(/id="([^"]+)"/g))document.getElementById(m[1]);
  const context={document,Date,JSON,Error,encodeURIComponent,fetch:async(path,options)=>{
    calls.push({path,options});let data=path==='/api/admin/status'?status:
      path==='/api/admin/overview'?{jobs:[],invitations:[],administrators:[],source_requests:[],audit:[]}:await respond(path,options);
    return {ok:!data.error,json:async()=>data};}};
  vm.runInNewContext(source,context);await tick();
  return {nodes,calls,async submit(id){const n=document.getElementById(id);n.handlers.submit({preventDefault(){},target:n});await tick();await tick();}};
}
test('guest is shown sign-in and cannot load private admin records',async()=>{
  const p=await page({authenticated:false,is_admin:false});
  assert.equal(p.nodes.get('login').hidden,false);assert.equal(p.nodes.get('workspace').hidden,true);
  assert.equal(p.calls.length,1);
});
test('ordinary signed-in user sees access guidance without fetching the registry',async()=>{
  const p=await page({authenticated:true,is_admin:false,email:'ordinary@example.org'});
  assert.equal(p.nodes.get('denied').hidden,false);assert.equal(p.calls.length,1);
});
test('invited user sees password acceptance but no admin workspace',async()=>{
  const p=await page({authenticated:true,is_admin:false,email:'invite@example.org',pending_invitation:{id:'invite-id',expires_at:'2026-10-22'}});
  assert.equal(p.nodes.get('invitation').hidden,false);assert.equal(p.nodes.get('workspace').hidden,true);
  assert.ok(p.nodes.get('invite-recipient').textContent.includes('invite@example.org'));assert.equal(p.calls.length,1);
});
test('mismatched invitation passwords never call acceptance',async()=>{
  const p=await page({authenticated:true,is_admin:false,email:'invite@example.org',pending_invitation:{id:'invite-id'}});
  p.nodes.get('new-password').value='first long password';p.nodes.get('confirm-password').value='other long password';
  await p.submit('accept-form');assert.equal(p.calls.length,1);assert.equal(p.nodes.get('notice').dataset.error,'true');
});
test('acceptance transmits only its own invitation and password, then clears both inputs',async()=>{
  const p=await page({authenticated:true,is_admin:false,email:'invite@example.org',pending_invitation:{id:'invite-id'}},()=>({message:'Ready'}));
  p.nodes.get('new-password').value=p.nodes.get('confirm-password').value='test long password';
  await p.submit('accept-form');const call=p.calls.find(c=>c.path.endsWith('/accept'));
  assert.deepEqual(JSON.parse(call.options.body),{invitation_id:'invite-id',password:'test long password'});
  assert.equal(p.nodes.get('new-password').value,'');assert.equal(p.nodes.get('confirm-password').value,'');
  assert.equal(p.nodes.get('notice').textContent,'Ready');
});
test('failed sign-in is visible and clears credentials without claiming success',async()=>{
  const p=await page({authenticated:false,is_admin:false},()=>({error:'Check your password.'}));
  p.nodes.get('login-email').value='user@example.org';p.nodes.get('login-password').value='test secret';
  await p.submit('login-form');assert.equal(p.nodes.get('login-password').value,'');
  assert.equal(p.nodes.get('notice').textContent,'Check your password.');assert.equal(p.nodes.get('workspace').hidden,true);
});
test('verified administrator can load the protected registry',async()=>{
  const p=await page({authenticated:true,is_admin:true,email:'admin@example.org'});
  assert.equal(p.nodes.get('workspace').hidden,false);assert.ok(p.calls.some(c=>c.path==='/api/admin/overview'));
});
