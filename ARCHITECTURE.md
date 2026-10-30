# Perspective Loom — Architecture & Technical Design

**Multi-Perspective LLM Deliberation & Evaluation Engine**

---

## 1. Architectural Overview

Perspective Loom separates domain logic, perspective specifications, model provider adapters, evaluation rubrics, and HTTP/MCP transport layers into clean, independently testable modules:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                             Transport Layer                             │
│  Django HTTP & NDJSON Views (`ai_app/views/`) | MCP Adapter (`mcp_tools`)│
└───────────────────────────────────────┬─────────────────────────────────┘
                                        │ Typed Dataclasses (`ai_app/engine/schemas.py`)
┌───────────────────────────────────────▼─────────────────────────────────┐
│                    Deliberation Engine (`ai_app/engine/`)               │
│  - `DeliberationEngine` (`orchestrator.py`)                             │
│      • Strategy A: `single_model_baseline`                              │
│      • Strategy B: `independent_perspectives` (concurrent + synthesis)  │
│      • Strategy C: `deliberative_exchange` (analysis + critique + synth)│
│  - `PerspectiveRegistry` (`perspectives.py`)                            │
│      • 4 Technical/Epistemological Perspectives                         │
│      • 9 Preserved Historical Contemplative Perspectives                │
└───────────────────┬───────────────────────────────────┬─────────────────┘
                    │                                   │
┌───────────────────▼───────────────────┐   ┌───────────▼─────────────────┐
│    Model Provider Layer (`providers`) │   │  Evaluation Lab (`evaluation`)│
│  - `ModelProvider` Protocol           │   │  - `DeliberationEvaluator`   │
│  - `FakeModelProvider` (CI/Offline)   │   │  - `ExperimentRunner`        │
│  - `OpenAICompatibleProvider`         │   │  - Domain Rubrics & Metrics  │
│  - `OllamaProvider` (Local)           │   │  - `datasets/eval_benchmark` │
└───────────────────────────────────────┘   └─────────────────────────────┘
```

### Why Custom Lightweight Orchestration Over LangGraph / OpenAI Agents SDK?
During Phase 2 design, we evaluated **LangGraph** and the **OpenAI Agents SDK** against actual system requirements:
- Perspective Loom executes a bounded, acyclic 3-stage pipeline (`independent_analyses` -> optional `critique_round` -> `synthesis`), not an open-ended cyclic state machine or autonomous tool-calling loop.
- Coupling core domain schemas to a single vendor SDK (`openai-agents`) or heavy graph runtime (`langgraph` + `langchain-core`) increases dependency churn and obscures failure semantics.
- Using standard Python `dataclasses`, `ThreadPoolExecutor` for concurrent perspective fan-out, and a 50-line `ModelProvider` protocol achieves zero framework lock-in, sub-millisecond unit test execution, and full inspectability.

---

## 2. Domain Schemas & Epistemic Boundaries

Defined in `ai_app/engine/schemas.py`:
- **`PerspectiveSpec`**: Versioned specification (`slug`, `name`, `version`, `domain`, `purpose`, `system_instructions`, `interpretive_methodology`, `boundaries_and_limitations`, `epistemic_type`, `evidence_requirements`, `permitted_tools`).
- **`EvidenceItem`**: Keeps user-supplied or benchmark-verified facts (`source_id`, `title`, `content`, `verified`) strictly separate from model-generated interpretations.
- **`PerspectiveAnalysis`**: Captures each perspective's `core_thesis`, `analysis`, `supporting_evidence_refs`, `assumptions_and_limitations`, `uncertainty_level`, and per-call telemetry.
- **`CritiqueExchange`**: Cross-examination output recording `points_of_tension`, `evidence_challenges`, and `constructive_revision`.
- **`SynthesisResult`**: Structured synthesis preserving `convergent_agreements`, `preserved_disagreements`, `uncertainties_and_limits`, `open_questions`, `actionable_recommendations`, and an explicit `epistemic_note`.
- **`ExecutionTrace` & `StepTrace`**: Tracks `trace_id`, per-step latency, prompt/completion tokens, estimated USD cost, retry counts, and partial failures.

---

## 3. Security, Privacy & Data Retention

Implemented in `ai_project/settings.py` and `ai_app/security.py`:
1. **No Hardcoded Secrets**: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (defaults to `False`), `DJANGO_ALLOWED_HOSTS`, and `DATABASE_URL` are read from environment variables.
2. **User Isolation & Removal of `testuser` Assumption**:
   - The legacy `/ai/ask-role/` endpoint crashed if `testuser` did not exist in SQLite, and `/ai/history/` returned every user's conversations without authentication.
   - `resolve_request_user()` permits private reads through authenticated Django sessions or a configured API key (`X-API-Key` / `Authorization: Bearer`). A trusted API client may use `X-Perspective-User` to select a record scope; that header is not end-user authentication.
   - `/ai/history/` and `/ai/runs/` filter records by `user=user_obj`. Cross-scope access to `/ai/runs/<run_id>/` returns `403 Forbidden`. The shared API key must remain server-side; public multi-user authentication is not implemented.
3. **Structured Log Redaction**: `SensitiveDataRedactionFilter` scrubs `GITHUB_TOKEN`, `OPENAI_API_KEY`, and `PERSPECTIVE_LOOM_API_KEY` before log emission, and views log exception types rather than raw request bodies containing personal prompts.
4. **Data Retention Policy**: Controlled via `DATA_RETENTION_DAYS` (default 90 days). Operators can purge historical records at any time via `python manage.py reset_history`.

---

## 4. Extensibility for Nexus Flow (MCP Symbol Ontology)

`ai_app/mcp_tools.py` defines `SymbolOntologyEntry` and four MCP-aligned tool handlers (`list_perspectives`, `deliberate`, `compare_deliberations`, `evaluate_deliberation`). When **Nexus Flow** (the Rust-based dream interpretation platform) integrates in the future, it can pass symbol ontology entries directly into `deliberate(symbol_ontology=[...])`, which converts them into `EvidenceItem` records with explicit epistemic guidance prioritizing the user's own associations over fixed archetype definitions.
