"""Freeze realistic conversation sequences before continuity optimization."""
from pathlib import Path
from .common import digest, now, write_json


def build():
    cases = []
    def add(cid, category, turns, expected, language='en'):
        cases.append({'id': cid, 'category': category, 'language': language,
                      'difficulty': 'balanced', 'turns': turns,
                      'followup_expectations': expected})
    def exp(patterns=(), numbers=(), clarify=False, evidence=True):
        return {'intent_patterns': list(patterns), 'answer_numbers': list(numbers),
                'clarification_required': clarify, 'grounded_answer_required': evidence}
    add('C01', 'geography_metric', ['How many municipalities are in Mali?', 'And in Gao?'],
        [exp(['commune|municipalit', 'gao'], [44])])
    add('C02', 'geography_metric', ['Combien de communes compte le Mali ?', 'Et à Mopti ?'],
        [exp(['commune', 'mopti'], [50])], 'fr')
    add('C03', 'geography_metric', ['How many cercles are in Mali?', 'And in Gao?', 'And in Mopti?'],
        [exp(['cercle', 'gao'], [16]), exp(['cercle', 'mopti'], [8])])
    add('C04', 'administrative_level', ['How many communes are in Gao cercle?', 'And in Ansongo?'],
        [exp(['commune', 'cercle', 'ansongo'], [4])])
    add('C05', 'geography_path', ['What is the parent hierarchy of Socoura commune?', 'And Konna?'],
        [exp(['parent|hierarch|path', 'commune', 'konna'])])
    add('C06', 'sex_level', ['What is the 2023 population projection for Bandiagara region?', 'What about women?', 'And at cercle level?'],
        [exp(['population|projection', 'bandiagara', '2023', 'women|female'], [636934]),
         exp(['population|projection', 'bandiagara', 'cercle', 'women|female'], [115511])])
    add('C07', 'sex_geography', ['Quelle est la population projetée de la région de Mopti en 2023 ?', 'Et à Gao ?', 'Et les hommes ?'],
        [exp(['population', 'gao', '2023'], [827614]), exp(['population', 'gao', 'hommes|male'], [425177])], 'fr')
    add('C08', 'needs_geography', ['What intersectoral people-in-need observations are available for Mopti in OCHA HAPI?', 'Same for Gao?'],
        [exp(['gao', 'hapi|ocha', 'intersectoral|people.in.need|needs'])])
    add('C09', 'category_period', ['What IDP stock does DTM Round 83 September 2025 report for Socoura?', 'What about returned IDPs?'],
        [exp(['socoura', 'dtm', '2025|83', 'return'])])
    add('C10', 'period_geography', ['What does the June–August 2026 Cadre Harmonise projection show for Mopti?', 'And Gao for the same period?'],
        [exp(['gao', 'harmoni', '2026', 'project|projection'])])
    add('C11', 'period_change', ['How much funding does FTS report for Mali in 2026?', 'And in 2025?'],
        [exp(['fts', 'fund|financ', '2025'])])
    add('C12', 'entity_pronoun', ['What did the IEG evaluation find for World Bank project P144442?', 'What constraints did it face?'],
        [exp(['p144442', 'constraint|limitation|obstacle'])])
    add('C13', 'entity_pronoun', ['Que prévoit la SNEDD 2024–2033 pour les services de base ?', 'Quelles sont ses limites comme preuve de résultats ?'],
        [exp(['snedd', 'result|preuve|evidence'])], 'fr')
    add('C14', 'entity_pronoun', ['What does the EIB Kabala drinking-water project record establish?', 'When was it signed?'],
        [exp(['kabala|eib', 'sign|signature'])])
    add('C15', 'status_subset', ['Which FONGIM projects are recorded in Mopti?', 'Which of those are still active?'],
        [exp(['fongim', 'mopti', 'active|cours'])])
    add('C16', 'status_dates', ['Quels projets FONGIM sont enregistrés à Mopti ?', 'Lesquels ont une date de fin dépassée mais restent en cours ?'],
        [exp(['fongim', 'mopti', 'fin|end', 'cours|active'])], 'fr')
    add('C17', 'topic_after_social_turn', ['How many communes are in Mali?', 'Thanks!', 'And in Gao?'],
        [exp([], [], evidence=False), exp(['commune', 'gao'], [44])])
    add('C18', 'topic_reset', ['How many communes are in Gao region?', 'What IDP stocks does DTM report for Socoura in September 2025?', 'What about women?'],
        [exp(['dtm', 'socoura']), exp(['dtm', 'socoura', 'women|female'])])
    add('C19', 'unverified_prior_claim', ['How many cercles are in Mali?', 'Are all 999 of them funded by the EU?'],
        [exp(['eu', 'cercle|999'])])
    add('C20', 'no_prior_place', ['Hello', 'How many communes are there?'],
        [exp([], [], clarify=True, evidence=False)])
    add('C21', 'multiple_places', ['Compare the populations of Gao region and Mopti region in 2023.', 'And how many communes are there?'],
        [exp([], [], clarify=True, evidence=False)])
    add('C22', 'ambiguous_metric', ['Compare Mali’s 2026 funding requirement, reported funding and people targeted.', 'How much was that?'],
        [exp([], [], clarify=True, evidence=False)])
    add('C23', 'multiple_entities', ['Compare the World Bank P144442 evaluation and the EIB Kabala project record.', 'When did it end?'],
        [exp([], [], clarify=True, evidence=False)])
    add('C24', 'sex_without_indicator', ['Which organisations are present in Mopti in OCHA 3W?', 'What about women?'],
        [exp([], [], clarify=True, evidence=False)])
    return cases


if __name__ == '__main__':
    root = Path(__file__).parent / 'benchmarks'
    target = root / 'conversation_v1.json'
    if target.exists():
        raise SystemExit('Conversation benchmark already frozen; create a versioned successor.')
    cases = build()
    write_json(target, {'version': 'conversation-v1', 'sequences': cases,
                       'method': 'Actual multi-turn guest exchanges; oracle expectations remain evaluator-only.'})
    write_json(root / 'conversation_freeze_manifest.json', {
        'frozen_at': now(), 'suite_sha256': digest(__import__('json').loads(target.read_text())),
        'sequences': len(cases), 'turns': sum(len(c['turns']) for c in cases),
        'baseline_hub_commit': 'ccd77fed567574b4b1319677a1a1c461fa8f130c',
        'oracle': 'Existing INSTAT versioned hierarchy and original population observation rows; reference2023, not current2026 population.'})
    print('Frozen', len(cases), 'sequences')
