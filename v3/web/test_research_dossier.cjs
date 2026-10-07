const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');
const source=fs.readFileSync(`${__dirname}/app.js`,'utf8');
const helpers=source.slice(source.indexOf('  function evidenceFor('),source.indexOf('  function exportDossier('));
const {dossier,brief}=new Function(`${helpers}; return {dossier:researchDossier,brief:researchBrief};`)();
const first={role:'assistant',content:'Reported funding is USD 12.50 [E01].',created_at:'2026-09-01',
  evidence:[{evidence_id:'E01',document_title:'Funding record',locator:'Row 2',reference_period_start:'2026-01-01'},
            {evidence_id:'E02',document_title:'Uncited source'}]};
const second={role:'assistant',content:'Local needs remain uncertain [E01].',standalone_question:'Compare local needs in Gao.',
  evidence_refs:[{evidence_id:'E01',document_title:'Different local-needs record',locator:'Row 7',reference_period_start:'2025-01-01'}]};

test('dossier preserves chronology, exact answers, follow-up scopes and turn-local evidence IDs',()=>{
  const messages=[{role:'user',content:'What funding is reported?'},first,{role:'user',content:'And in Gao?'},second];
  const before=JSON.stringify(messages);const result=dossier(messages,'Funding research','2026-10-07');
  assert.ok(result.indexOf('## Research turn 1')<result.indexOf('## Research turn 2'));
  for(const value of [first.content,second.content,'> And in Gao?',second.standalone_question,'Row 2','Row 7',
      '2026-01-01','2025-01-01','same ID in another turn may refer to a different source']) assert.ok(result.includes(value));
  assert.equal(result.split('#### E01').length-1,2);
  assert.ok(!result.includes('Uncited source'));assert.equal(JSON.stringify(messages),before);
});
test('open questions and unresolved citations remain explicit without invented answers or dates',()=>{
  const result=dossier([{role:'system',content:'Internal information'},
      {role:'assistant',content:'Unverified [E99].'},{role:'user',content:'Which evidence would settle this?'}],
      'Title\n# fake heading','2026-10-07');
  assert.ok(result.includes('Unresolved citation identifiers in this saved answer: E99'));
  assert.ok(result.includes('Question unavailable in this saved turn.'));
  assert.ok(result.includes('## Open research question\n\n> Which evidence would settle this?'));
  assert.ok(result.includes('No answer is recorded for this question.'));
  assert.ok(!result.includes('Internal information'));assert.ok(!result.includes('Answer recorded:'));
  assert.ok(!result.includes('\n# fake heading'));
});
test('existing single-answer brief output stays byte-identical to accepted implementation',()=>{
  const prior=execFileSync('git',['show','ddccf33a89aafc3c3a52a72b8dcde42d0352da2d:v3/web/app.js'],{cwd:__dirname,encoding:'utf8'});
  const helper=prior.slice(prior.indexOf('  function evidenceFor('),prior.indexOf('  function exportBrief('));
  const original=new Function(`${helper};return researchBrief;`)();
  assert.equal(brief(first,'What funding is reported?','2026-10-07'),original(first,'What funding is reported?','2026-10-07'));
});
test('dossier download uses only the current conversation and does not write to accounts',()=>{
  const flow=source.slice(source.indexOf('  function exportDossier('),source.indexOf('  function exportBrief('));
  assert.ok(flow.includes('if(state.busy)return;'));
  assert.ok(flow.includes('researchDossier(state.messages,conversation()?.title,exportedAt)'));
  assert.ok(flow.includes("type:'text/markdown;charset=utf-8'"));assert.ok(flow.includes('URL.revokeObjectURL(url)'));
  assert.ok(!flow.includes('send('));assert.ok(!flow.includes('api('));
  assert.ok(source.includes("el['topbar-export'].addEventListener('click',exportDossier)"));
});
