const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync(`${__dirname}/app.js`,'utf8');
const implementation=source.slice(source.indexOf('  function evidenceFor('),source.indexOf('  function exportBrief('));
const brief=new Function(`${implementation}; return researchBrief;`)();
const message={role:'assistant',content:'Needs remain uncertain [E03]. Funding is reported [E01, E03].',
  standalone_question:'Compare funding and needs in Mopti in 2026.',created_at:'2026-10-01T10:00:00Z',
  evidence:[{evidence_id:'E01',document_title:'National funding',organization:'Publisher',
    reference_period_start:'2026-01-01',reference_period_end:'2026-12-31',retrieved_at:'2026-10-01',
    geographic_scope:'Mali nationally',locator:'Table 2, row 3',page:4,source_endpoint:'https://example.org/report'},
    {evidence_id:'E02',document_title:'Uncited unrelated evidence',content:'Do not export this'},
    {evidence_id:'E03',document_title:'Local needs',publication_date:'2025-11-01',
     geographic_scope:'Older source boundaries',locator:'Exact aggregate row'}]};

test('brief preserves question, resolved scope, answer and exact cited reference identity',()=>{
  const before=JSON.stringify(message);const result=brief(message,'And in Mopti?','2026-10-07T12:00:00Z');
  for(const value of ['> And in Mopti?',message.standalone_question,message.content,
      '### E01 — National funding','### E03 — Local needs','Table 2, row 3','Page: 4',
      '2026-01-01 – 2026-12-31','2025-11-01','Older source boundaries','https://example.org/report']) assert.ok(result.includes(value));
  assert.ok(!result.includes('Uncited unrelated evidence'));assert.ok(!result.includes('Do not export this'));
  assert.equal(result.split('### E03').length-1,1);assert.equal(JSON.stringify(message),before);
  assert.ok(result.includes('Answer recorded: 2026-10-01T10:00:00Z'));
  assert.ok(result.includes('exporting does not refresh the evidence'));
});
test('saved references work without full source content or an invented answer date',()=>{
  const result=brief({content:'Known caveat [E02]',evidence_refs:[{evidence_id:'E02',document_title:'Saved reference',
    source_excerpt:'Saved passage',locator:'Original locator',retrieved_at:'2025-02-01'}]},'Question','2026-10-07');
  assert.ok(result.includes('Saved reference'));assert.ok(result.includes('Original locator'));
  assert.ok(!result.includes('Answer recorded:'));assert.ok(!result.includes('Saved passage'));
});
test('missing citations are identified rather than substituted with another source',()=>{
  const result=brief({content:'Check [E99].',evidence:message.evidence},'Question','2026-10-07');
  assert.ok(result.includes('Unresolved citation identifiers in this saved answer: E99'));
  assert.ok(!result.includes('### E01'));assert.ok(result.includes('No cited source references'));
});
test('source metadata cannot add headings or unsafe link schemes',()=>{
  const result=brief({content:'Record [E01]',evidence:[{evidence_id:'E01',document_title:'[click](javascript:alert)\n# invented',
    source_endpoint:'javascript:alert(1)',locator:'<script>unsafe</script>'}]},'Question','2026-10-07');
  assert.ok(result.includes('\\[click\\]'));assert.ok(!result.includes('\n# invented'));
  assert.ok(!result.includes('- Original source: javascript'));assert.ok(result.includes('\\<script\\>'));
});
test('each assistant turn exports its preceding question without account writes',()=>{
  assert.ok(source.includes("state.messages.slice(0,index).reverse().find(turn=>turn.role==='user')?.content"));
  const flow=source.slice(source.indexOf('  function exportBrief('),source.indexOf('  function renderConversation('));
  assert.ok(flow.includes("type:'text/markdown;charset=utf-8'"));
  assert.ok(flow.includes('URL.revokeObjectURL(url)'));assert.ok(!flow.includes('send('));assert.ok(!flow.includes('api('));
  assert.ok(source.includes("exportButton.addEventListener('click',()=>exportBrief(message))"));
});
