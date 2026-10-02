"""Real-file acceptance queries; no LLM or private account data required."""
import argparse
import json
from pathlib import Path
from source_foundation import SourceStore


def benchmark(database):
    store = SourceStore(database)
    population_dataset, needs_dataset = "mli-instat-localities-2023", "mli-hpc-hno-2026"
    cases = []
    for name, level, expected in (("BANDIAGARA", "region", 1270224),
                                  ("BANDIAGARA", "cercle", 230093),
                                  ("BANDIAGARA", "commune", 30916),
                                  ("MOPTI", "region", 1087526)):
        r = store.population(name, dataset_id=population_dataset, level=level)
        assert r["status"] == "reported" and r["evidence"][0]["value"] == expected
        e = r["evidence"][0]
        assert e["page"] > 0 and e["passage"] and e["reference_start"] == "2023-01-01"
        cases.append({"question": f"Quelle population projetée en 2023 pour {name}, niveau {level} ?",
            "status": "passed", "answer": f"{expected:,} personnes, projection DNP fondée sur le RGPH5 de 2022. Ce chiffre ne décrit pas la population actuelle.",
            "scope": level, "evidence": e})
    r = store.population("BOLIBANA", dataset_id=population_dataset, level="locality")
    assert r["status"] == "ambiguous" and len(r["candidates"]) == 4
    cases.append({"question": "Quelle population pour Bolibana sans préciser la commune ?", "status": "passed",
                  "answer": "Localité ambiguë : préciser la commune et la région.", "candidate_count": 4})
    for status, expected in (("INN", 5100000), ("TGT", 3800000)):
        r = store.humanitarian("Mali", dataset_id=needs_dataset, level="country", status=status)
        assert r["status"] == "reported" and r["evidence"][0]["value"] == expected
        cases.append({"question": f"Mali 2026 : {status} ?", "status": "passed", "answer": expected,
                      "scope": "country", "evidence": r["evidence"][0]})
    r = store.humanitarian("Mali", dataset_id=needs_dataset, level="country", status="REA")
    assert r["status"] == "not_reported" and not r["evidence"]
    cases.append({"question": "Combien de personnes atteintes en 2026 ?", "status": "passed",
                  "answer": "Non renseigné dans cet export ; une cellule vide ne signifie pas zéro."})
    r = store.humanitarian("Mopti", dataset_id=needs_dataset, level="region")
    assert r["status"] == "unresolved"
    cases.append({"question": "Déduire les besoins 2026 de Mopti du total national ?", "status": "passed",
                  "answer": "Impossible : cet export ne fournit pas de ventilation régionale."})
    country = store.resolve("Mali", dataset_id="mli-cod-ab", level="country")["candidates"][0]
    assert not store.approved_targets(country["id"])
    cases.append({"question": "Les correspondances COD–INSTAT peuvent-elles déjà autoriser des jointures ?",
                  "status": "passed", "answer": "Non : 171 propositions attendent une vérification des limites et des identifiants."})
    integrity = store.db.execute("pragma foreign_key_check").fetchall()
    assert not integrity
    store.close()
    return {"scope": "Local stored-source retrieval; not a deployed LLM or full pilot acceptance", "passed": len(cases),
        "cases": cases, "pilot_analyses": {"needs_priorities_projects_gaps": "pending: live corpus/project access and reviewed crosswalks",
        "closures_financing_sequencing": "pending: dated project/funding releases", "evaluation_transferability": "pending: reviewed evaluation collection"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = benchmark(args.database)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"real_file_acceptance_cases_passed": result["passed"]}))
