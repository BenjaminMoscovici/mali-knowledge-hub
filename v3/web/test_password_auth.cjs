const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync(`${__dirname}/app.js`,'utf8');
const implementation=source.slice(source.indexOf("  let authMode ="),source.indexOf('  function wire()'));

function harness(send=async()=>({message:'Check your email.'}),hash='') {
  const events=[];const state={user:null};const el={};
  const names=[...implementation.matchAll(/el\['([^']+)'\]/g)].map(m=>m[1]);
  for(const id of [...names,'auth-username','auth-email','auth-password','auth-confirm',
      'auth-username-wrap','auth-email-wrap','auth-password-wrap','auth-confirm-wrap']) {
    el[id]={value:'',disabled:false,required:false,textContent:'',attrs:{},hidden:false,
      classList:{toggle(name,flag){el[id].hidden=flag;}},
      setAttribute(name,value){this.attrs[name]=value;},setCustomValidity(){},focus(){},
      scrollIntoView(){this.scrolled=true;},
      showModal(){events.push('show');},close(){events.push('close');}};
  }
  const location={hash,pathname:'/',search:''};
  const history={replaceState(){events.push('scrub');}};
  const api=new Function('el','state','send','toast','profile','loadAccountThreads','renderThreads','location','history',
    `${implementation};return {setAuthMode,submitAuth,acceptAuthCallback};`)(el,state,
      async(path,payload)=>{events.push(path);return send(path,payload);},
      message=>events.push(message),()=>events.push('profile'),async()=>events.push('history'),
      ()=>events.push('threads'),location,history);
  return {...api,el,state,events};
}
const event={preventDefault(){}};

test('signup shows required username and confirmation; login supports legacy passwords',()=>{
  const h=harness();h.setAuthMode('signup');
  assert.equal(h.el['auth-username'].required,true);assert.equal(h.el['auth-confirm'].disabled,false);
  assert.equal(h.el['auth-password'].minLength,12);assert.equal(h.el['auth-password'].autocomplete,'new-password');
  h.setAuthMode('login');assert.equal(h.el['auth-username'].disabled,true);
  assert.equal(h.el['auth-confirm'].required,false);assert.equal(h.el['auth-password'].minLength,1);
  assert.equal(h.el['auth-password'].maxLength,1024);
});
test('recovery disables hidden passwords so native validation does not block the email request',async()=>{
  let received;const h=harness(async(path,payload)=>{received={path,payload:{...payload}};return {message:'Check email.'};});
  h.setAuthMode('recover');h.el['auth-email'].value='person@example.org';await h.submitAuth(event);
  assert.equal(h.el['auth-password'].disabled,true);assert.equal(h.el['auth-password'].required,false);
  assert.deepEqual(received,{path:'auth/recover',payload:{email:'person@example.org'}});
});
test('mismatched confirmation never reaches the provider',async()=>{
  const h=harness(()=>{throw new Error('Should not send');});h.setAuthMode('signup');
  h.el['auth-password'].value='first passphrase';h.el['auth-confirm'].value='second passphrase';
  await h.submitAuth(event);assert.ok(h.el['auth-status'].textContent.includes('do not match'));
  assert.deepEqual(h.events,[]);
});
test('login preserves account identity, loads private threads and clears credential fields',async()=>{
  let received;const user={id:'existing-id',email:'person@example.org'};
  const h=harness(async(path,payload)=>{received={path,payload:{...payload}};return {user};});
  h.setAuthMode('login');h.el['auth-email'].value=user.email;h.el['auth-password'].value='test passphrase';
  await h.submitAuth(event);assert.equal(h.state.user,user);
  assert.equal(received.path,'auth/login');assert.equal(received.payload.password,'test passphrase');
  assert.equal(h.el['auth-password'].value,'');assert.ok(h.events.includes('history'));assert.ok(h.events.includes('close'));
});
test('failed request clears passwords, releases button and keeps the dialog error visible',async()=>{
  const h=harness(async()=>{throw new Error('Try again later.');});h.setAuthMode('password');
  h.el['auth-password'].value=h.el['auth-confirm'].value='test long passphrase';await h.submitAuth(event);
  assert.equal(h.el['auth-password'].value,'');assert.equal(h.el['auth-confirm'].value,'');
  assert.equal(h.el['auth-submit'].disabled,false);assert.equal(h.el['auth-status'].textContent,'Try again later.');
  assert.equal(h.el['auth-status'].hidden,false);assert.equal(h.el['auth-status'].scrolled,true);
  assert.equal(h.el['auth-status'].attrs.role,'alert');
});
test('accepted signup shows verification outcome and preserves email for explicit resend',async()=>{
  const sent=[];const h=harness(async(path,payload)=>{sent.push({path,payload:{...payload}});return {message:'Signup request accepted. Check your email.'};});
  h.setAuthMode('signup');h.el['auth-email'].value='person@example.org';h.el['auth-username'].value='Researcher';
  h.el['auth-password'].value=h.el['auth-confirm'].value='test long passphrase';
  await h.submitAuth(event);
  assert.equal(h.el['auth-title'].textContent,'Verify your email');
  assert.equal(h.el['auth-password'].disabled,true);assert.equal(h.el['auth-email'].value,'person@example.org');
  assert.equal(h.el['auth-submit'].textContent,'Resend confirmation email');
  assert.equal(h.el['auth-status'].hidden,false);assert.equal(h.el['auth-status'].attrs['data-kind'],'success');
  assert.equal(sent.length,1);assert.equal(sent[0].path,'auth/signup');
  await h.submitAuth(event);
  assert.deepEqual(sent[1],{path:'auth/resend',payload:{email:'person@example.org'}});
});
test('confirmation mode never requires or transmits a password',async()=>{
  let received;const h=harness(async(path,payload)=>{received={path,payload:{...payload}};return {message:'Confirmation requested.'};});
  h.setAuthMode('confirm');h.el['auth-email'].value='person@example.org';await h.submitAuth(event);
  assert.equal(h.el['auth-password'].required,false);assert.equal(h.el['auth-confirm'].required,false);
  assert.equal(h.el['auth-username'].disabled,true);
  assert.deepEqual(received,{path:'auth/resend',payload:{email:'person@example.org'}});
});
test('feedback is placed before credential fields and announced accessibly',()=>{
  const html=fs.readFileSync(`${__dirname}/index.html`,'utf8');
  assert.ok(html.indexOf('id="auth-status"')<html.indexOf('id="auth-form"'));
  assert.ok(html.includes('aria-live="polite"'));assert.ok(html.includes('id="auth-resend"'));
});
test('in-flight submission cannot send the same credentials twice',async()=>{
  let finish;const h=harness(()=>new Promise(resolve=>{finish=resolve;}));h.setAuthMode('login');
  const first=h.submitAuth(event);await h.submitAuth(event);finish({message:'done'});await first;
  assert.equal(h.events.filter(e=>e==='auth/login').length,1);
});
test('recovery callback scrubs URL before exchange and opens password choice',async()=>{
  const h=harness(async()=>({user:{id:'same-id'}}),'#access_token=a&refresh_token=r&type=recovery');
  await h.acceptAuthCallback();assert.deepEqual(h.events,['scrub','auth/session','show']);
  assert.equal(h.el['auth-email'].disabled,true);assert.equal(h.el['auth-confirm'].required,true);
  assert.equal(h.el['auth-title'].textContent,'Choose your password');
});
test('expired or incomplete callback scrubs credentials without sending them',async()=>{
  for(const hash of ['#error=access_denied&error_description=private+provider+detail','#access_token=a']) {
    const h=harness(()=>{throw new Error('Should not send');},hash);await h.acceptAuthCallback();
    assert.deepEqual(h.events,['scrub','show']);assert.ok(h.el['auth-status'].textContent.includes('expired'));
    assert.ok(!h.el['auth-status'].textContent.includes('private'));
  }
});
