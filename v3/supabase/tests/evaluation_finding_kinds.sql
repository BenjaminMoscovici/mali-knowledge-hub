BEGIN;
SET LOCAL statement_timeout = '20s';
DO $checks$
DECLARE
    seed public.mkh_source_records%ROWTYPE;
    candidate jsonb;
    kind text;
    field text;
    rejected boolean;
    failed_constraint text;
    expected_new_kinds boolean := true;
BEGIN
    SELECT * INTO STRICT seed FROM public.mkh_source_records
    WHERE source_type = 'evaluation_finding' AND payload->>'project_id' = 'P144442'
    LIMIT 1;
    FOREACH kind IN ARRAY ARRAY[
        'results','constraints','recommendations','reported_reach','methodology_limits'
    ] LOOP
        candidate := seed.payload || jsonb_build_object('finding_kind', kind);
        rejected := false;
        BEGIN
            INSERT INTO public.mkh_source_records
                (id,release_id,span_id,source_type,reference_start,reference_end,payload)
            VALUES (gen_random_uuid(),seed.release_id,seed.span_id,seed.source_type,
                    seed.reference_start,seed.reference_end,candidate);
        EXCEPTION WHEN check_violation THEN
            GET STACKED DIAGNOSTICS failed_constraint = CONSTRAINT_NAME;
            IF failed_constraint <> 'mkh_learning_semantics' THEN RAISE; END IF;
            rejected := true;
        END;
        IF rejected <> (kind IN ('reported_reach','methodology_limits') AND NOT expected_new_kinds) THEN
            RAISE EXCEPTION 'Unexpected acceptance for finding kind %', kind;
        END IF;
    END LOOP;
    FOREACH field IN ARRAY ARRAY[
        'project_id','finding_kind','page','finding','methodology','transferability'
    ] LOOP
        candidate := seed.payload - field;
        rejected := false;
        BEGIN
            INSERT INTO public.mkh_source_records
                (id,release_id,span_id,source_type,reference_start,reference_end,payload)
            VALUES (gen_random_uuid(),seed.release_id,seed.span_id,seed.source_type,
                    seed.reference_start,seed.reference_end,candidate);
        EXCEPTION WHEN check_violation THEN
            GET STACKED DIAGNOSTICS failed_constraint = CONSTRAINT_NAME;
            IF failed_constraint <> 'mkh_learning_semantics' THEN RAISE; END IF;
            rejected := true;
        END;
        IF NOT rejected THEN RAISE EXCEPTION 'Missing field % accepted', field; END IF;
    END LOOP;
    FOREACH candidate IN ARRAY ARRAY[
        seed.payload || '{"finding_kind":"unknown_kind"}'::jsonb,
        seed.payload || '{"project_id":"not-an-exact-project"}'::jsonb,
        seed.payload || '{"page":0}'::jsonb,
        seed.payload || '{"page":-1}'::jsonb
    ] LOOP
        rejected := false;
        BEGIN
            INSERT INTO public.mkh_source_records
                (id,release_id,span_id,source_type,reference_start,reference_end,payload)
            VALUES (gen_random_uuid(),seed.release_id,seed.span_id,seed.source_type,
                    seed.reference_start,seed.reference_end,candidate);
        EXCEPTION WHEN check_violation THEN
            GET STACKED DIAGNOSTICS failed_constraint = CONSTRAINT_NAME;
            IF failed_constraint <> 'mkh_learning_semantics' THEN RAISE; END IF;
            rejected := true;
        END;
        IF NOT rejected THEN RAISE EXCEPTION 'Invalid finding accepted'; END IF;
    END LOOP;
END $checks$;
ROLLBACK;
SELECT true AS constraint_checks_passed,
       (SELECT count(*) FROM public.mkh_source_records
        WHERE source_type='evaluation_finding' AND payload->>'project_id'='P144442') AS original_findings_retained;
