# Perspective Loom

**Multi-Perspective LLM Deliberation & Evaluation Engine**

Perspective Loom is a modular deliberation and evaluation engine that investigates a central research question:

> **Can structured multi-perspective deliberation produce more useful, accurate, and insightful results than a single capable language model—and under what conditions?**

Perspective Loom executes controlled strategies side-by-side, separates supplied evidence from interpretive claims, preserves meaningful disagreements, and records execution traces (latency, token usage, estimated cost, and rubric scorecards) for inspection.

---

## Core Capabilities

- **Three Controlled Deliberation Strategies (`ai_app/engine/orchestrator.py`)**:
  - **Strategy A (`single_model_baseline`)**: Direct single-pass answer from one model.
  - **Strategy B (`independent_perspectives`)**: Concurrent independent analyses across selected perspectives followed by structured synthesis.
  - **Strategy C (`deliberative_exchange`)**: Concurrent independent analyses, a controlled cross-examination critique round, and structured synthesis.
- **Versioned Perspective Registry (`ai_app/engine/perspectives.py`)**:
  - **Software Architecture & Engineering**: `Systems Pragmatist`, `Security & Trust Auditor`, `Domain Boundary Architect`.
  - **Research & Epistemology**: `Empirical Epistemologist`.
  - **Preserved Historical Contemplative Perspectives**: `Christian Mystic`, `Quantum Philosopher`, `Alchemist`, `Existential Navigator`, `Void Explorer`, `Time Weaver`, `Desert Father`, `Sufi Mystic`, `Vedantic Sage`.
  - Every perspective is defined as an explicit interpretive methodology with stated boundaries and epistemic types (`empirical_evidence`, `architectural_tradeoff`, `philosophical_inquiry`, `symbolic_metaphor`, `contemplative_tradition`)—never as an authoritative personality presenting speculation as established fact.
- **Model-Provider Abstraction (`ai_app/engine/providers.py`)**:
  - `FakeModelProvider`: Deterministic, zero-cost offline provider for unit tests, CI, and reproducible structural benchmarks.
  - `OpenAICompatibleProvider`: Supports GitHub Models (`https://models.inference.ai.azure.com`) and OpenAI with configurable timeouts and bounded retries.
  - `OllamaProvider`: Supports local Ollama models while respecting per-request model configuration and avoiding stdout leaks.
- **Reproducible Evaluation Laboratory (`ai_app/evaluation/`)**:
  - Version-controlled benchmark dataset (`datasets/eval_benchmark.json`) spanning software architecture, philosophy of science, and symbolic interpretation.
  - Domain-specific heuristics measuring constraint markers, evidence separation, disagreement preservation, uncertainty acknowledgment, and rubric points per 1,000 tokens.
- **MCP-Ready Tool Surface & Nexus Flow Extensibility (`ai_app/mcp_tools.py`)**:
  - Transport-agnostic handlers for `list_perspectives`, `deliberate`, `compare_deliberations`, and `evaluate_deliberation`, plus `SymbolOntologyEntry` hooks for downstream symbolic platforms such as **Nexus Flow**.

---

## Quickstart & Clean Setup

### 1. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

By default, `DEFAULT_MODEL_PROVIDER=fake` and `DJANGO_DEBUG=False`, allowing the entire test suite and evaluation harness to run deterministically without paid API credentials. To run against live models, set `GITHUB_TOKEN` / `OPENAI_API_KEY` (`DEFAULT_MODEL_PROVIDER=github_models`) or run a local Ollama server (`DEFAULT_MODEL_PROVIDER=ollama`).

### 3. Run database migrations and initialize perspectives

```bash
python manage.py migrate
python manage.py initialize_llm_roles
```

### 4. Run verification & test suites

Run the zero-dependency standalone engine & evaluation verification suite:

```bash
python3 verify_engine.py
```

Run the Django and engine suite with the CI branch-coverage floor:

```bash
pytest --cov=ai_app --cov-branch --cov-report=term:skip-covered --cov-fail-under=80
ruff check .
ruff format --check .
mypy ai_app ai_project
python manage.py makemigrations --check --dry-run
```

Run the evaluation benchmark CLI:

```bash
python manage.py run_evaluation --provider fake --output reports/latest_evaluation_report.json
```

---

## Synthetic Structural Benchmark

Running `python3 verify_engine.py` (or `python manage.py run_evaluation --provider fake`) executes four benchmark cases with a deterministic fake provider. The table shows how the current structural rubric behaves across Strategies A, B, and C:

