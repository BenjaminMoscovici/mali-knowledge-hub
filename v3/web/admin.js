/* Administrator workspace. Credentials stay in same-origin HttpOnly cookies. */
(() => {
  const $=id=>document.getElementById(id);
  let access=null, data=null, busy=false;
  function notice(message,error=false){$('notice').textContent=message;$('notice').hidden=!message;$('notice').dataset.error=String(error);$('notice').setAttribute('role',error?'alert':'status');}
  async function api(path,payload,method='POST'){
    const res=await fetch('/api/'+path,{method:payload===undefined?'GET':method,credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:payload===undefined?undefined:JSON.stringify(payload)});
    let body;try{body=await res.json();}catch{throw Error('The server could not complete this request.');}
    if(!res.ok)throw Error(body.error||'This action could not be completed.');return body;
  }
  async function action(form,task){if(busy)return;busy=true;const buttons=[...document.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
    try{notice('Please wait…');await task();}catch(e){notice(e.message,true);}finally{busy=false;buttons.forEach(b=>b.disabled=false);for(const id of ['login-password','new-password','confirm-password'])$(id).value='';}}
  const date=v=>v?new Date(v).toLocaleString():'—';
  function line(parent,text,tag='p'){const e=document.createElement(tag);e.textContent=text;parent.append(e);return e;}
  function records(id,rows,render){const root=$(id);root.replaceChildren();if(!rows.length){line(root,'No records yet.','div').className='empty';return;}for(const row of rows){const item=document.createElement('article');item.className='record';render(item,row);root.append(item);}}
  function button(parent,text,handler){const b=line(parent,text,'button');b.type='button';b.className='secondary';b.addEventListener('click',()=>action(null,handler));}
  function renderJobs(){const term=$('job-search').value.trim().toLowerCase();records('jobs',(data?.jobs||[]).filter(j=>j.filename.toLowerCase().includes(term)),(item,j)=>{
    line(item,j.filename,'strong');line(item,j.status+' · '+date(j.uploaded_at));if(j.error)line(item,j.error);
    const details=document.createElement('details');line(details,'Metadata and processing quality','summary');line(details,JSON.stringify({metadata:j.metadata,quality:j.quality},null,2),'pre');item.append(details);
    if(['ready','failed','partially processed','queued'].includes(j.status))button(item,j.status==='ready'?'Reprocess original':'Retry processing',async()=>{const r=await api(`admin/documents/${j.id}/reprocess`,{});await load();notice(r.message);});
  });}
  function render(){renderJobs();records('invites',data.invitations,(item,i)=>{
    line(item,i.email,'strong');const expired=['pending','sending'].includes(i.status)&&new Date(i.expires_at)<=new Date();
    line(item,(expired?'expired':i.status)+' · invited '+date(i.created_at)+' · expires '+date(i.expires_at));
    if(['pending','sending'].includes(i.status))button(item,'Revoke invitation',async()=>{const r=await api(`admin/invitations/${i.id}`,{},'DELETE');await load();notice(r.message);});
  });records('members',data.administrators,(item,m)=>{line(item,m.email,'strong');line(item,'Accepted '+date(m.created_at));});
    records('source-requests',data.source_requests,(item,s)=>{line(item,s.title,'strong');line(item,'Awaiting connector review · '+s.url);if(s.organization)line(item,s.organization);if(s.notes)line(item,s.notes);});
    records('audit',data.audit,(item,a)=>line(item,a.action.replaceAll('_',' ')+' · '+date(a.created_at)));
  }
  async function load(){access=await api('admin/status');for(const id of ['login','invitation','denied','workspace'])$(id).hidden=true;
    $('identity').replaceChildren();if(!access.authenticated){$('login').hidden=false;return;}
    line($('identity'),access.email,'span');button($('identity'),'Sign out',async()=>{await api('auth/logout',{});data=null;await load();notice('Signed out.');});
    if(access.is_admin){data=await api('admin/overview');$('workspace').hidden=false;render();}
    else if(access.pending_invitation){$('invitation').hidden=false;$('invite-recipient').textContent='Invited account: '+access.email+' · invitation expires '+date(access.pending_invitation.expires_at);}
    else $('denied').hidden=false;
  }
  $('login-form').addEventListener('submit',e=>{e.preventDefault();action(e.target,async()=>{await api('auth/login',{email:$('login-email').value,password:$('login-password').value});await load();notice(access.is_admin?'Signed in to administration.':access.pending_invitation?'Your email is verified. Choose your password to accept the invitation.':'Signed in. This account does not have administrator access.');});});
  $('accept-form').addEventListener('submit',e=>{e.preventDefault();if($('new-password').value!==$('confirm-password').value){notice('The passwords do not match.',true);return;}action(e.target,async()=>{const r=await api('admin/invitations/accept',{invitation_id:access.pending_invitation.id,password:$('new-password').value});await load();notice(r.message);});});
  $('invite-form').addEventListener('submit',e=>{e.preventDefault();action(e.target,async()=>{const r=await api('admin/invitations',{email:$('invite-email').value});$('invite-email').value='';await load();notice(r.message);});});
  $('source-form').addEventListener('submit',e=>{e.preventDefault();action(e.target,async()=>{const payload={};for(const key of ['title','url','organization','notes'])payload[key]=$('source-'+key).value;const r=await api('admin/source-requests',payload);e.target.reset();await load();notice(r.message);});});
  $('upload-form').addEventListener('submit',e=>{e.preventDefault();action(e.target,async()=>{const file=$('document-file').files[0];if(!file||file.size>20*1024*1024)throw Error('Choose a document smaller than 20 MB.');
    const res=await fetch('/api/admin/documents',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/octet-stream','X-MKH-Filename':encodeURIComponent(file.name)},body:file});const r=await res.json();if(!res.ok)throw Error(r.error||'The upload could not be queued.');e.target.reset();await load();notice(r.message);});});
  $('refresh').addEventListener('click',()=>action(null,async()=>{await load();notice('Registry refreshed.');}));$('job-search').addEventListener('input',renderJobs);
  load().catch(e=>notice(e.message,true));
})();
