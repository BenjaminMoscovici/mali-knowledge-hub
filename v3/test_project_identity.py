from project_identity import preserve_project_identifiers
from conversation_state import resolve, referenced_fongim_ids


def evidence(rows):
    return [{'evidence_id':'E07','source_family':'FONGIM intervention data',
             'project_referents':[{'project_id':i,'project_name':name} for i,name in rows]}]


def test_names_without_ids_support_bounded_followup_without_carrying_status_facts():
    ledger=evidence([(461,' KELEN-YA de Union Européenne'),(715,'AGRO Ecologie ( Appui à la transition agroécologique )'),
                     (99,'ANW KA TA ! : Les maîtres coraniques')])
    answer='- **KELEN-YA de Union Européenne** — closed. [E07]\n- **AGRO Ecologie** — ongoing since 2099. [E07]\n- **ANW KA TA!** — closed. [E07]'
    identified=preserve_project_identifiers(answer,ledger)
    prior=[{'role':'user','content':'Which FONGIM projects are recorded in Mopti?'},
           {'role':'assistant','content':identified}]
    result=resolve('Which of those are still active?',prior)
    assert referenced_fongim_ids(result['standalone_question'])==(461,715,99)
    assert not result['clarification_required'] and not result['needs_model']
    assert '2099' not in result['standalone_question'] and 'closed' not in result['standalone_question']
    assert preserve_project_identifiers(identified,ledger)==identified


def test_exact_table_and_ellipsized_titles_keep_source_id_and_skip_ambiguous_names():
    ledger=evidence([(113,'Diversification des systèmes de production agricole pour la sécurité alimentaire'),
                     (118,'ALBARKA'),(5,'AGRO Ecologie un'),(6,'AGRO Ecologie deux')])
    text='| Project | Status |\n|---|---|\n| Diversification des systèmes de production agricole… | Closed |\n| ALBARKA | Closed |\n\n- **AGRO Ecologie** — ongoing.'
    result=preserve_project_identifiers(text,ledger)
    assert '(project ID 113) [E07]' in result and '(project ID 118) [E07]' in result
    assert 'project ID 5' not in result and 'project ID 6' not in result
    assert preserve_project_identifiers('- **Unknown project** — active.',ledger)=='- **Unknown project** — active.'
    assert preserve_project_identifiers('- **ALBARKA** (ID 999) — active.',ledger)=='- **ALBARKA** (ID 999) — active.'
    unrelated=evidence([(118,'ALBARKA')]);unrelated[0]['source_family']='Unrelated material'
    assert preserve_project_identifiers('- **ALBARKA** — active.',unrelated)=='- **ALBARKA** — active.'


def test_project_specific_heading_requires_fresh_source_identity_not_user_claim():
    ledger=[{'evidence_id':'E21','source_family':'IEG project evaluation',
             'content':'Initial IEG review for project P144442, covering 2013–2022.'}]
    answer='The historical review reports results and implementation constraints. [E21]'
    identified=preserve_project_identifiers(answer,ledger,'What did IEG find for P144442?')
    assert identified.startswith('**Project: P144442 [E21]**')
    assert preserve_project_identifiers(identified,ledger,'What did IEG find for P144442?')==identified
    assert preserve_project_identifiers(answer,ledger,'What did IEG find for P99999?')==answer
    assert preserve_project_identifiers(answer,[],'What did IEG find for P144442?')==answer
