/* Mali Knowledge Hub conversation workspace. No provider keys enter the browser. */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { user:null, threads:[], guest:[], selected:null, messages:[], busy:false,
    sources:[], sourcePosition:null, search:'', archivedOpen:false };
  const GUEST_KEY = 'mkh-guest-threads-v1';
  const ids = ['workspace','sidebar-scrim','thread-list','archived-wrap','archived-list',
    'archived-count','thread-search','search-wrap','history-label','welcome','messages',
    'conversation-scroll','prompt','send-button','analysis-mode','topbar-title',
    'topbar-sources','evidence-drawer','drawer-scrim','drawer-body','auth-dialog',
    'auth-form','auth-email','auth-status','profile-menu','profile-title','profile-detail',
    'avatar','toast','text-attachment'];
  const el = Object.fromEntries(ids.map(id => [id,$(id)]));
  const escaped = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const identifier = () => crypto.randomUUID();
  const guestSelected = () => state.guest.find(t => t.id === state.selected);
  const isGuestThread = () => !!guestSelected();
  const conversation = () => state.threads.find(t => t.id === state.selected) || guestSelected();
  const mobile = () => matchMedia('(max-width:800px)').matches;
  let toastTimer;

  async function api(path, options={}) {
    const response = await fetch('/api/' + path, { credentials:'same-origin',
      headers:{'Content-Type':'application/json'}, ...options });
    let data;
    try { data = await response.json(); } catch { throw new Error('The server did not respond as expected.'); }
    if (!response.ok) throw new Error(data.error || 'This action could not be completed.');
    return data;
  }
  const send = (path, data, method='POST') => api(path, {method, body:JSON.stringify(data)});
  function toast(message) {
    el.toast.textContent = message; el.toast.classList.remove('hidden');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.toast.classList.add('hidden'), 5200);
  }
  function saveGuest() {
    try { sessionStorage.setItem(GUEST_KEY, JSON.stringify(state.guest.slice(0,30))); }
    catch { toast('This browser cannot save the guest conversation in this tab.'); }
  }
  function loadGuest() {
    try {
      const rows = JSON.parse(sessionStorage.getItem(GUEST_KEY) || '[]');
      state.guest = Array.isArray(rows) ? rows.filter(t => t && typeof t.id === 'string'
        && Array.isArray(t.messages)).slice(0,30) : [];
    } catch { state.guest = []; }
  }
  function profile() {
    if (state.user) {
      el['profile-title'].textContent = state.user.email || 'Your research';
      el['profile-detail'].textContent = 'Research history saved privately';
      el.avatar.textContent = (state.user.email || 'A')[0].toUpperCase();
    } else {
      el['profile-title'].textContent = 'Guest research';
      el['profile-detail'].textContent = 'Sign in to save your work';
      el.avatar.textContent = 'G';
    }
    el['profile-menu'].replaceChildren();
    const add = (label, handler) => {
      const b = document.createElement('button'); b.textContent = label;
      b.addEventListener('click', () => { el['profile-menu'].classList.add('hidden'); handler(); });
      el['profile-menu'].append(b);
    };
    if (state.user) {
      if (isGuestThread() && state.messages.length) add('Save this guest chat', importCurrentGuest);
      add('Sign out', logout);
    } else add('Sign in to save chats', () => el['auth-dialog'].showModal());
  }
  function threadElement(thread, archived=false) {
    const row = document.createElement('div');
    row.className = 'thread-row' + (thread.id === state.selected ? ' active' : '');
    const select = document.createElement('button'); select.className = 'thread-title';
    select.textContent = thread.title || 'Untitled research'; select.title = select.textContent;
    select.addEventListener('click', () => openThread(thread.id)); row.append(select);
    const menu = document.createElement('button'); menu.className = 'icon-button thread-menu-button';
    menu.innerHTML = '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>';
    menu.setAttribute('aria-label','Conversation options'); row.append(menu);
    const options = document.createElement('div'); options.className = 'thread-menu hidden';
    for (const [label, action, danger] of [
      ['Rename', () => renameThread(thread), false],
      [archived ? 'Restore' : 'Archive', () => archiveThread(thread, !archived), false],
      ['Delete', () => deleteThread(thread), true]]) {
      const b = document.createElement('button'); b.className = 'menu-option' + (danger?' danger':'');
      b.textContent = label; b.addEventListener('click', (event) => {
        event.stopPropagation(); options.classList.add('hidden'); action();
      }); options.append(b);
    }
    menu.addEventListener('click', (event) => {
      event.stopPropagation(); document.querySelectorAll('.thread-menu').forEach(m => {
        if (m !== options) m.classList.add('hidden');
      }); options.classList.toggle('hidden');
    });
    const wrap = document.createElement('div'); wrap.append(row,options);
    return wrap;
  }
  function renderThreads() {
    const all = [...state.threads, ...state.guest].sort((a,b) =>
      new Date(b.updated_at || 0) - new Date(a.updated_at || 0));
    const matched = all.filter(t => (t.title || '').toLowerCase().includes(state.search));
    const active = matched.filter(t => !t.archived_at);
    const archived = matched.filter(t => t.archived_at);
    el['thread-list'].replaceChildren(...active.map(t => threadElement(t)));
    el['archived-list'].replaceChildren(...archived.map(t => threadElement(t,true)));
    el['history-label'].textContent = state.search ? 'Search results' : 'Recent';
    el['archived-wrap'].classList.toggle('hidden', !archived.length);
    el['archived-count'].textContent = `(${archived.length})`;
    el['archived-list'].classList.toggle('hidden', !state.archivedOpen);
  }
  function startFresh() {
    if (state.busy) { toast('Wait for the current answer before starting a new chat.'); return; }
    state.selected = null; state.messages = []; state.sources = []; state.sourcePosition=null;
    el.prompt.value = ''; el['analysis-mode'].value = 'balanced'; resizePrompt();
    renderConversation(); renderThreads(); profile(); closeDrawer();
    if (mobile()) closeSidebar();
    el.prompt.focus(); history.replaceState(null,'','/');
  }
  async function openThread(id) {
    if (state.busy || !id) return;
    state.selected=id; closeDrawer();
    const local = guestSelected();
    if (local) {
      state.messages=local.messages; el['analysis-mode'].value=local.analysis_mode || 'balanced';
      renderConversation(); renderThreads(); profile();
    } else {
      try {
        const result = await api(`conversations/${encodeURIComponent(id)}`);
        if (state.selected !== id) return;
        state.messages=result.messages || [];
        el['analysis-mode'].value=result.conversation.analysis_mode || 'balanced';
        renderConversation(); renderThreads(); profile();
      } catch (err) { toast(err.message); startFresh(); }
    }
    if (mobile()) closeSidebar();
    history.replaceState(null,'',`/?chat=${encodeURIComponent(id)}`);
  }
  function markdown(raw, evidence) {
    // Escape first, then apply a small answer-oriented Markdown subset. Citations
    // become buttons only if the ID is in this answer's actual evidence list.
    const sources = new Map((evidence || []).map((item,i) => [item.evidence_id, i]));
    let safe = escaped(raw);
    safe = safe.replace(/\bE\d{2,}\b/g, id => sources.has(id)
      ? `<button class="citation" data-source="${sources.get(id)}" title="Inspect ${id}">${id}</button>` : id);
    safe = safe.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
    const blocks = []; let paragraph = [], list = [], listType = null;
    const flushParagraph = () => {
      if (paragraph.length) blocks.push(`<p>${paragraph.join('<br>')}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (list.length) blocks.push(`<${listType}>${list.map(text => `<li>${text}</li>`).join('')}</${listType}>`);
      list = []; listType = null;
    };
    for (const line of safe.split(/\r?\n/)) {
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      const item = line.match(/^\s*(?:([-*+])\s+|\d+[.)]\s+)(.+)$/);
      if (!line.trim()) { flushParagraph(); flushList(); continue; }
      if (heading) {
        flushParagraph(); flushList();
        const level = heading[1].length === 3 ? 3 : 2;
        blocks.push(`<h${level}>${heading[2]}</h${level}>`);
      } else if (item) {
        flushParagraph();
        const type = item[1] ? 'ul' : 'ol';
        if (listType && listType !== type) flushList();
        listType = type; list.push(item[2]);
      } else { flushList(); paragraph.push(line); }
    }
    flushParagraph(); flushList();
    return blocks.join('');
  }
  function evidenceFor(message) { return message.evidence || message.evidence_refs || []; }
  function renderConversation() {
    const hasMessages=state.messages.length>0;
    el.welcome.classList.toggle('hidden',hasMessages);
    el.messages.replaceChildren();
    for (const message of state.messages) {
      const wrap=document.createElement('div'); wrap.className='message ' + message.role;
      if (message.role==='user') {
        const bubble=document.createElement('div'); bubble.className='user-bubble';
        bubble.textContent=message.content; wrap.append(bubble);
      } else {
        const answer=document.createElement('div'); answer.className='assistant-turn';
        const evidence=evidenceFor(message);
        answer.innerHTML=markdown(message.content, evidence);
        answer.querySelectorAll('.citation').forEach(b => b.addEventListener('click', () =>
          showSources(message,Number(b.dataset.source))));
        wrap.append(answer);
        const footer=document.createElement('div'); footer.className='message-footer';
        const button=document.createElement('button'); button.className='sources-button';
        button.textContent=evidence.length ? `View sources (${evidence.length})` : 'View sources';
        button.addEventListener('click', () => showSources(message)); footer.append(button);
        if (message.analysis_mode) {
          const label=document.createElement('span'); label.textContent=message.analysis_mode[0].toUpperCase()+message.analysis_mode.slice(1);
          footer.append(label);
        }
        wrap.append(footer);
      }
      el.messages.append(wrap);
    }
    el['topbar-title'].textContent = conversation()?.title || 'Mali Knowledge Hub';
    el['topbar-sources'].classList.toggle('hidden',!state.messages.some(m => m.role==='assistant'));
    requestAnimationFrame(() => el['conversation-scroll'].scrollTop=el['conversation-scroll'].scrollHeight);
  }
  function renderEvidence(evidence, selected) {
    el['drawer-body'].replaceChildren();
    if (!evidence.length) {
      const p=document.createElement('p'); p.className='empty-evidence';
      p.textContent='No source passages are attached to this message.';
      el['drawer-body'].append(p); return;
    }
    evidence.forEach((source,index) => {
      const card=document.createElement('article'); card.className='evidence-item'+(index===selected?' selected':'');
      const title=document.createElement('h3');
      title.textContent=`${source.evidence_id || `Source ${index+1}`} · ${source.document_title || source.organization || source.source_family || 'Source record'}`;
      card.append(title);
      const period = [source.reference_period_start,source.reference_period_end]
        .filter(Boolean).map(date => String(date).slice(0,10)).join(' – ');
      const parts=[source.organization,source.publication_date,source.page && `Page ${source.page}`,
        source.geographic_scope,period && `Period ${period}`,
        source.retrieved_at && `Retrieved ${String(source.retrieved_at).slice(0,10)}`].filter(Boolean);
      const meta=document.createElement('div'); meta.className='evidence-meta';
      meta.textContent=parts.join(' · '); card.append(meta);
      if (source.locator || source.section) {
        const locator=document.createElement('div'); locator.className='evidence-meta';
        locator.textContent=source.locator || source.section; card.append(locator);
      }
      if (source.source_endpoint && /^https?:\/\//i.test(source.source_endpoint)) {
        const link=document.createElement('a'); link.href=source.source_endpoint;
        link.target='_blank'; link.rel='noopener noreferrer'; link.textContent='Open original source';
        card.append(link);
      }
      const excerpt=source.content || source.source_excerpt;
      if (source.source_excerpt && !source.content) {
        const note=document.createElement('p'); note.className='evidence-meta';
        note.textContent='Saved evidence snapshot from this answer; later research checks sources again.';
        card.append(note);
      }
      if (excerpt) {
        const block=document.createElement('blockquote'); block.textContent=excerpt; card.append(block);
      }
      el['drawer-body'].append(card);
      if (index===selected) requestAnimationFrame(() => card.scrollIntoView({block:'nearest'}));
    });
  }
  async function showSources(message, selected) {
    state.sources=evidenceFor(message); state.sourcePosition=message.position;
    renderEvidence(state.sources,selected);
    el['evidence-drawer'].classList.remove('hidden');
    if (mobile()) el['drawer-scrim'].classList.remove('hidden');
    if (state.user && !isGuestThread() && message.position && state.sources.some(s => s.chunk_id && !s.content)) {
      try {
        const cid=state.selected;
        const data=await api(`conversations/${encodeURIComponent(cid)}/evidence?position=${message.position}`);
        if (state.selected!==cid || state.sourcePosition!==message.position) return;
        message.evidence_refs=data.evidence;
        state.sources=data.evidence; renderEvidence(state.sources,selected);
      } catch { toast('Some saved source passages could not be loaded.'); }
    }
  }
  function closeDrawer() { el['evidence-drawer'].classList.add('hidden'); el['drawer-scrim'].classList.add('hidden'); }
  function closeSidebar() { el.workspace.classList.add('sidebar-hidden'); el['sidebar-scrim'].classList.add('hidden'); }
  function openSidebar() { el.workspace.classList.remove('sidebar-hidden'); if(mobile()) el['sidebar-scrim'].classList.remove('hidden'); }
  function resizePrompt() {
    el.prompt.style.height='auto'; el.prompt.style.height=Math.min(el.prompt.scrollHeight,220)+'px';
    el['send-button'].disabled=state.busy || !el.prompt.value.trim();
  }
  function progress() {
    const row=document.createElement('div'); row.className='research-state';
    row.setAttribute('role','status');
    row.innerHTML='<span class="pulse"></span><span></span>';
    row.lastChild.textContent='Preparing your answer…'; el.messages.append(row);
    el['conversation-scroll'].scrollTop=el['conversation-scroll'].scrollHeight;
    return () => row.remove();
  }
  async function ask() {
    const question=el.prompt.value.trim(); if (!question || state.busy) return;
    if (state.user && isGuestThread()) {
      toast('Save this guest chat from your profile before continuing, or start a new chat.');
      return;
    }
    state.busy=true; el.prompt.value=''; resizePrompt();
    $('new-chat').disabled=true; $('profile-button').disabled=true;
    el['analysis-mode'].disabled=true;
    const unlock = () => {
      state.busy=false; $('new-chat').disabled=false; $('profile-button').disabled=false;
      el['analysis-mode'].disabled=false; resizePrompt();
    };
    const mode=el['analysis-mode'].value; const current=conversation();
    if (!current) {
      if (state.user) {
        try {
          const data=await send('conversations',{title:question.slice(0,80),analysis_mode:mode});
          state.selected=data.conversation.id; state.threads.unshift(data.conversation);
        } catch(err) {el.prompt.value=question;unlock();toast(err.message);return;}
      } else {
        const id=identifier(); state.selected=id;
        state.guest.unshift({id,title:question.slice(0,80),analysis_mode:mode,
          updated_at:new Date().toISOString(),messages:[]});
      }
    }
    const thread=conversation();
    const prior=state.messages.map(m => ({role:m.role,content:m.content,
      standalone_question:m.standalone_question}));
    state.messages.push({role:'user',content:question,analysis_mode:mode});
    renderConversation(); renderThreads(); profile();
    const stop=progress();
    const requestStarted=performance.now();
    try {
      const data=await send('chat',{question,analysis_mode:mode,
        conversation_id:state.user && !isGuestThread() ? state.selected : null,
        prior_messages:!state.user || isGuestThread() ? prior : undefined});
      stop();
      if(data.metrics) console.info('MKH_QUERY_METRICS '+JSON.stringify({...data.metrics,
        client_seconds:Number(((performance.now()-requestStarted)/1000).toFixed(4))}));
      const message={role:'assistant',content:data.answer,evidence:data.evidence || [],
        standalone_question:data.standalone_question,position:data.position,analysis_mode:mode};
      state.messages.push(message);
      thread.analysis_mode=mode;
      if (data.save_error) toast('The answer is available, but it could not be saved.');
      if (state.user && data.conversation_id) {
        state.selected=data.conversation_id;
        thread.id=data.conversation_id;
        thread.updated_at=new Date().toISOString();
      } else { thread.messages=state.messages; thread.updated_at=new Date().toISOString();saveGuest(); }
      renderConversation(); renderThreads(); profile();
      history.replaceState(null,'',`/?chat=${encodeURIComponent(state.selected)}`);
    } catch (err) {
      stop(); state.messages.pop();
      el.prompt.value=question; toast(err.message); renderConversation();
    } finally {unlock();el.prompt.focus();}
  }
  async function renameThread(thread) {
    if(state.busy)return;
    const title=prompt('Rename conversation',thread.title || 'New conversation');
    if (!title || !title.trim()) return;
    if (state.user && !state.guest.includes(thread)) {
      try {await send(`conversations/${thread.id}`,{title:title.trim()},'PATCH');}
      catch(err){toast(err.message);return;}
    }
    thread.title=title.trim().slice(0,120); saveGuest(); renderThreads();renderConversation();
  }
  async function archiveThread(thread, archived) {
    if(state.busy)return;
    if (state.user && !state.guest.includes(thread)) {
      try {await send(`conversations/${thread.id}`,{archived},'PATCH');}
      catch(err){toast(err.message);return;}
    }
    thread.archived_at=archived?new Date().toISOString():null;saveGuest();renderThreads();
    if (state.selected===thread.id && archived) startFresh();
  }
  async function deleteThread(thread) {
    if(state.busy)return;
    if (!confirm('Delete this conversation and its messages?')) return;
    if (state.user && !state.guest.includes(thread)) {
      try {await send(`conversations/${thread.id}`,{},'DELETE');}
      catch(err){toast(err.message);return;}
      state.threads=state.threads.filter(t=>t!==thread);
    } else {state.guest=state.guest.filter(t=>t!==thread);saveGuest();}
    if(state.selected===thread.id)startFresh();else renderThreads();
  }
  async function importCurrentGuest() {
    const guest=guestSelected(); if (!guest || !state.user || guest.messages.length<2) return;
    try {
      const result=await send('conversations/import',{title:guest.title,
        analysis_mode:guest.analysis_mode,messages:guest.messages});
      state.guest=state.guest.filter(t=>t!==guest);saveGuest();
      await loadAccountThreads();await openThread(result.conversation_id);
      toast('Conversation saved to your account.');
    } catch(err){toast(err.message);}
  }
  async function loadAccountThreads() {
    if (!state.user) {state.threads=[];renderThreads();return;}
    try {state.threads=(await api('conversations')).conversations || [];renderThreads();}
    catch(err){toast(err.message);}
  }
  async function logout() {
    try {await send('auth/logout',{});} catch {}
    state.user=null;state.threads=[];startFresh();profile();toast('Signed out.');
  }
  function wire() {
    $('new-chat').addEventListener('click',startFresh);
    $('search-toggle').addEventListener('click',() => {
      el['search-wrap'].classList.toggle('hidden'); el['thread-search'].focus();
    });
    el['thread-search'].addEventListener('input',e => {state.search=e.target.value.toLowerCase();renderThreads();});
    $('archived-toggle').addEventListener('click',()=> {state.archivedOpen=!state.archivedOpen;renderThreads();});
    $('sidebar-collapse').addEventListener('click',closeSidebar);
    $('sidebar-open').addEventListener('click',openSidebar);
    el['sidebar-scrim'].addEventListener('click',closeSidebar);
    $('drawer-close').addEventListener('click',closeDrawer);
    el['drawer-scrim'].addEventListener('click',closeDrawer);
    el['topbar-sources'].addEventListener('click',() => {
      const last=[...state.messages].reverse().find(m=>m.role==='assistant');
      if(last)showSources(last);
    });
    el.prompt.addEventListener('input',resizePrompt);
    el.prompt.addEventListener('keydown',e => {if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();}});
    el['send-button'].addEventListener('click',ask);
    document.querySelectorAll('.suggestion').forEach(b => b.addEventListener('click',()=> {
      el.prompt.value=b.textContent;resizePrompt();el.prompt.focus();
    }));
    $('plus-button').addEventListener('click',()=>el['text-attachment'].click());
    el['text-attachment'].addEventListener('change',async () => {
      const file=el['text-attachment'].files[0]; if(!file)return;
      if(file.size>25_000){toast('Choose a text file smaller than 25 KB.');return;}
      try {
        const content=await file.text(); const insertion=`\n\nContext from ${file.name} (user-provided, verify against cited sources):\n${content}`;
        if(el.prompt.value.length+insertion.length>5000){toast('The question and attachment must fit within 5,000 characters.');return;}
        el.prompt.value+=insertion;resizePrompt();el.prompt.focus();
      } catch {toast('This text file could not be read.');}
      el['text-attachment'].value='';
    });
    $('profile-button').addEventListener('click',()=>el['profile-menu'].classList.toggle('hidden'));
    document.addEventListener('click',e=>{
      if(!e.target.closest('.profile-menu,.profile'))el['profile-menu'].classList.add('hidden');
      if(!e.target.closest('.thread-menu,.thread-menu-button'))document.querySelectorAll('.thread-menu').forEach(m=>m.classList.add('hidden'));
    });
    el['auth-form'].addEventListener('submit',async e=>{
      e.preventDefault();el['auth-status'].textContent='Sending a sign-in link…';
      try {const data=await send('auth/email',{email:el['auth-email'].value});el['auth-status'].textContent=data.message;}
      catch(err){el['auth-status'].textContent=err.message;}
    });
    addEventListener('resize',()=> {if(mobile())closeSidebar();});
  }
  async function init() {
    wire();loadGuest();if(mobile())closeSidebar();resizePrompt();
    const hash=new URLSearchParams(location.hash.slice(1));
    if(hash.has('access_token') && hash.has('refresh_token')) {
      // Clear URL fragments before any other network request or interaction.
      const access_token=hash.get('access_token'),refresh_token=hash.get('refresh_token');
      history.replaceState(null,'',location.pathname+location.search);
      try {const result=await send('auth/session',{access_token,refresh_token});state.user=result.user;toast('Signed in.');}
      catch(err){toast(err.message);}
    }
    if(!state.user) {
      try {state.user=(await api('me')).user;}catch {state.user=null;}
    }
    profile();renderThreads();renderConversation();
    if(state.user)await loadAccountThreads();
    const requested=new URLSearchParams(location.search).get('chat');
    if(requested && conversationById(requested))await openThread(requested);
  }
  function conversationById(id){return [...state.threads,...state.guest].some(t=>t.id===id);}
  init();
})();
