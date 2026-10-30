#!/usr/bin/env bash
# Creates one modernization branch with 5 focused, reviewable commits.
# Run from the repository root: bash scripts/create_pr_branches.sh

set -euo pipefail

cd "$(dirname "$0")/.."

git diff --check
if ! git diff --cached --quiet; then
    echo "The index already contains staged changes. Unstage them before running this script." >&2
    exit 1
fi

git checkout -b modernize/perspective-loom-platform

# 1. Foundation: dependencies, security, settings, and CI
git add requirements.txt requirements-dev.txt pyproject.toml .env.example .gitignore .github/workflows/ci.yml \
        ai_project/settings.py ai_app/security.py \
        ai_app/views/dialogue.py ai_app/views/history.py ai_app/views/roles.py \
        ai_app/management/commands/initialize_mock_user.py
git commit -m "foundation: stabilize runtime, security, and testing configuration"

# 2. Architecture: typed schemas and model provider abstraction
git add ai_app/engine/__init__.py ai_app/engine/schemas.py ai_app/engine/providers.py \
        ai_app/services/model_rotation.py
git commit -m "architecture: introduce typed deliberation schemas and provider abstraction"

# 3. Features: perspective registry, deliberation orchestrator, and persistence
git add ai_app/engine/perspectives.py ai_app/engine/orchestrator.py \
        ai_app/models/llm_role.py ai_app/models/deliberation.py ai_app/models/__init__.py \
        ai_app/migrations/0004_deliberationrun_and_role_metadata.py \
        ai_app/management/commands/initialize_llm_roles.py \
        ai_app/services/response_formatter.py
git commit -m "features: implement perspective registry, deliberation engine, and run persistence"

# 4. Evaluation: benchmark dataset, domain rubrics, and experiment runner
git add datasets/eval_benchmark.json datasets/latest_evaluation_report.json \
        ai_app/evaluation/__init__.py ai_app/evaluation/evaluator.py ai_app/evaluation/runner.py \
        ai_app/management/commands/run_evaluation.py
git commit -m "evaluation: add reproducible baseline vs deliberation benchmark laboratory"

# 5. Developer experience: REST/streaming APIs, MCP adapter, tests, and documentation
git add ai_app/views/deliberation.py ai_app/urls.py ai_app/mcp_tools.py \
        ai_app/tests.py verify_engine.py \
        ai_app/admin.py ai_app/management/commands/reset_history.py \
        ai_app/services/dialogue_generator.py ai_project/urls.py \
        README.md ARCHITECTURE.md PR_ROADMAP.md scripts/create_pr_branches.sh
git commit -m "developer-experience: add deliberation APIs, MCP tools, test suite, and docs"

echo ""
echo "Successfully created 5 reviewable commits on branch 'modernize/perspective-loom-platform':"
git log --oneline -n 5
