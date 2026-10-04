# Geography and fast routing — 4 October 2026

New source families are paused. This sprint reuses the immutable COD/INSTAT
foundation and adds a queryable, release-specific geographic model.

## Reference and reconciliation

Preferred enumerated hierarchy: INSTAT RGPH5 Répertoire des localités du Mali
en 2023, January 2026 edition, release
`837f4d93-ab1c-5120-8460-29836397cb94`.
Original: https://www.instat-mali.org/laravel-filemanager/files/shares/rgph/repvila-rgph5_rgph.pdf
Pages 6–7 describe the 2023 framework. National administrative counts are
computed from distinct source identities across the directory, not invented
as a quotation from those pages. Page 9 reports the locality totals.

| Reference | Regions | Districts | Cercles/admin2 | Communes | Localities parsed |
|---|---:|---:|---:|---:|---:|
| INSTAT 2023 / Jan 2026 | 19 | 1 | 159 | 815 | 12,915 |
| COD v03, valid 4 Sep 2025 | 19 | 1 | 160 admin2 records | Not enumerated | Not enumerated |

COD release `75917a21-a82b-5ee8-82ff-e3fd4c9acec7` has a Bamako admin2
representation. It is not merged into an additional INSTAT cercle.
INSTAT's seven arrondissement rows cover Bamako only; they are not a national
arrondissement total. Region → cercle → commune → locality and Bamako's
district → arrondissement → locality are explicit parent chains.

Every unit retains its release, source identity/locator, parent and boundary
version. Available COD P-codes remain available. INSTAT units without government
identifiers are not assigned invented P-codes. Aliases are separate name rows;
an alias is not automatically a verified historical renaming. Homonyms retain
distinct IDs and parents. Parent cycles and cross-release parents fail validation.

171 cross-release candidate matches remain proposed, with ten unresolved
matches. INSTAT reports 12,917 localities, while the extraction has 12,915;
missing Kayes/Dioila occurrences remain unresolved. The preferred release is
the most detailed current official directory verified here, not a guarantee
that every later legal amendment is incorporated. An indexed ministry page
uses a conflicting commune count; it is not silently substituted for the directory.
No operational record is remapped merely because its name matches this model.

`GET /api/geography` returns reference summaries. Name/level/release or unit_id
filters expose bounded lookups, aliases, identifiers, paths and child lists.
Chat answers use the same model, with original-source citations. Joined research
receives bounded framework context and a prohibition on assuming identity.

## Routing

Whole-message greeting, thanks and capabilities responses are deterministic.
They never load the research engine, embed a query or contact evidence APIs.
Exact conversation-only simplification requests extract and quote the previous
assistant answer's main point and limitations, without a model or retrieval call.
This is a shorter extract, not a newly generated paraphrase; sources remain
with the original answer. Factual follow-ups requiring new
evidence still go through context resolution and research.
Direct hierarchy/count/name queries use read-only structured retrieval.
Mixed needs, finance, population, delivery and other analytical questions retain
the existing research path and requested depth.

The API emits route, routing/server duration, model and embedding calls,
tracked external research HTTP calls, API token usage and estimated USD.
Browser metrics also record chat-request round-trip time. Account/database I/O
is explicitly outside the tracked external HTTP-call counter. Cost is a token
price estimate, not a billing receipt; infrastructure cost is excluded.
Cold service startup and sign-in/history I/O can affect perceived latency.

## Validation before deployment

116 V3 tests and two subtests pass; 11 V2 tests pass; frontend syntax passes.
New acceptance checks cover release counts, every parent chain, Mopti's 12
communes, Socoura's path, Bamba homonyms, unknown names, citation/version
provenance, public summary validation, and zero research/network calls for
trivial and direct geography requests. Existing account-ownership tests pass.
The public summary exposes the unresolved-place and proposed-crosswalk queues;
an unresolved-place chat question lists source names, levels, parents and reasons.
Live acceptance and timings are recorded after deployment, separately from
these local checks. Full programme acceptance still requires the previously
documented authenticated-account journey and source-access work.

## Next source gate

Only resume sources with a concrete unanswered question: PDSEC/local priorities;
verified reach/delivery; transaction/funding chains; evaluation results;
implementation geography; verified implementing organisations. State the
newly answerable user question before adding each source.
