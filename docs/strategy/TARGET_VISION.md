# Mali Knowledge Hub — Target Vision

**One platform. Connected knowledge. Better decisions.**

## Purpose

The Mali Knowledge Hub (MKH) is an AI-powered knowledge and analytical platform intended to connect fragmented information about Mali and support evidence-based professional decisions across the Humanitarian–Development–Peace (HDP) Nexus.

MKH is **not merely a document chatbot**. It should provide an accessible, continuously expanding knowledge infrastructure integrating:

- Government strategies and local development plans
- Humanitarian assessments and operational information
- Statistics, datasets and geographically referenced observations
- Organisations, projects, interventions and funding
- Evaluations, results, lessons learned and institutional knowledge

Its analytical ambition is to connect **Need → Priority → Intervention → Actor → Geography → Funding → Result → Learning** while respecting the limits of the evidence.

## Defining architectural requirement

**As new sources are integrated, MKH must become more knowledgeable and analytically capable without requiring question-specific code, prompts or retrieval rules.**

New sources should become discoverable, queryable, combinable and citable through reusable ingestion, metadata, retrieval, analytical and evidence mechanisms. Source-specific connectors and declarative schema mappings are acceptable where genuinely necessary; answer patches for individual questions are not.

## Defining product requirement

**MKH must be genuinely useful as a professional analytical tool.**

Professionals should be able to ask natural-language questions in a conversation, without knowing how the underlying information is stored, and get relevant, accurate, well-structured answers that help them carry out actual work.

Useful workflows include briefings, comparisons between geographic areas and reporting periods, cross-source analysis, mapping documented actors and interventions, identifying evidence gaps, and exploring potential complementarities.

An MKH answer should:
- Give the decision-relevant finding clearly and promptly.
- Distinguish facts, evidence-based synthesis, and inference.
- Supply precise, inspectable citations supporting material claims.
- Respect geographic boundaries, reporting periods, definitions, units, methodologies and source limitations.
- Identify uncertainty, conflicts and missing evidence rather than inventing certainty.
- Avoid treating operational presence as delivered coverage, expenditure as impact, or missing evidence as evidence of absence.
- Read naturally and professionally, comparable to a capable conversational assistant.

## Development philosophy

Build the strongest overall product, not the greatest number of features. Preserve verified functionality and data; challenge architecture when its limitations are demonstrated. Optimize for professional usefulness, reliability, extensibility, maintainability, latency and cost together.

**The final test:** previously unseen sources expand real answer capabilities without bespoke question logic, and professional users can obtain dependable, useful answers across reasonable variations in wording.
