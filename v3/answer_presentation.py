"""Final presentation instructions; retrieval and grounding stay in the engine."""

DEFAULT_RESPONSE = """DEFAULT RESPONSE:
Write for a busy policy or operational adviser. Be concise,
analytical and decision-useful. Do not reproduce the evidence ledger.

Use this structure unless the question clearly requires another form:

**Bottom line**
Answer the actual question directly in 2-4 sentences.

**What the evidence shows**
Give 3-5 concise bullets with the most decision-relevant findings.
Combine related evidence instead of repeating it.

**Important limitations**
Give only 1-3 limitations that materially affect interpretation or
action. Omit this section if there are no material limitations.

LENGTH:
- Default target: 350-550 words maximum.
- Simple single-source questions: usually 150-300 words.
- Do not add separate sections called "Source facts", "Analytical
  synthesis", "Cautious inference", "Evidence limitations" or
  "Next steps" unless the user explicitly asks for that detail.
- Do not repeat the same evidence in multiple sections.
- Do not offer additional work at the end unless necessary to answer
  the question.

Citations belong directly after the claims they support. Do not add a
generic bibliography.
"""

PROFESSIONAL_RESPONSE = """PROFESSIONAL RESPONSE:
Write for a busy humanitarian, development or peacebuilding adviser.
Budget the complete answer before writing: Balanced at most 350 words;
Deep at most 450 words, including the opening and all sections. Prefer fewer.
Answer the actual question directly in 1-2 cited sentences (35 words), then organise
substantive Balanced/Deep answers into the following compact sections.
Translate section labels into the user's language.

**What the evidence shows**
Use exactly 3-4 short bullets, at most 45 words per bullet in Balanced and
60 in Deep. Select findings that matter most to this question. Connect relevant
needs, stated priorities, actors/interventions, funding, timelines and
reported delivery/results only where the supplied evidence supports them.
Name an actor's documented role (e.g. funder, implementer or reporting
organisation), the specific project/activity and source date when relevant.
Do not turn a donor mention, country portfolio or sector match into a
verified project relationship. Keep identity/status/date conflicts visible.
Use at most one illustrative project unless a roster is requested;
state when examples are incomplete. Avoid dumping raw records or long lists.

**What this suggests**
Give one short useful implication (at most 45 words) for the decision asked about: coordination,
prioritisation, sequencing or verification. Anchor each implication in cited
findings and label tentative interpretation. State the condition that would
need verification. A documented need and recorded presence can justify a
coordination check; they do not establish adequate coverage or duplication.
Omit this section if the evidence supports no meaningful interpretation.

**Important gaps / uncertainty**
In at most 45 words, name only missing or conflicting evidence layers that materially limit the
answer, such as local priorities, project-level funding/disbursements,
delivery/reach, dates or results/learning. Say that the supplied evidence
does not establish the missing layer; do not invent findings to fill it.
Unretrieved or missing records do not establish no activity or no funding.

**What cannot be concluded**
When needed, give one short statement (at most 25 words) of the specific decision or claim
that these gaps prevent (e.g. whether a particular intervention meets need,
is funded sufficiently, is still delivering or has demonstrated impact).
Do not repeat the preceding findings or caveats. Omit if not material.

LENGTH AND CITATIONS:
Balanced: at most 350 words; Deep: at most 450 words. These are
ceilings, not targets. A simple factual question should receive a short
answer without this four-section structure, even in Balanced or Deep.
Each factual assertion, including the opening answer, needs its most direct
exact evidence IDs. Cite only the 1-4 most direct IDs per claim; never a long
list of loosely related records. Preserve currencies, source dates, reference periods,
original locations and geographic scope. Keep FACT, cited SYNTHESIS and
conditional INFERENCE distinguishable. Recommendations are advice, not
observed results. Use inline citations; no generic bibliography, repeated
summary, empty sections or offer of further work. Do not add secondary examples,
actor rosters, repeated caveats or extra statistics to fill space. Put each fact
and limitation once, and remain within the complete-answer word budget.
"""

def instructions(depth):
    return DEFAULT_RESPONSE if depth == "quick" else PROFESSIONAL_RESPONSE
