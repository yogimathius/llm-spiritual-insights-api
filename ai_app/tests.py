"""
Comprehensive Unit & Integration Test Suite for Perspective Loom.

Covers:
1. Phase 1 Foundation & Security:
   - Environment-driven settings, secret redaction filter, and DATABASE_URL parsing
   - Removal of hardcoded `testuser` crash on `/ai/ask-role/`
   - Strict user authentication and data isolation on `/ai/history/` and `/ai/runs/`
   - API key enforcement when `PERSPECTIVE_LOOM_API_KEY` or `REQUIRE_AUTH` is enabled
2. Phase 2 Deliberation Engine & Versioned Perspectives:
   - Preservation of all 9 historical contemplative roles + new architecture/research roles
   - Strategy A (`single_model_baseline`), Strategy B (`independent_perspectives`), and Strategy C (`deliberative_exchange`)
   - Partial-failure resilience when an individual perspective provider call fails
   - Ollama model selection consistency (never hardcoding `llama2`)
   - NDJSON streaming progress and trace correlation
3. Phase 3 Evaluation Laboratory:
   - Domain-specific rubric scoring, evidence separation, and disagreement preservation
   - Reproducible comparison across Strategies A, B, and C with cost/token trade-off findings
4. Phase 4 APIs & MCP Contracts:
   - End-to-end HTTP endpoints (`/ai/perspectives/`, `/ai/deliberate/`, `/ai/deliberate/stream/`, `/ai/runs/`, `/ai/evaluate/`, `/ai/compare/`)
   - MCP tool surface (`list_perspectives`, `deliberate`, `compare_deliberations`, `evaluate_deliberation`) and Nexus Flow `SymbolOntologyEntry`
"""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from ai_app.engine.orchestrator import DeliberationEngine
from ai_app.engine.perspectives import DEFAULT_REGISTRY
from ai_app.engine.providers import FakeModelProvider, OllamaProvider
from ai_app.engine.schemas import (
    DeliberationRequest,
    DeliberationStrategy,
    EvidenceItem,
)
from ai_app.evaluation.runner import ExperimentRunner
from ai_app.mcp_tools import SymbolOntologyEntry, invoke_mcp_tool
from ai_app.models.deliberation import DeliberationRun
from ai_app.models.history import History
from ai_app.models.llm_role import LLMRole
from ai_app.models.user import User
from ai_project.settings import SensitiveDataRedactionFilter, _parse_database_url