| Strategy | Mean Structural Score (0–5) | Disagreement Marker Score (0–5) | Mean Tokens | Rubric Points / 1k Tokens | Observation |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`single_model_baseline`** | 1.91 | 2.00 | 377.5 | **5.06** | Lowest simulated token use. |
| **`independent_perspectives`** | 4.50 | 4.25 | 2,990.2 | 1.50 | More rubric markers at 7.9x baseline tokens. |
| **`deliberative_exchange`** | **4.77** | **5.00** | 5,942.0 | 0.80 | Highest rubric score at 15.7x baseline tokens. |

The rubric rewards explicit disagreements, critiques, and uncertainty fields, so multi-perspective strategies have a structural advantage. The fake provider and its judge are not independent evidence of answer quality. Real model comparisons and independent human review are needed before claiming that one strategy is more useful.

---

## HTTP API Reference

### 1. List or Register Perspectives
- **`GET /ai/perspectives/?domain=software_architecture&include_historical=true`**
- **`POST /ai/perspectives/`**: Register a custom `PerspectiveSpec`.

### 2. Start a Structured Deliberation
- **`POST /ai/deliberate/`**
```json
{
  "question": "Should our 3-person team adopt microservices or keep a modular Django monolith with PostgreSQL?",
  "strategy": "deliberative_exchange",
  "domain": "software_architecture",
  "perspectives": ["Systems Pragmatist", "Security & Trust Auditor", "Domain Boundary Architect"],
  "evidence": [
    {
      "source_id": "EV-1",
      "title": "Traffic Profile",
      "content": "2,000 requests/day with 5-15s LLM latency."
    }
  ]
}
```

### 3. Stream Deliberation Progress (NDJSON)
- **`POST /ai/deliberate/stream/`**: Streams newline-delimited JSON events (`run_started`, `perspectives_selected`, `perspective_analysis`, `perspective_critique`, `synthesis_completed`, `complete`).

### 4. Inspect & Evaluate Persisted Runs
- **`GET /ai/runs/`** (requires an authenticated session, or a configured API key plus `X-Perspective-User`)
- **`GET /ai/runs/<run_id>/`** (enforces per-user ownership)
- **`POST /ai/evaluate/`**: Score a completed `run_id` against domain rubrics and attach optional `human_review_notes`.
- **`POST /ai/compare/`**: Run Strategies A, B, and C side-by-side on a question and return token use and structural rubric comparisons.

### 5. Legacy Prototype Endpoints (Preserved & Hardened)
- **`GET /ai/roles/`**
- **`POST /ai/ask-role/`** (no longer crashes if `testuser` is absent; scopes history to requesting user)
- **`POST /ai/full-dialogue/`**
- **`POST /ai/stream-dialogue/`**
- **`GET /ai/history/`** (requires an authenticated session, or a configured API key plus `X-Perspective-User`)

---

## Security, Frontend Status & Known Limitations

- **Frontend Status**: The historical 2024 README referenced a separate `yogimathius/frontend` repository that is unavailable. Perspective Loom operates as a headless API, CLI evaluation runner, and MCP-ready library.
- **Authentication & Isolation**: Set `REQUIRE_AUTH=True` and `PERSPECTIVE_LOOM_API_KEY=<secret>` in deployed environments. Private reads require an authenticated Django session or the configured API key. `X-Perspective-User` selects a record scope for a trusted API client; it does not authenticate an end user. The shared API key is a service credential and must stay server-side. This prototype does not yet provide public multi-user authentication.
- **CSRF**: Mutating requests made with an authenticated Django session require a CSRF token. Header-key API clients do not use session cookies and may omit it.
- **Retention**: `python manage.py prune_expired_records --dry-run` previews deletion; run without `--dry-run` to remove history and deliberation runs older than `DATA_RETENTION_DAYS` (default 90). This command is manual until you schedule it. `python manage.py reset_history` deletes all conversation history regardless of age.
- **Inherited texts**: The archived [`datasets/spiritual_texts`](datasets/spiritual_texts/README.md) corpus is not used by the current engine or benchmark. Its manifest records checksums and source notices; reuse rights still need review before the texts enter a product or dataset.
- **Database**: Uses SQLite (`db.sqlite3`) by default for zero-setup local development and CI, and supports PostgreSQL via `DATABASE_URL=postgresql://user:pass@host:5432/dbname`.
- **Architecture & PR Details**: See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`PR_ROADMAP.md`](PR_ROADMAP.md).
