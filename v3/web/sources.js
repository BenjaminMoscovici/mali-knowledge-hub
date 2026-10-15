'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const labels = {loaded:'Loaded dataset', indexed:'Indexed document', connected:'Connected · integration record', pending:'Awaiting evidence or review'};
  let data = null;
  const el = (tag, text, cls) => {const node=document.createElement(tag); if(text!==undefined) node.textContent=String(text); if(cls) node.className=cls; return node;};
  const date = value => {if(!value) return 'Not reported'; const d=new Date(value); return Number.isNaN(d.getTime())?'Not reported':d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});};
  const safeURL = value => {try {const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&!u.search&&!u.hash&&!u.pathname.includes('/storage/v1/')&&!/\.supabase\.(co|in)$/.test(u.hostname)?u.href:null;} catch{return null;}};
  const matches = (row, query, state) => (state==='all'||row.state===state) && [row.title,row.provider,row.use,row.period,row.publication_date,...(row.limitations||[])].join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  function fact(list, label, value) {const group=el('div');group.append(el('dt',label),el('dd',value||'Not reported'));list.append(group);}
  function card(row) {
    const article=el('article',undefined,'source-card'), top=el('div',undefined,'card-top');
    top.append(el('span',labels[row.state]||'Coverage not verified','badge '+row.state));
    article.append(top,el('p',row.provider,'publisher'),el('h3',row.title));
    if(row.use) article.append(el('p',row.use.replaceAll('_',' '),'use'));
    const facts=el('dl',undefined,'facts');
    if(row.kind==='document') {
      fact(facts,'Published',date(row.publication_date));fact(facts,'Added to Hub',date(row.added_at));
      fact(facts,'Reference / validity period',row.valid_from||row.valid_until?`${date(row.valid_from)} → ${date(row.valid_until)}`:'Not reported');
      fact(facts,'Document type',row.document_type?row.document_type.replaceAll('_',' '):null);
    } else {
      fact(facts,'Reference period',row.period);fact(facts,'Last recorded retrieval',date(row.retrieved_at));
      fact(facts,'Evidence records',Number.isInteger(row.records)?row.records.toLocaleString('en-GB'):'Not verified on this page');
      fact(facts,'Reported update frequency',row.update_frequency);
    }
    article.append(facts);
    const details=el('details',undefined,'limits');
    details.append(el('summary',row.kind==='document'?'Coverage & date notes':`Known limits${row.limitations?.length?' · '+row.limitations.length:''}`));
    const list=el('ul');
    const notes=row.kind==='document'?['Indexed text is available for retrieval; this does not guarantee an answer to every question.','“Added to Hub” is the document record date, not a provider update or publication date.','Document metadata may be incomplete. Check the original and the citations.']:(row.limitations?.length?row.limitations:['No additional limitations recorded. This is not evidence of unrestricted coverage.']);
    for(const note of notes) list.append(el('li',note));
    if(row.state==='pending') list.append(el('li','Catalogue status: '+row.status+'. No usable evidence confirmed here.'));
    if(row.state==='connected') list.append(el('li','Integration is recorded; this page has not run a live connector freshness check.'));
    details.append(list);article.append(details);
    const foot=el('div',undefined,'card-footer'), url=safeURL(row.url);
    if(url){const link=el('a','Visit original source ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';foot.append(link);} else foot.append(el('span','No public source link listed'));
    article.append(foot);return article;
  }
  function render() {
    if(!data) return;
    const all=[...data.datasets,...data.documents], shown=all.filter(r=>matches(r,$('source-search').value,$('source-filter').value));
    $('source-list').replaceChildren(...shown.map(card));
    if(!shown.length) $('source-list').append(el('p','No matching sources. Try another search or select All sources.','empty'));
    const checked=data.documents_checked_at?` Document index checked ${date(data.documents_checked_at)} at ${new Date(data.documents_checked_at).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'})} UTC; refreshes may reuse a check for up to 60 seconds.`:'';
    $('catalogue-status').textContent=`${shown.length} of ${all.length} listed sources${data.catalogue_available&&data.documents_available?'':'; catalogue incomplete'}.${checked}`;
    for(const [state,id,available] of [['loaded','loaded-count',data.catalogue_available],['connected','connected-count',data.catalogue_available],['pending','pending-count',data.catalogue_available],['indexed','document-count',data.documents_available]]) $(id).textContent=available?String(all.filter(r=>r.state===state).length):'—';
  }
  async function load() {
    $('refresh').disabled=true;$('source-list').setAttribute('aria-busy','true');$('catalogue-status').textContent='Checking the source catalogue…';
    data=null;$('source-list').replaceChildren();$('warnings').replaceChildren();
    for(const id of ['loaded-count','connected-count','pending-count','document-count']) $(id).textContent='—';
    try {
      const response=await fetch('/api/sources',{credentials:'omit',cache:'no-store',signal:AbortSignal.timeout(30000)});
      if(!response.ok) throw Error('Unavailable'); const value=await response.json();
      if(!Array.isArray(value.datasets)||!Array.isArray(value.documents)) throw Error('Invalid catalogue');
      data=value;
      if(!data.catalogue_available) $('warnings').append(el('p','The dataset catalogue could not be checked. Its contents and counts are unknown. Use Refresh catalogue to retry.','warning'));
      if(!data.documents_available) $('warnings').append(el('p','The document index could not be checked. This does not mean the Hub has no documents. Use Refresh catalogue to retry.','warning'));
      render();
    } catch { $('catalogue-status').textContent='The catalogue could not be loaded.';$('warnings').append(el('p','Please try Refresh catalogue. Source coverage is unknown until the check succeeds.','warning')); }
    finally { $('refresh').disabled=false;$('source-list').setAttribute('aria-busy','false'); }
  }
  $('source-search').addEventListener('input',render);$('source-filter').addEventListener('change',render);$('refresh').addEventListener('click',load);
  load();
})();
