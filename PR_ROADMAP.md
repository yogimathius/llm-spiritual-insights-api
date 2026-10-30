# Perspective Loom — Pull Request & Commit Roadmap

This document organizes the modernization into 5 focused, reviewable commits on one branch. The helper script (`scripts/create_pr_branches.sh`) creates that branch and its commits; it does not create pull requests.

---

## Commit 1: `foundation: stabilize runtime, security, and testing`

### Scope & Rationale
Establishes a trustworthy runtime, dependency, security, and testing foundation before altering orchestration behavior.

### Architectural Decisions
- Pruned `requirements.txt` from 80+ ML/Jupyter packages (`torch`, `transformers`, `scipy`, `ipykernel`) down to 9 core runtime packages, adding `ollama==0.4.7` (previously imported in `model_rotation.py` but missing from requirements) and updating Django and sqlparse to audited releases.
- Added `requirements-dev.txt` (`pytest`, `pytest-django`, `ruff`, `mypy`, `pip-audit`), `pyproject.toml`, `.env.example`, and `.github/workflows/ci.yml`.
- Moved `SECRET_KEY`, `DEBUG` (now defaulting to `False`), `ALLOWED_HOSTS`, and `DATABASE_URL` (supporting both SQLite and PostgreSQL) to environment variables in `ai_project/settings.py`.
- Added `SensitiveDataRedactionFilter` to prevent API keys or secrets from leaking into logs.
- Created `ai_app/security.py` to require an authenticated session or trusted API key for private reads, fixing the global `/ai/history/` data leak and the hardcoded `User.objects.get(username="testuser")` 500 error in `/ai/ask-role/`.

### Files Changed
- `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.env.example`, `.gitignore`, `.github/workflows/ci.yml`
- `ai_project/settings.py`
- `ai_app/security.py`
- `ai_app/views/dialogue.py`, `ai_app/views/history.py`, `ai_app/views/roles.py`
- `ai_app/management/commands/initialize_mock_user.py`

---

## Commit 2: `architecture: introduce typed deliberation engine`

### Scope & Rationale
Decouples perspective definitions and model execution from Django views and replaces brittle string-concatenation with typed schemas and a pluggable `ModelProvider` contract.

### Architectural Decisions
- Created `ai_app/engine/schemas.py` with typed dataclasses (`PerspectiveSpec`, `EvidenceItem`, `DeliberationRequest`, `PerspectiveAnalysis`, `CritiqueExchange`, `SynthesisResult`, `ExecutionTrace`, `DeliberationRunResult`).
- Created `ai_app/engine/providers.py` implementing `FakeModelProvider` (deterministic offline execution for CI), `OpenAICompatibleProvider` (GitHub Models & OpenAI with timeouts/retries), and `OllamaProvider` (fixing the hardcoded `model="llama2"` streaming bug and removing `print()` stdout pollution).
- Updated `ai_app/services/model_rotation.py` as a backward-compatible adapter over `ModelProvider`.

### Files Changed
- `ai_app/engine/__init__.py`, `ai_app/engine/schemas.py`, `ai_app/engine/providers.py`
- `ai_app/services/model_rotation.py`

---

## Commit 3: `features: independent perspectives and structured synthesis`

### Scope & Rationale
Preserves all 9 original contemplative perspectives as versioned interpretive methodologies while adding software architecture and research epistemology perspectives, and implements the multi-strategy `DeliberationEngine`.

### Architectural Decisions
- Built `PerspectiveRegistry` (`ai_app/engine/perspectives.py`) containing 4 technical/research perspectives (`Systems Pragmatist`, `Security & Trust Auditor`, `Domain Boundary Architect`, `Empirical Epistemologist`) and all 9 preserved historical roles (`Christian Mystic`, `Quantum Philosopher`, `Alchemist`, `Existential Navigator`, `Void Explorer`, `Time Weaver`, `Desert Father`, `Sufi Mystic`, `Vedantic Sage`).
- Implemented `DeliberationEngine` (`ai_app/engine/orchestrator.py`) supporting Strategy A (`single_model_baseline`), Strategy B (`independent_perspectives`), and Strategy C (`deliberative_exchange`) with concurrent execution, partial-failure degradation (`partial_failure`), and NDJSON progress streaming.
- Added `DeliberationRun` model and migration `0004_deliberationrun_and_role_metadata.py`.

### Files Changed
- `ai_app/engine/perspectives.py`, `ai_app/engine/orchestrator.py`
- `ai_app/models/llm_role.py`, `ai_app/models/deliberation.py`, `ai_app/models/__init__.py`
- `ai_app/migrations/0004_deliberationrun_and_role_metadata.py`
- `ai_app/management/commands/initialize_llm_roles.py`
- `ai_app/services/response_formatter.py`

---

## Commit 4: `evaluation: reproducible baseline comparisons`

### Scope & Rationale
Introduces the Evaluation Laboratory to test the core research hypothesis: when does structured multi-perspective deliberation outperform a single-model baseline, and at what token/latency cost?

### Architectural Decisions
- Created `datasets/eval_benchmark.json` with 4 multi-domain benchmark cases (`arch-001`, `arch-002`, `phil-001`, `symb-001`) and explicit evidence constraints.
- Built `DeliberationEvaluator` (`ai_app/evaluation/evaluator.py`) and `ExperimentRunner` (`ai_app/evaluation/runner.py`) measuring constraint markers, evidence separation, disagreement preservation, uncertainty acknowledgment, latency, token multipliers, and structural rubric points per 1,000 tokens. Synthetic scores do not establish answer quality.
- Added `python manage.py run_evaluation` and standalone `verify_engine.py`, generating an ignored report under `reports/`.

### Files Changed
- `datasets/eval_benchmark.json`; generated reports are kept under `reports/`.
- `ai_app/evaluation/__init__.py`, `ai_app/evaluation/evaluator.py`, `ai_app/evaluation/runner.py`
- `ai_app/management/commands/run_evaluation.py`

---

## Commit 5: `developer-experience: APIs, tracing, and documentation`

### Scope & Rationale
Exposes documented HTTP/streaming endpoints, an MCP-ready tool contract with Nexus Flow ontology hooks, comprehensive tests, and honest documentation.

### Architectural Decisions
- Added `/ai/perspectives/`, `/ai/deliberate/`, `/ai/deliberate/stream/`, `/ai/runs/`, `/ai/runs/<run_id>/`, `/ai/evaluate/`, and `/ai/compare/` in `ai_app/views/deliberation.py` and `ai_app/urls.py`.
- Added `ai_app/mcp_tools.py` exposing `list_perspectives`, `deliberate`, `compare_deliberations`, `evaluate_deliberation`, and `SymbolOntologyEntry`.
- Added full unit and integration test suites in `ai_app/tests.py` and `verify_engine.py`.
- Updated `README.md` and `ARCHITECTURE.md`.

### Files Changed
- `ai_app/views/deliberation.py`, `ai_app/urls.py`, `ai_app/mcp_tools.py`
- `ai_app/tests.py`, `verify_engine.py`
- `README.md`, `ARCHITECTURE.md`, `PR_ROADMAP.md`, `scripts/create_pr_branches.sh`
