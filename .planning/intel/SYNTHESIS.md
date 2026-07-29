# SYNTHESIS.md — elc-audit-engine Document Ingest Synthesis

Single entry point for downstream consumers (`gsd-roadmapper`). This file summarizes what was synthesized from the ingested documents; see the per-type intel files for full detail.

## Ingest Summary

- **Docs classified:** 3 total — 1 ADR, 1 SPEC, 1 DOC (0 PRD, 0 UNKNOWN)
- **Mode:** new (net-new bootstrap; no prior `.planning/` state existed)
- **Precedence applied:** ADR (0) > SPEC (1) > DOC (2), all manifest-declared and manifest-overridden (`manifest_override: true` on all three classifications)

| Doc | Type | Precedence | Locked | Confidence |
|---|---|---|---|---|
| progress.md | ADR | 0 | true | high |
| docs/plans/2026-07-29-elc-audit-engine-design.md | SPEC | 1 | false | high |
| 電子抽審.md | DOC | 2 | false | high |

## Decisions (decisions.md)

- **12 LOCKED decisions** (D1-D12) from progress.md, all non-negotiable and authoritative over SPEC/DOC content
- **1 LOCKED system architecture diagram** (progress.md §二)
- **1 LOCKED rule-repository layering scheme** (progress.md §三, 3 tiers: SQLite / PageIndex / ChromaDB)
- All SPEC content relating to these topics is elaboration, not contradiction — logged as "Elaborated by" annotations, not separate decisions

## Requirements (requirements.md)

- **9 requirements extracted**, derived from ADR+SPEC milestone breakdown (no dedicated PRD in this ingest set):
  - REQ-project-skeleton (M1), REQ-rule-repository (M2), REQ-parsers (M3), REQ-record-aggregator (M4), REQ-three-way-comparator (M5), REQ-output-reinforcement-report (M6), REQ-output-appeal-draft (M7), REQ-e2e-testing (M8) — all Phase 1
  - REQ-phase2-his-integration — Phase 2, placeholder/low-detail
- No competing acceptance-criteria variants found

## Constraints (constraints.md)

- **12 constraints extracted** (C1-C12), from SPEC (C1-C7) and DOC (C8-C12)
- Type breakdown: api-contract (C1, C3 partial, C7, C8, C9), nfr (C2, C3, C4, C5, C6), protocol (C10), schema (C11, C12)
- C8, C11 cross-confirmed as non-contradictory with ADR/SPEC (field-level detail corroborates, doesn't conflict)

## Context (context.md)

- **7 context topics** extracted from 電子抽審.md, covering: NHI audit/appeal background, as-is paper workflow, to-be cloud-HIS workflow (Phase 2 reference), administrative prerequisites, doctor-toolbox ecosystem, UML/ER research appendix, and 6-stage research roadmap (noted as broader/distinct from this project's own roadmap)

## Conflicts

- **0 BLOCKERS**
- **0 competing-variants (WARNINGS)**
- **5 INFO (auto-resolved / cross-confirmed)** — see `.planning/INGEST-CONFLICTS.md` for full detail:
  1. Benign 3-way cross-reference cycle (no contradiction, not a blocker)
  2. SPEC elaborates ADR D2 (LLM engine config)
  3. SPEC narrows ADR D4 tech-stack scope (Flask/ChromaDB phase-tagging)
  4. SPEC extends ADR D8 output bullet list
  5. DOC field-level detail cross-confirms ADR/SPEC appeal-structure decisions

## Pointers

- Conflict report: `.planning/INGEST-CONFLICTS.md`
- Decisions: `.planning/intel/decisions.md`
- Requirements: `.planning/intel/requirements.md`
- Constraints: `.planning/intel/constraints.md`
- Context: `.planning/intel/context.md`
- Downstream deliverables already produced from this synthesis: `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`
