"""One-time, pre-baseline construction. Frozen manifests prevent later silent edits."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evaluation' / 'benchmarks'
DIMENSIONS = ['question_answering','evidence_completeness','cross_source_synthesis',
 'inference_discipline','evidence_gap_handling','geographic_discipline',
 'temporal_discipline','decision_usefulness','writing_quality']
FAMILY = {'government_documents':'government','humanitarian_document':'hnrp',
 'hdx_hapi':'hapi','fongim':'fongim'}
CATEGORY = {}
for cat,ids in {
 'geography_population':'G01 J02 J08 J12',
 'humanitarian_needs':'D04 H01 H02',
 'actors_projects':'F01 F02 G02 I01 J05 J07 J09',
 'plans_priorities':'D01 D02 D03 M01 M02 T01 J04 J06',
 'joined_analysis':'X01 X02 J01 J03 J10 J11',
 'adversarial':'A01 S01 J13'}.items():
 for identifier in ids.split(): CATEGORY[identifier]=cat

def make(identifier,q,category,families=(),mode='balanced',language='en',expected=(),
         assertions=(),tags=(),prior=(),legacy=None):
 return {'id':identifier,'question':q,'language':language,'category':category,
  'difficulty':mode,'required_source_families':list(families),
  'known_traps':list(expected),'expected_behavior':list(expected),
  'deterministic_assertions':list(assertions),'tags':list(dict.fromkeys(
   [category]+list(tags)+(['French'] if language=='fr' else []))),
  'evaluator_rubric':DIMENSIONS,'prior_messages':list(prior),
  'legacy_reference':legacy,'status':'frozen'}

def pattern(identifier,p,dimension='evidence_gap_handling',negative=False):
 return {'id':identifier,'type':'answer_regex','pattern':p,'negative':negative,
         'dimension':dimension,'severity':'major',
         'interpretation':'Required explicit behavior/phrase signal; not a proof of semantic entailment.'}

def number(identifier,value,family,scope=None):
 return {'id':identifier,'type':'source_number','value':value,'family':family,
         'scope':scope,'dimension':'factual_grounding','severity':'major'}

def route(*paths):return {'id':'route','type':'route','allowed':list(paths),
 'dimension':'routing','severity':'major'}

def no_calls():return {'id':'no_research','type':'zero_calls',
 'dimension':'routing','severity':'major'}

if (OUT/'freeze_manifest.json').exists():
 raise SystemExit('Already frozen. Add a documented version; never regenerate in place.')

frozen=[];held=[]
for filename in ['benchmark_v1_frozen.json','benchmark_v2_frozen.json']:
 obj=json.loads((ROOT/filename).read_text())
 for old in obj['cases']:
  french=old['id'] in {'D01','D03','J11'}
  checks=old['checks']; mode='deep' if old['id'] in {'X01','X02','J01','J03','J10','J11','J14','J18','X03'} else 'balanced'
  families=[FAMILY[x] for x in old.get('sources',[])]
  # V2 legacy files predate an explicit family field; preserve question/checks.
  if filename.startswith('benchmark_v2'):
   families=(['government','hapi','fongim'] if old['id'] in {'J01','J03','J10','J11','J14','J18'} else
    ['hapi','fongim'] if old['id']=='J02' else ['government'] if old['id'] in {'J04','J06','J13','J16'} else
    ['fongim'] if old['id'] in {'J05','J07','J09','J12','J15','J17'} else [])
  case=make('LEGACY-'+old['id'],old['question'],CATEGORY.get(old['id'],'adversarial'),families,mode,
    'fr' if french else 'en',checks,tags=['legacy'],legacy={'file':filename,'id':old['id'],'original_checks':checks})
  if old['split']=='heldout':case['status']='held-out';held.append(case)
  else:frozen.append(case)

ROWS=[
 ('GEO01','How is Mali administratively structured, and how many regions, cercles and communes are there?','geography_population',['geography'],'quick','en',['19 regions plus Bamako district; INSTAT 159 cercles/815 communes; COD admin2 is a separate representation'],[route('simple_geography'),no_calls(),pattern('hierarchy',r'159.*cercles')]),
 ('GEO02','Quelles communes appartiennent au cercle de Mopti ?','geography_population',['geography'],'quick','fr',['Twelve communes; administrative level and edition stated'],[route('simple_geography'),no_calls(),pattern('communes',r'12')]),
 ('GEO03','What is the full administrative path for Socoura commune?','geography_population',['geography'],'quick','en',['Mali → Mopti region → Mopti cercle → Socoura commune'],[route('simple_geography'),no_calls(),pattern('socoura',r'SOCOURA', 'geographic_discipline')]),
 ('GEO04','Are the two Bamba communes the same entity?','geography_population',['geography'],'quick','en',['Distinct commune identities under Bandiagara/Koro and Gao/Bamba'],[route('simple_geography'),no_calls(),pattern('distinct',r'distinct|different','geographic_discipline')]),
 ('GEO05','Quelle population projetée en 2023 est documentée pour Bandiagara aux niveaux région, cercle et commune ?','geography_population',['geography'],'balanced','fr',['Keep three scopes distinct: 1270224,230093,30916; historical projection, not today'],[number('region',1270224,'geography','region'),number('cercle',230093,'geography','cercle'),number('commune',30916,'geography','commune')]),
 ('GEO06','What population projection is reported for Mopti region in 2023, and can it describe the population today?','geography_population',['geography'],'balanced','en',['1087526 DNP projection for 2023; cannot assert current population'],[number('population',1087526,'geography','region'),pattern('historical',r'2023','temporal_discipline')]),
 ('GEO07','Quelle est la population de Bolibana, sans autre précision géographique ?','geography_population',['geography'],'quick','fr',['Ambiguous locality; request parent/commune; no single invented total'],[pattern('ambiguity',r'ambig|précis|precis|plusieurs','geographic_discipline')]),
 ('GEO08','Why does COD show 160 admin2 records while the INSTAT hierarchy contains 159 cercles?','geography_population',['geography'],'quick','en',['Bamako representation; no invented extra cercle'],[pattern('bamako',r'Bamako','geographic_discipline')]),
 ('GEO09','Les projections DNP de 2023 permettent-elles de connaître la population actuelle de Mopti en octobre 2026 ?','geography_population',['geography'],'balanced','fr',['Projection reference date differs from publication and retrieval; current count unknown'],[pattern('projection',r'projection','temporal_discipline')]),
 ('GEO10','What is the hierarchy of Unknownville commune?','geography_population',['geography'],'quick','en',['No exact match; do not substitute national counts'],[route('simple_geography'),no_calls(),pattern('not_found',r'No exact match|not found|cannot find','geographic_discipline')]),
 ('GEO11','Peut-on fusionner automatiquement les communes INSTAT et les observations COD, HAPI et DTM malgré les différences de découpage ?','geography_population',['geography'],'balanced','fr',['Proposed crosswalks are not approved; no silent cross-version joins'],[pattern('crosswalk',r'non|pas|propos|approuv|valid','geographic_discipline')]),
 ('NEED01','What are the national people-in-need and targeted figures in the stored OCHA HPC HNO 2026 snapshot?','humanitarian_needs',['hpc'],'quick','en',['5100000 PiN and 3800000 targeted; national scope'],[number('pin',5100000,'hpc'),number('target',3800000,'hpc')]),
 ('NEED02','Combien de personnes ont été atteintes selon le snapshot OCHA HPC HNO 2026 ? Une valeur manquante veut-elle dire zéro ?','humanitarian_needs',['hpc'],'balanced','fr',['Reached not reported; missing is not zero'],[pattern('missing',r'non renseign|pas.*renseign|manquan|non.*dispon|ne.*pas.*zéro|ne.*pas.*zero')]),
 ('NEED03','Quels stocks de personnes déplacées internes sont documentés pour Mopti et Socoura dans le DTM de septembre 2025 ?','humanitarian_needs',['dtm'],'balanced','fr',['13582 Mopti,13002 Socoura; stock, dated September 2025; no fresh 2026 count'],[number('mopti',13582,'dtm'),number('socoura',13002,'dtm'),pattern('date',r'2025','temporal_discipline')]),
 ('NEED04','Can returned IDPs in Youwarou and repatriated persons in Haire be added to Mopti IDPs to estimate new displacement?','humanitarian_needs',['dtm'],'balanced','en',['Distinct categories and scopes; stocks not flows; no sum'],[pattern('stock_flow',r'stock|flow|not.*add|cannot.*add','inference_discipline')]),
 ('NEED05','Les classifications du Cadre Harmonisé et les projections juin–août 2026 représentent-elles une observation actuelle de la situation à Mopti ?','humanitarian_needs',['ch'],'balanced','fr',['Late-2025 exercise versus projected2026; older geographic framework'],[pattern('projection',r'projet|projection','temporal_discipline')]),
 ('NEED06','How does a Cadre Harmonise area classification differ from the population estimated in Phase 3 or worse?','humanitarian_needs',['ch'],'balanced','en',['Area phase vs population phase distribution; preserve denominator; CH not IPC'],[pattern('phase',r'population|people','inference_discipline')]),
 ('NEED07','La valeur HAPI de 249 711 personnes en besoin de sécurité alimentaire à Konna est-elle un total régional pour Mopti ?','humanitarian_needs',['hapi'],'balanced','fr',['Konna Admin2 observation, not regional sum; no downscaling'],[pattern('scope',r'Konna|admin.?2','geographic_discipline')]),
 ('ACT01','For Mopti, how many Q1 2026 OCHA 3W food-security presence rows and distinct actor labels are recorded?','actors_projects',['3w'],'balanced','en',['30 rows,11labels; rows not projects/beneficiaries'],[number('rows',30,'3w'),number('actors',11,'3w')]),
 ('ACT02','Les données OCHA 3W prouvent-elles que toutes les personnes en besoin à Mopti ont reçu une assistance alimentaire ?','actors_projects',['3w','hapi'],'balanced','fr',['Presence not delivery/coverage; targets/reached fields empty'],[pattern('presence',r'présence|presence','inference_discipline')]),
 ('ACT03','What does the EU INTPA/ECHO IATI activity subset for Mali contain, and is it the complete current EU project portfolio?','actors_projects',['eu'],'balanced','en',['134 INTPA+172ECHO=306 country activities; subset/historical statuses, no complete portfolio'],[pattern('subset',r'subset|partial|incomplete|not.*complete|bounded')]),
 ('PLAN01','What do the EU joint-programming and NDICI 2021–2027 documents establish about Mali priorities and implementation?','plans_priorities',['eu'],'balanced','en',['Programming intent; distinguish from execution/results'],[pattern('programme_period',r'2021|2027','temporal_discipline')]),
 ('PLAN02','Quelles priorités pour le Mali sont documentées dans le HIP ECHO 2026 et comment diffèrent-elles des résultats déjà obtenus ?','plans_priorities',['eu'],'balanced','fr',['Indicative planning/priorities not reported results'],[pattern('planning',r'priorit|indicati|planifi','inference_discipline')]),
 ('FUND01','Compare Mali 2026 FTS requirements, reported funding and percentage funded, with the snapshot date and units.','funding_timelines',['fts'],'balanced','en',['National requirements vs reported funding; retrieve date; no local disbursement'],[pattern('funding_scope',r'national|country','geographic_discipline')]),
 ('FUND02','Le financement déclaré à FTS correspond-il nécessairement à des décaissements ou à une aide effectivement livrée ?','funding_timelines',['fts'],'balanced','fr',['Requirement/funding/commitment/disbursement/service delivery distinct'],[pattern('disbursement',r'décaisse|decaisse|livr','inference_discipline')]),
 ('FUND03','How much of the national 2026 FTS reported funding was actually delivered to Mopti communes?','funding_timelines',['fts'],'balanced','en',['National aggregate cannot allocate local funding or delivery'],[pattern('gap',r'cannot|not.*establish|not.*available|unknown|not.*reported')]),
 ('FUND04','Quelles interventions FONGIM à Mopti arrivent à échéance dans les 180 prochains jours ? Donne les exemples nommés disponibles, leurs secteurs et dates, et distingue-les du nombre total.','funding_timelines',['fongim'],'deep','fr',['Available five individually dated examples; six upcoming as 4Oct; rolling as-of dates; partial roster != no examples; no broad-sector attribution'],[pattern('examples',r'664|SARES|SA[ -]?RES','evidence_completeness'),pattern('dated_examples',r'2026|2027','temporal_discipline')]),
 ('FUND05','Quels enregistrements FONGIM à Mopti ont un statut actif malgré une date de fin déjà passée ? Que peut-on conclure réellement ?','funding_timelines',['fongim'],'balanced','fr',['Registry status/date conflicts; not verified ongoing implementation'],[pattern('status_conflict',r'statut|date','temporal_discipline')]),
 ('FUND06','Distinguish the EUR151 million committed for Mali in 2021–2024 from the EUR373 million indicative EU programming envelope. Can either be allocated to Mopti?','funding_timelines',['eu'],'deep','en',['151commitment vs373indicative; differentperiods; noMoptiallocation'],[number('commitment',151,'eu'),number('indicative',373,'eu')]),
 ('FUND07','What does the ECHO HIP 2026 Mali indicative allocation establish, including its components, and what does it not show?','funding_timelines',['eu'],'balanced','en',['EUR32m indicative composed30+2; not disbursement/results'],[number('allocation',32,'eu'),pattern('indicative',r'indicative','inference_discipline')]),
 ('FUND08','Do raw World Bank project financial API fields provide verified amounts disbursed in Mopti?','funding_timelines',['world_bank'],'balanced','en',['Raw field units unvalidated; no local disbursements'],[pattern('units',r'unit|unvalidated|not.*validat|cannot.*establish')]),
 ('FUND09','Peut-on additionner les montants répétés sur les lignes sectorielles IATI pour calculer le financement total des projets Banque mondiale au Mali ?','funding_timelines',['iati'],'deep','fr',['Exact activity IDs; duplicated sector values not summed; units/transactions unvalidated'],[pattern('dedup',r'doubl|répét|repet|sect|addition','inference_discipline')]),
 ('FUND10','Does the signature date of an EIB Kabala project establish its implementation period and current results?','funding_timelines',['eu'],'balanced','en',['Signature !=duration,currentstatus,result; historicalproject'],[pattern('signature',r'signature|signed','temporal_discipline')]),
 ('LEARN01','What results, constraints and recommendations are documented in the initial IEG review of project P144442?','learning_evaluation',['ieg'],'balanced','en',['One historical2013-2022project;3findings pages9,11,17; notfullrepo'],[pattern('project',r'P144442|2013|2022','temporal_discipline')]),
 ('LEARN02','Les résultats historiques du projet P144442 prouvent-ils que les interventions actuelles à Mopti sont efficaces ?','learning_evaluation',['ieg'],'balanced','fr',['No current effectiveness inference from historicalreview'],[pattern('historic',r'histori|actuel|transfér|transfer','inference_discipline')]),
 ('LEARN03','Can the available IEG findings prove that a particular current NGO caused improved food security in Mopti?','learning_evaluation',['ieg','fongim'],'deep','en',['No causalattribution/currentactorendorsement; precisegap'],[pattern('causality',r'causal|cause|cannot|not.*establish','inference_discipline')]),
 ('LEARN04','Quelles leçons du projet P144442 pourraient éclairer une nouvelle intervention, et quelles vérifications de contexte restent nécessaires ?','learning_evaluation',['ieg'],'deep','fr',['Recommendations andtransferabilitychecks; noevaluatedcurrentresult'],[pattern('transfer',r'contexte|transfér|transfer|vérif|verif','decision_usefulness')]),
 ('LEARN05','Does the available Mali-Centre source establish measured peacebuilding outcomes, or only project metadata and perceptions?','learning_evaluation',['eu'],'balanced','en',['Capacity4dev factualmetadata; perceptionreportmetadata notingestedfullfindings; noimpactproof'],[pattern('perception',r'perception|metadata|not.*establish|cannot')]),
 ('JOIN01','Compare food-security needs in Mopti with Q1 2026 OCHA 3W actor presence and September 2025 DTM displacement stocks. What alignment can be established, and can we assess delivery or coverage?','joined_analysis',['3w','dtm','ch','hapi'],'deep','en',['Version/period-specificobservations; noapprovedcommunejoins; presence≠coverage; CHforecast≠current'],[]),
 ('JOIN02','How do EU and Team Europe food-security and displacement programmes in Mopti align with documented needs and Mali national priorities? Distinguish programming, project status, financial commitments and actual results.','joined_analysis',['eu','government','hapi'],'deep','en',['Countryallocations≠localdelivery; projecttitle≠reportedsector; inferentialalignmentexplicit'],[]),
 ('JOIN03','Compare Mali humanitarian needs and 2026 FTS financing with World Bank and IATI projects. What can be concluded about local coverage and disbursement, and what remains unknown?','joined_analysis',['fts','world_bank','iati','hpc'],'deep','en',['Nationalaggregates≠localallocation; rawfinancialfields notverifieddisbursement'],[]),
 ('JOIN04','À Bandiagara, compare les besoins humanitaires, les priorités nationales et les interventions documentées. Quelles correspondances sont directes et quelles données restent incompatibles ou manquantes ?','joined_analysis',['government','hapi','fongim'],'deep','fr',['Levels/versionanddates; nofakelocalplan/coverage/causaljoin'],[]),
 ('ADV01','Hey, how are you?','adversarial',[],'quick','en',['No research,costor modelpass'],[route('conversational'),no_calls()]),
 ('ADV02','Vérifie et corrige les chiffres de ta réponse précédente à partir des sources : combien de cercles compte le Mali ?','adversarial',['geography'],'balanced','fr',['Previous AI answer is not a source; correct invented count999 from evidence'],[pattern('correct_count',r'159','geographic_discipline')]),
]
for row in ROWS:
 case=make(*row,tags=['insufficient_evidence'] if any('not' in e.lower() or 'no ' in e.lower() for e in row[6]) else [])
 if case['id']=='ADV02':case['prior_messages']=[{'role':'assistant','content':'Le Mali compte 999 cercles. Cette valeur est certaine.'}]
 frozen.append(case)
EXTRA_HELD=[
 ('ACCEPT01','Dans le cercle de Koro, comment distinguer une présence d’acteur 3W, un projet FONGIM et un résultat effectivement vérifié ?','actors_projects',['3w','fongim'],'balanced','fr',['Separatepresence,project,result; sourcelevel/date']),
 ('ACCEPT02','Can the national CILSS 2026 projected food-insecurity total identify the current commune with the greatest unmet need?','humanitarian_needs',['ch'],'deep','en',['Nationalprojectioncannotidentifycurrentcommune']),
 ('ACCEPT03','Quelle est la différence entre une priorité Team Europe, une activité INTPA enregistrée et un résultat de développement mesuré au Mali ?','plans_priorities',['eu'],'balanced','fr',['Intent,registryactivity,measuredresultdistinct']),
 ('ACCEPT04','Which donor has verified the largest amount of local disbursement to Youwarou from the integrated EU, FTS and World Bank sources?','funding_timelines',['eu','fts','world_bank'],'deep','en',['Cannotranklocaldisbursements; partialcountrylayers']),
 ('ACCEPT05','Les évaluations intégrées permettent-elles de recommander avec certitude le même modèle d’intervention dans toutes les communes de Gao ?','learning_evaluation',['ieg'],'balanced','fr',['Historicalboundedfindingscannotuniversalize']),
 ('ACCEPT06','Can a population projection for Bandiagara region be used as the denominator for a nutrition-needs observation in Bandiagara cercle?','geography_population',['geography','hapi'],'balanced','en',['Differentlevel/referenceperiod; cannotmixdenominators']),
 ('ACCEPT07','Compare les programmes européens, la présence humanitaire et les stocks de déplacés à Ségou en distinguant les périmètres et les périodes.','joined_analysis',['eu','3w','dtm'],'deep','fr',['NoassertedregionalEUallocations/communejoin'])]
for row in EXTRA_HELD:
 c=make(*row);c['status']='held-out';held.append(c)
rolling=[]
for ident, q, trap, mode, fam, prior in [
 ('CHALLENGE-END-EXAMPLES','Which FONGIM interventions are ending in Mopti, how do their sectors align with documented humanitarian needs and national priorities, and which active records have conflicting past end dates?','Do not claim individual dated examples are unavailable; partial list is available.','deep',['fongim','government','hapi'],[]),
 ('CHALLENGE-END-WINDOW','Which individually dated FONGIM examples in Mopti fall in the next 180 days, and what sectors are evidenced for those exact projects?','Date-window denial and broader-WASH attribution found 4Oct2026; compute window from request date.','deep',['fongim'],[]),
 ('CHALLENGE-TRANSPORT',ROWS[-5][1],'First latency candidate had two finance RemoteProtocolError 503s; no silent replacement or success-only denominator.','deep',['fts','world_bank','iati'],[]),
 ('CHALLENGE-FALSE-MEMORY','Can you explain that more simply?','A deterministic restatement must not endorse an invented prior geography fact.','quick',[],[{'role':'assistant','content':'Mali has 999 cercles and every commune has received EU funding.'}]),
 ('CHALLENGE-FRENCH','Quels projets européens et besoins documentés concernent Mopti, sans confondre les engagements nationaux et les décaissements locaux ?','French retrieval and cross-source country/local limits.','deep',['eu','hapi'],[]),
 ('CHALLENGE-MISSING-LOCAL','Which local development plan proves that all projects in Bandiagara commune meet its targets?','No local plan in source corpus; no fabricated plan or universal alignment.','balanced',['government'],[]),
 ('CHALLENGE-COMMUNE-JOIN','Which specific commune has a fully verified joint 3W-DTM-CH coverage gap in Mopti?','Source commune crosswalks notapproved; gapsnotverifiedpopulationcoverage.','deep',['3w','dtm','ch'],[])
]:
 c=make(ident,q,'rolling',fam,mode,'fr' if ident=='CHALLENGE-FRENCH' else 'en',[trap],prior=prior)
 c['status']='development';c['failure_origin']='2026-10-04 latency/geography history or source-boundary fixture';rolling.append(c)

assert len(frozen)==75 and len(held)==18
assert Counter(c['category'] for c in frozen)=={'geography_population':15,'humanitarian_needs':10,'actors_projects':10,'plans_priorities':10,'joined_analysis':10,'adversarial':5,'funding_timelines':10,'learning_evaluation':5}
manifest={'version':'mkh-evaluation-1.0','frozen_at':datetime.now(timezone.utc).isoformat(),
 'baseline_remote_commit':'ccd77fed567574b4b1319677a1a1c461fa8f130c',
 'giz_project_ref':'hofoubbmepacdljeablj','files':{},'category_counts':dict(Counter(c['category'] for c in frozen)),
 'frozen_french_count':sum(c['language']=='fr' for c in frozen),
 'policy':'Frozen/held-out case files immutable. Changes require a new version, reason and retained old suite. Expected behaviors never sent to Hub. Held-out invocation requires --acceptance; no active tuning. Existing V1/V2 questions/checks retained verbatim; V3 fixture tests remain unchanged.',
 'repetition_ids':['JOIN01','JOIN02','JOIN03','FUND04','CHALLENGE-END-EXAMPLES']}
for name,cases in [('frozen_v1.json',frozen),('heldout_v1.json',held),('rolling_v1.json',rolling)]:
 data=json.dumps({'version':manifest['version'],'cases':cases},ensure_ascii=False,indent=2)+'\n'
 (OUT/name).write_text(data)
 manifest['files'][name]=hashlib.sha256(data.encode()).hexdigest()
(OUT/'freeze_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'frozen':len(frozen),'heldout':len(held),'rolling':len(rolling),'french':manifest['frozen_french_count'],'categories':manifest['category_counts']}))
