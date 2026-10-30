#!/usr/bin/env python3
"""
Standalone verification & benchmark runner for Perspective Loom.

Executes with zero third-party dependencies (using Python's standard library)
or inside a full Django virtualenv. Verifies:
1. PerspectiveSpec validation and registry lookup across all 13 perspectives
2. Strategy A (`single_model_baseline`), Strategy B (`independent_perspectives`),
   and Strategy C (`deliberative_exchange`)
3. Partial-failure resilience when a perspective provider call fails
4. Secret redaction filter and DATABASE_URL parsing
5. MCP tool surface (`list_perspectives`, `deliberate`, `compare_deliberations`,
   `evaluate_deliberation`) and Nexus Flow `SymbolOntologyEntry`
6. Full reproducible evaluation benchmark across all 4 domain cases
"""

from __future__ import annotations

import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
from ai_project.settings import SensitiveDataRedactionFilter, _parse_database_url

ROOT_DIR = Path(__file__).resolve().parent


class StandaloneEngineVerificationTests(unittest.TestCase):
    def test_01_registry_preserves_historical_and_technical_perspectives(self) -> None:
        all_specs = DEFAULT_REGISTRY.list_all()
        self.assertEqual(len(all_specs), 13)
        historical = [s for s in all_specs if s.is_historical_persona]
        technical = [s for s in all_specs if not s.is_historical_persona]
        self.assertEqual(len(historical), 9)
        self.assertEqual(len(technical), 4)

    def test_02_strategies_a_b_c_and_trace_telemetry(self) -> None:
        engine = DeliberationEngine(provider=FakeModelProvider())
        ev = [EvidenceItem(source_id="EV-1", title="Constraint", content="3-person team")]

        res_a = engine.run(
            DeliberationRequest(
                question="Should we adopt microservices or a modular monolith?",
                strategy=DeliberationStrategy.SINGLE_MODEL_BASELINE.value,
                domain="software_architecture",
                evidence=ev,
            )
        )
        self.assertEqual(res_a.status, "completed")
        self.assertEqual(len(res_a.independent_analyses), 0)

        res_b = engine.run(
            DeliberationRequest(
                question="Should we adopt microservices or a modular monolith?",
                strategy=DeliberationStrategy.INDEPENDENT_PERSPECTIVES.value,
                domain="software_architecture",
                max_perspectives=3,
                evidence=ev,
            )
        )
        self.assertEqual(res_b.status, "completed")
        self.assertEqual(len(res_b.independent_analyses), 3)
        self.assertEqual(len(res_b.critiques), 0)

        res_c = engine.run(
            DeliberationRequest(
                question="Should we adopt microservices or a modular monolith?",
                strategy=DeliberationStrategy.DELIBERATIVE_EXCHANGE.value,
                domain="software_architecture",
                max_perspectives=3,
                evidence=ev,
            )
        )
        self.assertEqual(res_c.status, "completed")
        self.assertEqual(len(res_c.independent_analyses), 3)
        self.assertEqual(len(res_c.critiques), 3)
        self.assertGreater(res_c.trace.total_tokens, res_b.trace.total_tokens)

    def test_03_partial_failure_degrades_gracefully(self) -> None:
        flaky = FakeModelProvider(fail_on_roles={"Security & Trust Auditor"})
        engine = DeliberationEngine(provider=flaky)
        res = engine.run(
            DeliberationRequest(
                question="Review auth and database boundaries.",
                strategy=DeliberationStrategy.DELIBERATIVE_EXCHANGE.value,
                perspective_names=[
                    "Systems Pragmatist",
                    "Security & Trust Auditor",
                    "Domain Boundary Architect",
                ],
            )
        )
        self.assertEqual(res.status, "partial_failure")
        self.assertGreaterEqual(res.trace.partial_failures, 1)
        self.assertTrue(bool(res.synthesis.summary))

    def test_04_security_settings_and_ollama_model_fix(self) -> None:
        pg = _parse_database_url("postgres://u:p@localhost:5432/loom")
        self.assertEqual(pg["ENGINE"], "django.db.backends.postgresql")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret-key-123456"}):
            filt = SensitiveDataRedactionFilter()
            rec = logging.LogRecord("ai_app", logging.INFO, __file__, 1, "Key=sk-secret-key-123456", (), None)
            filt.filter(rec)
            self.assertNotIn("sk-secret-key-123456", rec.msg)
            self.assertIn("[REDACTED_SECRET]", rec.msg)

        ollama_prov = OllamaProvider(default_model="mistral-nemo")
        self.assertEqual(ollama_prov.default_model, "mistral-nemo")

    def test_05_mcp_tools_and_nexus_flow_ontology(self) -> None:
        entry = SymbolOntologyEntry(
            symbol_id="SYM-01",
            term="Cracked Mirror",
            user_associations=["identity shift"],
            cultural_motifs=["initiation"],
        )
        out = invoke_mcp_tool(
            "deliberate",
            {
                "question": "Reflect on the cracked mirror symbol.",
                "strategy": "independent_perspectives",
                "domain": "symbolic_contemplative",
                "perspectives": ["Alchemist", "Existential Navigator"],
                "symbol_ontology": [entry.to_dict()],
            },
        )
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["evidence_supplied"][0]["source_id"], "ONTOLOGY-SYM-01")


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(StandaloneEngineVerificationTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)

    print("\nRunning Reproducible Evaluation Benchmark Suite (Strategies A vs B vs C)...")
    exp_runner = ExperimentRunner(provider_name="fake")
    report = exp_runner.run_benchmark_suite()
    report_path = ROOT_DIR / "datasets" / "latest_evaluation_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for strat, m in report["aggregate_by_strategy"].items():
        print(
            f"  [{strat:26s}] quality={m['mean_overall_quality_score']:.2f}/5.0 | "
            f"disagreement={m['mean_disagreement_preservation_score']:.2f}/5.0 | "
            f"mean_tokens={m['mean_tokens']:6.1f} | "
            f"quality/1k_tok={m['mean_quality_per_1k_tokens']:.2f}"
        )
    print(f"\nConclusion: {report['overall_conclusion']}")
    print(f"Saved full reproducible benchmark artifact to: {report_path}")


if __name__ == "__main__":
    main()
