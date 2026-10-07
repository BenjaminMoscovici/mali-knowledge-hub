"""Real browser renderer: safe tables, usable citations and unchanged prose."""
import json
from pathlib import Path
import subprocess


def render(source, raw):
    start=source.index('  function markdown(')
    end=source.index('  function evidenceFor(', start)
    escaped=next(line.strip() for line in source.splitlines() if line.strip().startswith('const escaped ='))
    script=escaped+'\n'+source[start:end]+'\nconsole.log(markdown('+json.dumps(raw)+', '+json.dumps([{'evidence_id':'E01'}])+'));'
    return subprocess.check_output(['node','-e',script],text=True).strip()


def test_date_comparison_tables_escape_source_text_and_keep_direct_citation_targets():
    source=Path(__file__).with_name('web').joinpath('app.js').read_text()
    html=render(source,'| ID | Project | Source |\n|---|---|---|\n| 664 | Name \\| <img src=x onerror=alert(1)> | [E01] |\n| 32 | Another record | [E99] |')
    assert '<table>' in html and html.count('<th scope="col">')==3 and html.count('<td>')==6
    assert 'Name | &lt;img' in html and '<img' not in html
    assert 'data-source="0"' in html and 'Inspect E01' in html
    assert 'data-source="1"' not in html and '[E99]' in html


def test_existing_prose_lists_headings_and_source_buttons_render_identically():
    root=Path(__file__).parent
    source=root.joinpath('web/app.js').read_text()
    question_answer='Opening **fact** [E01].\n\n### What the evidence shows\n- Reported end date in 2026 [E01].\n- No delivery proof [E99].\n\nUncertainty <script>text</script>.'
    expected='<p>Opening <strong>fact</strong> [<button class="citation" data-source="0" title="Inspect E01">E01</button>].</p><h3>What the evidence shows</h3><ul><li>Reported end date in 2026 [<button class="citation" data-source="0" title="Inspect E01">E01</button>].</li><li>No delivery proof [E99].</li></ul><p>Uncertainty &lt;script&gt;text&lt;/script&gt;.</p>'
    assert render(source,question_answer)==expected