class FoundationSecurityTests(TestCase):
    """Phase 1 tests: configuration, secret redaction, auth, and user history isolation."""

    def setUp(self) -> None:
        self.client = Client()
        call_command("initialize_llm_roles")

    def test_database_url_parser_supports_postgres_and_sqlite(self) -> None:
        pg_cfg = _parse_database_url("postgresql://loom_user:secret_pw@db.internal:5432/loom_prod")
        self.assertEqual(pg_cfg["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(pg_cfg["NAME"], "loom_prod")
        self.assertEqual(pg_cfg["USER"], "loom_user")
        self.assertEqual(pg_cfg["HOST"], "db.internal")
        self.assertEqual(pg_cfg["PORT"], "5432")

        sqlite_cfg = _parse_database_url("sqlite:///tmp/test_loom.sqlite3")
        self.assertEqual(sqlite_cfg["ENGINE"], "django.db.backends.sqlite3")

    def test_sensitive_log_redaction_filter_scrubs_secrets(self) -> None:
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_super_secret_token_99999"}):
            redactor = SensitiveDataRedactionFilter()
            record = logging.LogRecord(
                name="ai_app",
                level=logging.ERROR,
                pathname=__file__,
                lineno=10,
                msg="Failed auth with token ghp_super_secret_token_99999 on request",
                args=(),
                exc_info=None,
            )
            redactor.filter(record)
            self.assertNotIn("ghp_super_secret_token_99999", record.msg)
            self.assertIn("[REDACTED_SECRET]", record.msg)

    def test_ask_role_succeeds_without_preexisting_testuser(self) -> None:
        """Verifies the historical `User.objects.get(username='testuser')` crash is resolved."""
        User.objects.all().delete()
        response = self.client.post(
            "/ai/ask-role/",
            data=json.dumps(
                {
                    "prompt": "How does quantum observation relate to meaning?",
                    "role": "Quantum Philosopher",
                }
            ),
            content_type="application/json",
            HTTP_X_PERSPECTIVE_USER="alice",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("response", payload)
        self.assertEqual(History.objects.filter(user__username="alice").count(), 1)

    @override_settings(PERSPECTIVE_LOOM_API_KEY="test-service-key")
    def test_history_endpoint_rejects_unauthenticated_and_isolates_users(self) -> None:
        """Verifies users cannot read each other's conversation history."""
        role = LLMRole.objects.get(name="Quantum Philosopher")
        alice = User.objects.create(username="alice", email="alice@example.com")
        bob = User.objects.create(username="bob", email="bob@example.com")
        History.objects.create(user=alice, role=role, prompt="Alice secret prompt", response="Alice reply")
        History.objects.create(user=bob, role=role, prompt="Bob private prompt", response="Bob reply")

        # Unscoped request must be rejected with 401
        unauth_resp = self.client.get("/ai/history/")
        self.assertEqual(unauth_resp.status_code, 401)

        # Alice only sees Alice's history
        alice_resp = self.client.get(
            "/ai/history/", HTTP_X_PERSPECTIVE_USER="alice", HTTP_X_API_KEY="test-service-key"
        )
        self.assertEqual(alice_resp.status_code, 200)
        alice_items = alice_resp.json()["history"]
        self.assertEqual(len(alice_items), 1)
        self.assertEqual(alice_items[0]["prompt"], "Alice secret prompt")

        # Bob only sees Bob's history
        bob_resp = self.client.get(
            "/ai/history/", HTTP_X_PERSPECTIVE_USER="bob", HTTP_X_API_KEY="test-service-key"
        )
        self.assertEqual(bob_resp.status_code, 200)
        bob_items = bob_resp.json()["history"]
        self.assertEqual(len(bob_items), 1)
        self.assertEqual(bob_items[0]["prompt"], "Bob private prompt")

    def test_user_header_alone_cannot_authorize_private_history(self) -> None:
        response = self.client.get("/ai/history/", HTTP_X_PERSPECTIVE_USER="alice")
        self.assertEqual(response.status_code, 401)

    @override_settings(PERSPECTIVE_LOOM_API_KEY="top-secret-api-key")
    def test_api_key_enforcement_when_configured(self) -> None:
        blocked = self.client.post(
            "/ai/deliberate/",
            data=json.dumps({"question": "Test auth?"}),
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 401)

        allowed = self.client.post(
            "/ai/deliberate/",
            data=json.dumps({"question": "Test auth?"}),
            content_type="application/json",
            HTTP_X_API_KEY="top-secret-api-key",
        )
        self.assertEqual(allowed.status_code, 200)


class DeliberationEngineTests(TestCase):
    """Phase 2 tests: perspectives registry, Strategies A/B/C, partial failures, and provider fixes."""

    def test_all_nine_historical_roles_and_technical_roles_registered(self) -> None:
        historical_names = {
            "Christian Mystic",
            "Quantum Philosopher",
            "Alchemist",
            "Existential Navigator",
            "Void Explorer",
            "Time Weaver",
            "Desert Father",
            "Sufi Mystic",
            "Vedantic Sage",
        }
        registered_names = {s.name for s in DEFAULT_REGISTRY.list_all()}
        self.assertTrue(historical_names.issubset(registered_names))
        self.assertIn("Systems Pragmatist", registered_names)
        self.assertIn("Security & Trust Auditor", registered_names)
        self.assertIn("Domain Boundary Architect", registered_names)
        self.assertIn("Empirical Epistemologist", registered_names)

    def test_strategies_a_b_and_c_execution_and_trace_accounting(self) -> None:
        engine = DeliberationEngine(provider=FakeModelProvider())
        evidence = [
            EvidenceItem(
                source_id="EV-1",
                title="Latency SLO",
                content="p95 latency must stay below 10 seconds.",
            )
        ]

        # Strategy A: Single-Model Baseline
        req_a = DeliberationRequest(
            question="Should we use SQLite or PostgreSQL for multi-user deployment?",
            strategy=DeliberationStrategy.SINGLE_MODEL_BASELINE.value,
            domain="software_architecture",
            evidence=evidence,
        )
        res_a = engine.run(req_a)
        self.assertEqual(res_a.status, "completed")
        self.assertEqual(len(res_a.independent_analyses), 0)
        self.assertEqual(len(res_a.critiques), 0)
        self.assertGreater(res_a.trace.total_tokens, 0)

        # Strategy B: Independent Perspectives (no critique round)
        req_b = DeliberationRequest(
            question="Should we use SQLite or PostgreSQL for multi-user deployment?",
            strategy=DeliberationStrategy.INDEPENDENT_PERSPECTIVES.value,
            domain="software_architecture",
            max_perspectives=3,
            evidence=evidence,
        )
        res_b = engine.run(req_b)
        self.assertEqual(res_b.status, "completed")
        self.assertEqual(len(res_b.independent_analyses), 3)
        self.assertEqual(len(res_b.critiques), 0)
        self.assertGreater(len(res_b.synthesis.preserved_disagreements), 0)

        # Strategy C: Deliberative Exchange (independent analyses + critiques + synthesis)
        req_c = DeliberationRequest(
            question="Should we use SQLite or PostgreSQL for multi-user deployment?",
            strategy=DeliberationStrategy.DELIBERATIVE_EXCHANGE.value,
            domain="software_architecture",
            max_perspectives=3,
            evidence=evidence,
        )
        res_c = engine.run(req_c)
        self.assertEqual(res_c.status, "completed")
        self.assertEqual(len(res_c.independent_analyses), 3)
        self.assertEqual(len(res_c.critiques), 3)
        self.assertGreater(res_c.trace.total_tokens, res_b.trace.total_tokens)

    def test_partial_failure_semantics_when_one_perspective_fails(self) -> None:
        flaky_provider = FakeModelProvider(fail_on_roles={"Security & Trust Auditor"})
        engine = DeliberationEngine(provider=flaky_provider)
        req = DeliberationRequest(
            question="Evaluate authentication and database trade-offs.",
            strategy=DeliberationStrategy.DELIBERATIVE_EXCHANGE.value,
            perspective_names=[
                "Systems Pragmatist",
                "Security & Trust Auditor",
                "Domain Boundary Architect",
            ],
        )
        result = engine.run(req)
        self.assertEqual(result.status, "partial_failure")
        self.assertGreaterEqual(result.trace.partial_failures, 1)
        succeeded = [a for a in result.independent_analyses if a.status == "succeeded"]
        failed = [a for a in result.independent_analyses if a.status == "failed"]
        self.assertEqual(len(succeeded), 2)
        self.assertEqual(len(failed), 1)
        self.assertTrue(bool(result.synthesis.summary))

    def test_ollama_provider_respects_configured_model_name(self) -> None:
        provider = OllamaProvider(default_model="qwen2.5-coder:7b")
        self.assertEqual(provider.default_model, "qwen2.5-coder:7b")

    def test_ollama_provider_accepts_host_without_scheme(self) -> None:
        provider = OllamaProvider(host="127.0.0.1:11434")
        self.assertEqual(provider.host, "http://127.0.0.1:11434")


class EvaluationLaboratoryTests(TestCase):
    """Phase 3 tests: evaluation scorecard, benchmark suite, and comparative findings."""

    def test_evaluator_and_experiment_runner_compare_strategies(self) -> None:
        runner = ExperimentRunner(provider_name="fake")
        comparison = runner.compare_on_question(
            question="Should a 3-person team adopt microservices or a modular monolith?",
            domain="software_architecture",
            required_concepts=["modular monolith", "PostgreSQL", "timeout"],
        )
        self.assertIn("strategies", comparison)
        self.assertIn("comparative_findings", comparison)
        strategies = comparison["strategies"]
        self.assertIn("single_model_baseline", strategies)
        self.assertIn("independent_perspectives", strategies)
        self.assertIn("deliberative_exchange", strategies)

        base_sc = strategies["single_model_baseline"]["scorecard"]
        delib_sc = strategies["deliberative_exchange"]["scorecard"]
        self.assertGreater(
            delib_sc["disagreement_preservation_score"],
            base_sc["disagreement_preservation_score"],
        )
        self.assertGreater(delib_sc["total_tokens"], base_sc["total_tokens"])

    def test_full_benchmark_suite_executes_reproducibly(self) -> None:
        runner = ExperimentRunner(provider_name="fake")
        report = runner.run_benchmark_suite()
        self.assertEqual(len(report["cases"]), 4)
        self.assertIn("overall_conclusion", report)
        self.assertIn("single_model_baseline", report["aggregate_by_strategy"])


class ApiAndMcpIntegrationTests(TestCase):
    """Phase 4 tests: REST/streaming endpoints, run persistence, and MCP tool invocation."""

    def setUp(self) -> None:
        self.client = Client()
        call_command("initialize_llm_roles")

    @override_settings(PERSPECTIVE_LOOM_API_KEY="test-service-key")
    def test_deliberate_and_evaluate_http_workflow(self) -> None:
        # 1. Start a deliberation run
        resp = self.client.post(
            "/ai/deliberate/",
            data=json.dumps(
                {
                    "question": "What does a dream of a flooded labyrinth with a cracked mirror suggest?",
                    "strategy": "deliberative_exchange",
                    "domain": "symbolic_contemplative",
                    "perspectives": ["Alchemist", "Existential Navigator", "Void Explorer"],
                }
            ),
            content_type="application/json",
            HTTP_X_PERSPECTIVE_USER="researcher_1",
            HTTP_X_API_KEY="test-service-key",
        )
        self.assertEqual(resp.status_code, 200)
        run_data = resp.json()
        run_id = run_data["run_id"]
        self.assertEqual(run_data["status"], "completed")
        self.assertEqual(len(run_data["independent_analyses"]), 3)

        # 2. Retrieve run detail
        detail_resp = self.client.get(
            f"/ai/runs/{run_id}/",
            HTTP_X_PERSPECTIVE_USER="researcher_1",
            HTTP_X_API_KEY="test-service-key",
        )
        self.assertEqual(detail_resp.status_code, 200)

        # 3. Verify another user cannot access researcher_1's run
        forbidden_resp = self.client.get(
            f"/ai/runs/{run_id}/",
            HTTP_X_PERSPECTIVE_USER="intruder_user",
            HTTP_X_API_KEY="test-service-key",
        )
        self.assertEqual(forbidden_resp.status_code, 403)

        # 4. Evaluate the completed run
        eval_resp = self.client.post(
            "/ai/evaluate/",
            data=json.dumps(
                {
                    "run_id": run_id,
                    "required_concepts": ["ambiguity", "symbolic", "association"],
                    "human_review_notes": "Preserves user agency and avoids dogmatic dream dictionary claims.",
                }
            ),
            content_type="application/json",
            HTTP_X_PERSPECTIVE_USER="researcher_1",
            HTTP_X_API_KEY="test-service-key",
        )
        self.assertEqual(eval_resp.status_code, 200)
        eval_payload = eval_resp.json()["evaluation"]
        self.assertGreater(eval_payload["overall_quality_score"], 0.0)
        self.assertEqual(
            eval_payload["human_review_notes"],
            "Preserves user agency and avoids dogmatic dream dictionary claims.",
        )

    def test_streaming_deliberation_ndjson_events(self) -> None:
        resp = self.client.post(
            "/ai/deliberate/stream/",
            data=json.dumps(
                {
                    "question": "Compare SQLite and PostgreSQL for concurrent writes.",
                    "strategy": "independent_perspectives",
                    "domain": "software_architecture",
                    "max_perspectives": 2,
                }
            ),
            content_type="application/json",
            HTTP_X_PERSPECTIVE_USER="streamer",
        )
        self.assertEqual(resp.status_code, 200)
        lines = [
            json.loads(line.decode("utf-8"))
            for line in resp.streaming_content
            if line.strip()
        ]
        event_types = [e["type"] for e in lines]
        self.assertEqual(event_types[0], "run_started")
        self.assertIn("perspectives_selected", event_types)
        self.assertIn("perspective_analysis", event_types)
        self.assertIn("synthesis_completed", event_types)
        self.assertEqual(event_types[-1], "complete")
        self.assertEqual(DeliberationRun.objects.filter(user__username="streamer").count(), 1)

    def test_mcp_tools_and_nexus_flow_symbol_ontology_hook(self) -> None:
        perspectives_out = invoke_mcp_tool(
            "list_perspectives", {"domain": "symbolic_contemplative"}
        )
        self.assertGreaterEqual(len(perspectives_out["perspectives"]), 5)

        ontology_entry = SymbolOntologyEntry(
            symbol_id="SYM-LABYRINTH-01",
            term="Flooded Labyrinth",
            user_associations=["career transition", "feeling submerged yet searching"],
            cultural_motifs=["initiation threshold", "non-linear passage"],
        )
        delib_out = invoke_mcp_tool(
            "deliberate",
            {
                "question": "How can I reflect on this labyrinth dream?",
                "strategy": "independent_perspectives",
                "domain": "symbolic_contemplative",
                "perspectives": ["Alchemist", "Existential Navigator"],
                "symbol_ontology": [ontology_entry.to_dict()],
            },
        )
        self.assertEqual(delib_out["status"], "completed")
        self.assertEqual(delib_out["evidence_supplied"][0]["source_id"], "ONTOLOGY-SYM-LABYRINTH-01")
