const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(`${__dirname}/app.js`, 'utf8');
const implementation = source.slice(source.indexOf('  function evidenceView('),
                                    source.indexOf('  function renderEvidence('));
const evidenceView = new Function(`${implementation}; return evidenceView;`)();
const ledger = [{evidence_id:'E01', content:'Needs in 2025'},
                {evidence_id:'E02', content:'Funding allocation, not delivery'},
                {evidence_id:'E03', content:'Source association, not implementer'}];

test('cited view keeps original indices and unchanged source objects', () => {
  const before=JSON.stringify(ledger);
  const view=evidenceView(ledger,'Roles uncertain [E03, E01]. [E03]',undefined,false);
  assert.equal(view.citedCount,2);
  assert.equal(view.all,false);
  assert.deepEqual(view.rows.map(row=>row.index),[0,2]);
  assert.equal(view.rows[1].source,ledger[2]);
  assert.equal(JSON.stringify(ledger),before);
});
test('all retrieved remains available with original citation mapping', () => {
  const view=evidenceView(ledger,'Needs [E01]',undefined,true);
  assert.equal(view.citedCount,1);
  assert.deepEqual(view.rows.map(row=>row.index),[0,1,2]);
});
test('no citations and unavailable IDs retain the complete evidence view', () => {
  for(const answer of ['',undefined,'Unverified [E99].','Not an ID XE01Y']) {
    const view=evidenceView(ledger,answer,undefined,false);
    assert.equal(view.citedCount,0);
    assert.equal(view.rows.length,3);
    assert.equal(view.all,true);
  }
});
test('selected citation scroll target retains its original ledger index', () => {
  const view=evidenceView(ledger,'Attribution [E03]',2,false);
  assert.deepEqual(view.rows.map(row=>row.index),[2]);
  const uncited=evidenceView(ledger,'Needs [E01]',2,false);
  assert.equal(uncited.all,true);
  assert.equal(uncited.rows[2].source,ledger[2]);
});
test('empty evidence and saved references require no source facts', () => {
  assert.deepEqual(evidenceView([],'[E01]',undefined,false).rows,[]);
  const snapshot=[{evidence_id:'E03',chunk_id:42,source_excerpt:'Saved passage',
                   publication_date:'2025-03-01',locator:'Paragraph 4'}];
  assert.equal(evidenceView(snapshot,'[E03]',undefined,false).rows[0].source,snapshot[0]);
});
test('both initial and hydrated panels use the original answer for citation selection', () => {
  assert.ok(source.includes('renderEvidence(state.sources,selected,message.content);'));
  assert.equal(source.split('renderEvidence(state.sources,selected,message.content);').length-1,2);
});
