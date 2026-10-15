/* Mali Knowledge Hub conversation workspace. No provider keys enter the browser. */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { user:null, threads:[], guest:[], selected:null, messages:[], busy:false,
    sources:[], sourcePosition:null, search:'', archivedOpen:false };
  const GUEST_KEY = 'mkh-guest-threads-v1';
  const ids = ['workspace','sidebar-scrim','thread-list','archived-wrap','archived-list',
    'archived-count','thread-search','search-wrap','history-label','welcome','messages',
    'conversation-scroll','prompt','send-button','analysis-mode','topbar-title',
    'topbar-sources','topbar-export','evidence-drawer','drawer-scrim','drawer-body','auth-dialog',
    'auth-form','auth-email','auth-status','profile-menu','profile-title','profile-detail',
    'avatar','toast','text-attachment','auth-title','auth-description','auth-login','auth-signup',
    'auth-username','auth-username-wrap','auth-email-wrap','auth-password','auth-password-wrap',
    'auth-confirm','auth-confirm-wrap','auth-password-help','auth-submit','auth-recover','auth-link','auth-resend',
    'auth-tabs','auth-progress','auth-step-1','auth-step-2','auth-step-3','auth-confirm-help','auth-recipient',
    'auth-change-email','auth-complete','auth-complete-email','auth-continue','auth-links'];
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
      el['profile-title'].textContent = state.user.username || state.user.email || 'Your research';
      el['profile-detail'].textContent = state.user.username ? state.user.email : 'Research history saved privately';
      el.avatar.textContent = (state.user.username || state.user.email || 'A')[0].toUpperCase();
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
      add('Set / change password', () => openAuth('password'));
      if(state.adminAccess || state.adminInvitation)add('Administration',()=>location.assign('/admin'));
      add('Sign out', logout);
    } else add('Sign in / create account', () => openAuth('login'));
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
    const lines = safe.split(/\r?\n/);
    const cells = (line) => line.trim().replace(/^\||\|$/g,'')
      .split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g,'|'));
    for (let i=0; i<lines.length; i++) {
      const line=lines[i];
      if (line.trim().startsWith('|') && i+1<lines.length) {
        const header=cells(line), divider=cells(lines[i+1]);
        if (header.length>1 && divider.length===header.length &&
            divider.every(cell => /^:?-{3,}:?$/.test(cell))) {
          flushParagraph(); flushList();
          const body=[]; i++;
          while (i+1<lines.length && lines[i+1].trim().startsWith('|')) {
            const row=cells(lines[i+1]);
            if (row.length!==header.length) break;
            body.push(`<tr>${row.map(text => `<td>${text}</td>`).join('')}</tr>`); i++;
          }
          blocks.push(`<div class="answer-table"><table><thead><tr>${header.map(text => `<th scope="col">${text}</th>`).join('')}</tr></thead><tbody>${body.join('')}</tbody></table></div>`);
          continue;
        }
      }
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
  function researchBrief(message, question, exportedAt, options={}) {
    const answer=String(message.content || '');
    const ids=new Set(answer.match(/\bE\d{2,}\b/g) || []);
    const sources=evidenceFor(message).filter(source=>ids.has(source.evidence_id));
    const present=new Set(sources.map(source=>source.evidence_id));
    const missing=[...ids].filter(id=>!present.has(id));
    const text=value=>String(value || '').replace(/[\\`*_\[\]<>]/g,'\\$&').replace(/\r?\n/g,' ');
    const heading=(offset,label)=>'#'.repeat((options.level || 1)+offset)+' '+label;
    const lines=[heading(0,options.title || 'Mali Knowledge Hub — research brief'),'',
      `Exported: ${exportedAt}`,'',
      'This is a saved research snapshot. Source dates below retain their original meaning; exporting does not refresh the evidence.','',
      heading(1,'Research question'),'',...String(question || 'Question unavailable in this saved turn.').split('\n').map(line=>'> '+line),''];
    if(message.standalone_question && message.standalone_question!==question) {
      lines.push('Resolved research scope:','',...String(message.standalone_question).split('\n').map(line=>'> '+line),'');
    }
    if(message.created_at) lines.push('Answer recorded: '+text(message.created_at),'');
    lines.push(heading(1,'Answer'),'',answer,'',heading(1,'Cited source references'),'');
    if(!sources.length) lines.push('No cited source references are available in this saved answer.');
    for(const source of sources) {
      lines.push(heading(2,text(source.evidence_id)+' — '+text(source.document_title || source.organization || source.source_family || 'Source record')),'');
      for(const [label,value] of [['Publisher',source.organization],['Source family',source.source_family],
        ['Publication date',source.publication_date],['Source update',source.project_record?.source_updated_at || source.funding_record?.source_updated_at],
        ['Reference period', [source.reference_period_start,source.reference_period_end].filter(Boolean).join(' – ')],
        ['Geographic scope',source.geographic_scope],['Retrieved',source.retrieved_at],
        ['Locator',source.locator || source.section],['Page',source.page]]) {
        if(value!==null && value!==undefined && value!=='') lines.push('- '+label+': '+text(value));
      }
      try {
        const endpoint=new URL(source.source_endpoint);
        if(['https:','http:'].includes(endpoint.protocol)) lines.push('- Original source: <'+endpoint.href.replace(/</g,'%3C').replace(/>/g,'%3E')+'>');
      } catch { /* Missing or invalid URLs remain absent, never invented. */ }
      lines.push('');
    }
    if(missing.length) lines.push('Unresolved citation identifiers in this saved answer: '+missing.join(', ')+'. Check the original conversation before relying on these claims.','');
    lines.push('References identify the records cited by this answer. They do not independently verify its claims; check the original passages before a programme or coordination decision.');
    return lines.join('\n');
  }
  function researchDossier(messages,title,exportedAt) {
    const text=value=>String(value || '').replace(/[\\`*_\[\]<>]/g,'\\$&').replace(/\r?\n/g,' ');
    const lines=['# Mali Knowledge Hub — research dossier','',
      'Conversation: '+text(title || 'Research conversation'),'', 'Exported: '+exportedAt,'',
      'This dossier preserves the research conversation in order. Evidence IDs belong to each answer; the same ID in another turn may refer to a different source. Exporting does not refresh the evidence.',''];
    let question, pending=false, turn=0;
    for(const message of messages) {
      if(message.role==='user') {question=message.content;pending=true;}
      if(message.role!=='assistant') continue;
      turn+=1;
      lines.push(researchBrief(message,question,exportedAt,{level:2,title:'Research turn '+turn}),'','---','');
      pending=false;
    }
    if(pending) lines.push('## Open research question','',...String(question || '').split('\n').map(line=>'> '+line),'','No answer is recorded for this question.');
    return lines.join('\n');
  }
  function exportDossier() {
    if(state.busy)return;
    const exportedAt=new Date().toISOString();
    const blob=new Blob([researchDossier(state.messages,conversation()?.title,exportedAt)],{type:'text/markdown;charset=utf-8'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=`MKH_research_dossier_${exportedAt.slice(0,10)}.md`;
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    toast('Research dossier exported with questions, answers and cited sources.');
  }
  function exportBrief(message) {
    const index=state.messages.indexOf(message);
    const question=state.messages.slice(0,index).reverse().find(turn=>turn.role==='user')?.content;
    const exportedAt=new Date().toISOString();
    const blob=new Blob([researchBrief(message,question,exportedAt)],{type:'text/markdown;charset=utf-8'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=`MKH_research_brief_${exportedAt.slice(0,10)}.md`;
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    toast('Research brief exported with cited source references.');
  }
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
        const exportButton=document.createElement('button');exportButton.className='sources-button';
        exportButton.textContent='Export brief';
        exportButton.addEventListener('click',()=>exportBrief(message));footer.append(exportButton);
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
    el['topbar-export'].classList.toggle('hidden',!state.messages.some(m => m.role==='assistant'));
    el['topbar-export'].disabled=state.busy;
    requestAnimationFrame(() => el['conversation-scroll'].scrollTop=el['conversation-scroll'].scrollHeight);
  }
  function evidenceView(evidence, answer, selected, showAll) {
    const mentioned = new Set(String(answer || '').match(/\bE\d{2,}\b/g) || []);
    const cited = evidence.filter(source => mentioned.has(source.evidence_id));
    // Keep original indices: citation buttons refer to the retrieved ledger.
    const all = showAll || !cited.length || (selected !== undefined &&
      !mentioned.has(evidence[selected]?.evidence_id));
    return {citedCount: cited.length, all,
      rows: evidence.map((source, index) => ({source, index})).filter(row =>
        all || mentioned.has(row.source.evidence_id))};
  }
  function evidencePresentation(source, answer) {
    const original=String(source.content || source.source_excerpt || '');
    let passage=original;
    const notes=[];
    const label='Geography validation: ';
    const start=original.indexOf(label);
    if(start>=0 && original[start+label.length]==='{') {
      // Only separate a complete, valid, explicitly labelled JSON object.
      // Everything else, especially source caveats, remains verbatim.
      let depth=0, quoted=false, escaped=false, end=-1;
      for(let i=start+label.length;i<original.length;i++) {
        const c=original[i];
        if(quoted){if(escaped)escaped=false;else if(c==='\\')escaped=true;else if(c==='"')quoted=false;}
        else if(c==='"')quoted=true;
        else if(c==='{')depth++;
        else if(c==='}' && --depth===0){end=i+1;break;}
      }
      if(end>0) {
        try {
          const validation=JSON.parse(original.slice(start+label.length,end));
          const issues=Array.isArray(validation.issues)?validation.issues:[];
          if(issues.length) notes.push(issues.some(i=>i?.reason==='source_label_only_no_approved_commune_crosswalk') ?
            'Commune labels are not verified against an approved crosswalk.' :
            'Geographic matching has unresolved issues; inspect the technical details before using place relationships.');
          passage=original.slice(0,start)+'[Geographic matching metadata is in Technical details.]'+original.slice(end);
        } catch { /* Keep incomplete or unfamiliar records fully visible. */ }
      }
    }
    const readingNotes={
      displacement_stock:'Stock observations are not movement flows or evidence of durable return.',
      operational_presence:'Reported presence does not establish services delivered or people reached.',
      fongim_structured:'A recorded project does not establish delivery, funding adequacy or impact.'
    };
    if(readingNotes[source.source_type])notes.unshift(readingNotes[source.source_type]);
    const id=String(source.evidence_id||'');
    const claim=id && String(answer||'').split(/\n/).find(line=>
      [...line.matchAll(/\[(E\d{2,}(?:\s*,\s*E\d{2,})*)\]/g)].some(m=>m[1].split(/\s*,\s*/).includes(id)));
    return {original,passage,notes,claim:claim||''};
  }
  function evidenceSourceURL(value) {
    try {
      const url=new URL(value);
      if(!['https:','http:'].includes(url.protocol)||url.username||url.password ||
         /\/storage\/v1\/object\/sign\//i.test(url.pathname) ||
         [...url.searchParams.keys()].some(k=>/token|secret|signature|authorization|api.?key|jwt/i.test(k)))return null;
      return url.href;
    } catch { return null; }
  }
  function renderEvidenceCard(source,index,selected,answer) {
    const item=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
    const card=item('article',undefined,'evidence-item'+(index===selected?' selected':''));
    const id=source.evidence_id||`Source ${index+1}`;
    card.tabIndex=-1;card.setAttribute('aria-label',id+' source passage');
    const presentation=evidencePresentation(source,answer);
    card.append(item('p',id,'evidence-id'),item('h3',source.document_title||source.organization||source.source_family||'Source record'));
    const facts=item('dl',undefined,'source-facts');
    const fact=(label,value)=>{if(!value)return;const pair=item('div');pair.append(item('dt',label),item('dd',value));facts.append(pair);};
    fact('Publisher / organisation',source.organization||source.source_family||'Not reported');
    const bounds=(start,end)=>(start||end)?`${start?String(start).slice(0,10):'Start not reported'} – ${end?String(end).slice(0,10):'End not reported'}`:'';
    const period=bounds(source.reference_period_start,source.reference_period_end);
    fact('Reference period',period||'Not reported');
    fact('Published',source.publication_date&&String(source.publication_date).slice(0,10));
    fact('Retrieved',source.retrieved_at&&String(source.retrieved_at).slice(0,10));
    if(!period)fact('Document validity',bounds(source.valid_from,source.valid_until));
    fact('Place / scope',source.geographic_scope);
    fact('Find it in the source',[source.page&&`Page ${source.page}`,source.locator||source.section].filter(Boolean).join(' · ')||'Locator not reported');
    card.append(facts);
    if(presentation.claim){const context=item('details',undefined,'answer-source-context');context.append(item('summary','Where this citation is used'),item('p','Exact excerpt from the answer; check it against the passage below.','evidence-meta'),item('blockquote',presentation.claim,'answer-claim'));card.append(context);}
    if(source.source_excerpt&&!source.content)card.append(item('p','Saved evidence snapshot from this answer; later research checks sources again.','evidence-meta'));
    if(presentation.notes.length){const note=item('div',undefined,'source-reading-note');note.append(item('strong','Hub reading note'));for(const text of presentation.notes)note.append(item('p',text));card.append(note);}
    card.append(item('h4','Source passage'));
    if(presentation.passage){const passage=item('blockquote',presentation.passage,'source-passage');passage.tabIndex=0;passage.setAttribute('aria-label',id+' supplied passage');card.append(passage);}
    else card.append(item('p','The source passage is not available here. The reference alone does not establish the answer’s claim.','evidence-meta'));
    const url=evidenceSourceURL(source.source_endpoint);
    if(url){const link=item('a','Open original source ↗','source-original-link');link.href=url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
    const details=item('details',undefined,'source-technical');details.append(item('summary','Technical details & original supplied text'));
    const provenance=item('dl',undefined,'source-facts');
    for(const[key,label]of [['source_type','Record type'],['source_family','Source family'],['version','Version'],['document_id','Document ID'],['chunk_id','Passage ID'],['release_id','Release ID'],['record_id','Record ID'],['project_id','Project ID']]){
      if(source[key]!==undefined&&source[key]!==null){const pair=item('div');pair.append(item('dt',label),item('dd',source[key]));provenance.append(pair);}
    }
    details.append(provenance,item('p','Original text supplied to this view, unchanged. It may be an excerpt rather than the complete document.','evidence-meta'));
    details.append(item('pre',presentation.original||'No passage supplied.','source-original-text'));card.append(details);
    return card;
  }
  function renderEvidence(evidence, selected, answer = '', showAll = false) {
    el['drawer-body'].replaceChildren();
    if (!evidence.length) {
      const p=document.createElement('p'); p.className='empty-evidence';
      p.textContent='No source passages are attached to this message.';
      el['drawer-body'].append(p); return;
    }
    const view = evidenceView(evidence, answer, selected, showAll);
    if (view.citedCount) {
      const controls=document.createElement('div'); controls.className='evidence-filters';
      controls.setAttribute('role','group'); controls.setAttribute('aria-label','Source view');
      for (const [all,label] of [[false,`Cited in answer (${view.citedCount})`],
                                [true,`All retrieved (${evidence.length})`]]) {
        const button=document.createElement('button'); button.type='button';
        button.className='sources-button'; button.textContent=label;
        button.setAttribute('aria-pressed',String(view.all===all));
        button.addEventListener('click',() => renderEvidence(evidence,undefined,answer,all));
        controls.append(button);
      }
      el['drawer-body'].append(controls);
      const note=document.createElement('p'); note.className='evidence-meta';
      note.textContent=view.all ? 'All retrieved records. Some are not cited in this answer.' :
        'Sources cited in this answer. Check each passage supports the claim; a citation alone does not establish it.';
      el['drawer-body'].append(note);
    }
    view.rows.forEach(({source,index}) => {
      const card=renderEvidenceCard(source,index,selected,answer);
      el['drawer-body'].append(card);
      if (index===selected) requestAnimationFrame(() => {card.scrollIntoView({block:'start'});card.focus({preventScroll:true});});
    });
    if (selected===undefined) requestAnimationFrame(() => el['drawer-body'].scrollTop=0);
  }
  async function showSources(message, selected) {
    state.sources=evidenceFor(message); state.sourcePosition=message.position;
    renderEvidence(state.sources,selected,message.content);
    el['evidence-drawer'].classList.remove('hidden');
    if (mobile()) el['drawer-scrim'].classList.remove('hidden');
    if (state.user && !isGuestThread() && message.position && state.sources.some(s => s.chunk_id && !s.content)) {
      try {
        const cid=state.selected;
        const data=await api(`conversations/${encodeURIComponent(cid)}/evidence?position=${message.position}`);
        if (state.selected!==cid || state.sourcePosition!==message.position) return;
        message.evidence_refs=data.evidence;
        state.sources=data.evidence; renderEvidence(state.sources,selected,message.content);
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
      el['topbar-export'].disabled=false;
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
        standalone_question:data.standalone_question,position:data.position,analysis_mode:mode,
        created_at:new Date().toISOString()};
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
  let authMode = 'login', authBusy = false, completedAccountLink = false;
  async function loadAdminAccess() {
    try {
      const a=await api('admin/status');state.adminAccess=a.is_admin;state.adminInvitation=!!a.pending_invitation;
      if(completedAccountLink && (state.adminAccess || state.adminInvitation))location.assign('/admin');
    } catch {state.adminAccess=false;state.adminInvitation=false;}
  }
  function setAuthStatus(message, kind='info') {
    el['auth-status'].textContent=message;
    el['auth-status'].setAttribute('data-kind',kind);
    el['auth-status'].setAttribute('role',kind==='error'?'alert':'status');
    el['auth-status'].classList.toggle('hidden',!message);
    if(message)el['auth-status'].scrollIntoView({block:'nearest'});
  }
  function setAuthMode(mode) {
    authMode = mode;
    const creating = mode === 'signup', complete = mode === 'complete', choosing = creating || mode === 'password';
    const credentials = mode === 'login' || choosing;
    for (const [id, visible] of [['auth-username',creating],['auth-email',mode !== 'password' && !complete],
        ['auth-password',credentials],['auth-confirm',choosing]]) {
      el[id+'-wrap'].classList.toggle('hidden',!visible);
      el[id].disabled = !visible; el[id].required = visible;
    }
    el['auth-password'].value = ''; el['auth-confirm'].value = '';
    el['auth-confirm'].setCustomValidity('');
    el['auth-password'].minLength = choosing ? 12 : 1;
    el['auth-password'].maxLength = choosing ? 256 : 1024;
    el['auth-password'].autocomplete = choosing ? 'new-password' : 'current-password';
    el['auth-password-help'].classList.toggle('hidden',!choosing);
    el['auth-form'].classList.toggle('hidden',complete);
    el['auth-tabs'].classList.toggle('hidden',complete);
    el['auth-links'].classList.toggle('hidden',complete);
    el['auth-complete'].classList.toggle('hidden',!complete);
    el['auth-confirm-help'].classList.toggle('hidden',mode!=='confirm');
    el['auth-progress'].classList.toggle('hidden',!creating && mode!=='confirm' && !complete);
    const step=complete?3:mode==='confirm'?2:1;
    for(let i=1;i<=3;i++)el['auth-step-'+i].setAttribute('aria-current',i===step?'step':'false');
    renderAuthRecipient();
    const titles = {login:'Sign in',signup:'Create your account',recover:'Reset your password',
      password:'Choose your password',link:'Email sign-in link',confirm:'Check your email',complete:'Your account is ready'};
    const descriptions = {
      login:'Sign in with your personal email and password to reopen your private research.',
      signup:'Choose a username and password. Verify your personal email before signing in.',
      recover:'We’ll email a reset link. Existing email-link accounts keep the same saved research.',
      password:'Set a password for your verified account. Your email and saved research stay the same.',
      link:'Use an email link for an existing account, then choose “Set / change password” in your profile.',
      confirm:'Confirm your email to finish setting up your Mali Knowledge Hub account.',
      complete:'Your email is verified and you are signed in to Mali Knowledge Hub.'};
    el['auth-title'].textContent = titles[mode]; el['auth-description'].textContent = descriptions[mode];
    el['auth-submit'].textContent = {login:'Sign in',signup:'Create account',recover:'Email password reset link',
      password:'Save password',link:'Email sign-in link',confirm:'Resend confirmation email'}[mode];
    el['auth-login'].setAttribute('aria-pressed',String(mode==='login'));
    el['auth-signup'].setAttribute('aria-pressed',String(creating));
    setAuthStatus('');
  }
  function renderAuthRecipient() {
    el['auth-recipient'].textContent=el['auth-email'].value.trim() || 'the email address you enter below';
  }
  function openAuth(mode) { setAuthMode(mode); el['auth-dialog'].showModal(); }
  async function submitAuth(event) {
    event.preventDefault(); if(authBusy)return;
    const mode = authMode;
    if ((mode==='signup' || mode==='password') && el['auth-password'].value !== el['auth-confirm'].value) {
      setAuthStatus('The passwords do not match.','error'); el['auth-confirm'].focus(); return;
    }
    const payload = mode==='password' ? {} : {email:el['auth-email'].value};
    if (mode==='login' || mode==='signup' || mode==='password') payload.password=el['auth-password'].value;
    if (mode==='signup') payload.username=el['auth-username'].value;
    authBusy=true;el['auth-submit'].disabled=true;
    setAuthStatus(mode==='signup'?'Creating your account…':mode==='confirm'?'Requesting a confirmation email…':'Please wait…');
    try {
      const data=await send('auth/'+({link:'email',confirm:'resend'}[mode] || mode),payload);
      if(data.user) {
        state.user=data.user;await loadAdminAccess();profile();el['auth-dialog'].close();
        await loadAccountThreads();renderThreads();
        toast(data.message || 'Signed in.');
      } else {
        if(mode==='signup')setAuthMode('confirm');
        setAuthStatus(data.message,'success');
      }
    } catch(err) { setAuthStatus(err.message,'error'); }
    finally {
      // Credentials never enter guest storage, history or analytics.
      el['auth-password'].value='';el['auth-confirm'].value='';delete payload.password;
      authBusy=false;el['auth-submit'].disabled=false;
    }
  }
  async function acceptAuthCallback() {
    const hash=new URLSearchParams(location.hash.slice(1));
    const hasAuth=hash.has('access_token') || hash.has('refresh_token') || hash.has('error');
    if(!hasAuth)return;
    const access_token=hash.get('access_token'),refresh_token=hash.get('refresh_token'),type=hash.get('type');
    // Scrub credentials and provider errors before any network request or rendering.
    history.replaceState(null,'',location.pathname+location.search);
    if(hash.has('error') || !access_token || !refresh_token) {
      openAuth('confirm');setAuthStatus('This account link has expired or is incomplete. Request a fresh confirmation or password reset email.','error');return;
    }
    try {
      const result=await send('auth/session',{access_token,refresh_token});state.user=result.user;
      completedAccountLink=type!=='recovery';
      if(type==='invite'){location.assign('/admin');return;}
      if(type==='recovery')openAuth('password');
      else if(type==='signup') {
        openAuth('complete');el['auth-complete-email'].textContent=state.user.email;
      } else toast('Signed in.');
    } catch(err) {openAuth('confirm');setAuthStatus(err.message,'error');}
  }
  function wire() {
    el['topbar-export'].addEventListener('click',exportDossier);
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
      if(file.size>5*1024*1024){toast('Chat accepts files up to 5 MB. Administration accepts 20 MB.');el['text-attachment'].value='';return;}
      if(el.prompt.value.length>1000){toast('Shorten the question to leave room for document excerpts.');el['text-attachment'].value='';return;}
      const button=$('plus-button'); button.disabled=true;
      const startingQuestion=el.prompt.value, startingThread=state.selected;
      try {
        toast('Reading document…');
        const response=await fetch('/api/attachments/extract',{method:'POST',credentials:'same-origin',
          headers:{'Content-Type':'application/octet-stream','X-MKH-Filename':encodeURIComponent(file.name),
            'X-MKH-Question':encodeURIComponent(el.prompt.value)},body:file});
        const data=await response.json(); if(!response.ok)throw new Error(data.error || 'The document could not be read.');
        if(state.selected!==startingThread || el.prompt.value!==startingQuestion){toast('The conversation or question changed. Attach the document again to the intended question.');return;}
        const scope=data.complete_text?'Extracted text':'Selected excerpts (not the whole document)';
        const warnings=(data.warnings || []).join(' ');
        const insertion=`\n\n${scope} from ${file.name} (user-provided context; verify facts against cited sources):\n${data.text}\n${warnings}`;
        if(el.prompt.value.length+insertion.length>5000){toast('The question and attachment must fit within 5,000 characters.');return;}
        el.prompt.value+=insertion;resizePrompt();el.prompt.focus();
        toast(data.complete_text?'Document text attached. Review before sending.':'Relevant excerpts attached; the full document is not included. Review before sending.');
      } catch(err) {toast(err.message || 'This document could not be read.');}
      finally {el['text-attachment'].value='';button.disabled=false;}
    });
    $('profile-button').addEventListener('click',()=>el['profile-menu'].classList.toggle('hidden'));
    document.addEventListener('click',e=>{
      if(!e.target.closest('.profile-menu,.profile'))el['profile-menu'].classList.add('hidden');
      if(!e.target.closest('.thread-menu,.thread-menu-button'))document.querySelectorAll('.thread-menu').forEach(m=>m.classList.add('hidden'));
    });
    el['auth-form'].addEventListener('submit',submitAuth);
    for(const mode of ['login','signup','recover'])el['auth-'+mode].addEventListener('click',()=>{if(!authBusy)setAuthMode(mode);});
    el['auth-link'].addEventListener('click',()=>{if(!authBusy)setAuthMode('link');});
    el['auth-resend'].addEventListener('click',()=>{if(!authBusy)setAuthMode('confirm');});
    el['auth-change-email'].addEventListener('click',()=>{if(!authBusy){setAuthMode('signup');el['auth-email'].focus();}});
    el['auth-email'].addEventListener('input',renderAuthRecipient);
    el['auth-continue'].addEventListener('click',()=>el['auth-dialog'].close());
    el['auth-dialog'].addEventListener('close',()=>{el['auth-password'].value='';el['auth-confirm'].value='';});
    addEventListener('resize',()=> {if(mobile())closeSidebar();});
  }
  async function init() {
    wire();loadGuest();if(mobile())closeSidebar();resizePrompt();
    await acceptAuthCallback();
    if(!state.user) {
      try {state.user=(await api('me')).user;}catch {state.user=null;}
    }
    if(state.user)await loadAdminAccess();
    profile();renderThreads();renderConversation();
    if(state.user)await loadAccountThreads();
    const requested=new URLSearchParams(location.search).get('chat');
    if(requested && conversationById(requested))await openThread(requested);
    if(new URLSearchParams(location.search).get('recover')==='1')openAuth('recover');
  }
  function conversationById(id){return [...state.threads,...state.guest].some(t=>t.id===id);}
  init();
})();
