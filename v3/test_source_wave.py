import source_wave


def test_population_evidence_keeps_same_name_levels_and_page_citations():
    rows = source_wave.retrieve_source_evidence("What is the population of Mopti region, cercle and commune?")
    population = [row for row in rows if row["source_type"] == "official_population_table"]
    assert {row["geographic_scope"].split(" > ")[-1].casefold() for row in population} == {"mopti"}
    assert {row["content"].split()[0].casefold() for row in population} >= {"region", "cercle", "commune"}
    assert all(row["page"] and row["retrieved_at"] and "projection" in row["content"] for row in population)


def test_cod_evidence_preserves_level_parent_and_identifier():
    rows = source_wave.retrieve_source_evidence("Which region and cercle is Djenné in, and what is its P-code?")
    cod = [row for row in rows if row["source_type"] == "official_geography_registry"]
    assert cod
    assert any("administrative level cercle" in row["content"] for row in cod)
    assert all(row["version"] == "v03" and row["source_endpoint"].startswith("https://") for row in cod)


def test_unrelated_question_does_not_add_source_wave_evidence():
    assert source_wave.retrieve_source_evidence("What colour is the logo?") == []


def test_existing_hpc_snapshot_is_exposed_without_duplicate_ingestion():
    rows = source_wave.retrieve_source_evidence("Compare needs, targets, reached and funding in 2026")
    hpc = [r for r in rows if r["source_type"] == "humanitarian_planning_snapshot"]
    assert len(hpc) == 1
    assert "5,100,000" in hpc[0]["content"] and "3,800,000" in hpc[0]["content"]
    assert "no financial requirements" in hpc[0]["content"]
