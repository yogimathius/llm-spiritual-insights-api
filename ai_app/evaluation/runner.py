"""
Reproducible Experiment Runner comparing Deliberation Strategies (A, B, and C).

Executes benchmark cases across:
- Strategy A: `single_model_baseline`
- Strategy B: `independent_perspectives`
- Strategy C: `deliberative_exchange`

Records traces, token counts, costs, latencies, and structural rubric scorecards.
The deterministic fake-provider run is a smoke test, not evidence of answer quality.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_app.engine.orchestrator import DeliberationEngine
from ai_app.engine.providers import ModelProvider, get_model_provider
from ai_app.engine.schemas import DeliberationRequest, DeliberationStrategy, EvidenceItem
from ai_app.evaluation.evaluator import DeliberationEvaluator

DEFAULT_BENCHMARK_PATH = (
    Path(__file__).resolve().parent.parent.parent / "datasets" / "eval_benchmark.json"
)


class ExperimentRunner:
    """Runs controlled comparisons across single-model and multi-perspective strategies."""

    STRATEGIES = [
        DeliberationStrategy.SINGLE_MODEL_BASELINE.value,
        DeliberationStrategy.INDEPENDENT_PERSPECTIVES.value,
        DeliberationStrategy.DELIBERATIVE_EXCHANGE.value,
    ]

    def __init__(
        self,
        *,
        provider: ModelProvider | None = None,
        provider_name: str = "fake",
        model_name: str | None = None,
    ) -> None:
        self.provider = provider or get_model_provider(provider_name, model_name=model_name)
        self.engine = DeliberationEngine(provider=self.provider)
        self.evaluator = DeliberationEvaluator(judge_provider=self.provider)

    def compare_on_question(
        self,
        *,
        question: str,
        domain: str = "research_philosophy",
        perspective_names: list[str] | None = None,
        evidence: list[EvidenceItem] | None = None,
        required_concepts: list[str] | None = None,
        strategies: list[str] | None = None,
    ) -> dict[str, Any]:
        active_strategies = strategies or self.STRATEGIES
        strategy_runs: dict[str, Any] = {}

        for strategy in active_strategies:
            req = DeliberationRequest(
                question=question,
                strategy=strategy,
                domain=domain,
                perspective_names=list(perspective_names or []),
                evidence=list(evidence or []),
                provider_name=self.provider.provider_name,
                model_name=self.provider.default_model,
            )
            run_result = self.engine.run(req)
            scorecard = self.evaluator.evaluate_run(
                run_result,
                required_concepts=required_concepts,
            )
            strategy_runs[strategy] = {
                "run": run_result.to_dict(),
                "scorecard": scorecard.to_dict(),
            }

        analysis = self._analyze_tradeoffs(strategy_runs)
        return {
            "question": question,
            "domain": domain,
            "provider": self.provider.provider_name,
            "model": self.provider.default_model,
            "evaluation_method": (
                "synthetic_structural"
                if self.provider.provider_name == "fake"
                else "automated_structural"
            ),
            "strategies": strategy_runs,
            "comparative_findings": analysis,
        }

    def run_benchmark_suite(
        self,
        benchmark_path: Path | None = None,
    ) -> dict[str, Any]:
        path = benchmark_path or DEFAULT_BENCHMARK_PATH
        cases = json.loads(path.read_text(encoding="utf-8"))

        case_results = []
        agg_by_strategy: dict[str, dict[str, float]] = {
            s: {
                "count": 0.0,
                "total_quality": 0.0,
                "total_disagreement_score": 0.0,
                "total_tokens": 0.0,
                "total_latency_ms": 0.0,
                "total_cost_usd": 0.0,
            }
            for s in self.STRATEGIES
        }

        for case in cases:
            evidence_items = [
                EvidenceItem(
                    source_id=ev["source_id"],
                    title=ev["title"],
                    content=ev["content"],
                    source_type=ev.get("source_type", "benchmark_constraint"),
                    verified=ev.get("verified", True),
                )
                for ev in case.get("evidence", [])
            ]
            comparison = self.compare_on_question(
                question=case["question"],
                domain=case["domain"],
                perspective_names=case.get("perspectives", []),
                evidence=evidence_items,
                required_concepts=case.get("required_concepts", []),
            )
            comparison["case_id"] = case["case_id"]
            comparison["evaluation_focus"] = case.get("evaluation_focus", "")
            case_results.append(comparison)

            for strat, bundle in comparison["strategies"].items():
                sc = bundle["scorecard"]
                agg = agg_by_strategy[strat]
                agg["count"] += 1
                agg["total_quality"] += sc["overall_quality_score"]
                agg["total_disagreement_score"] += sc["disagreement_preservation_score"]
                agg["total_tokens"] += sc["total_tokens"]
                agg["total_latency_ms"] += sc["latency_ms"]
                agg["total_cost_usd"] += sc["estimated_cost_usd"]

        summary_table: dict[str, Any] = {}
        for strat, agg in agg_by_strategy.items():
            cnt = max(1.0, agg["count"])
            avg_quality = round(agg["total_quality"] / cnt, 2)
            avg_tokens = round(agg["total_tokens"] / cnt, 1)
            summary_table[strat] = {
                "cases_evaluated": int(agg["count"]),
                "mean_overall_quality_score": avg_quality,
                "mean_disagreement_preservation_score": round(
                    agg["total_disagreement_score"] / cnt, 2
                ),
                "mean_tokens": avg_tokens,
                "mean_latency_ms": round(agg["total_latency_ms"] / cnt, 2),
                "total_estimated_cost_usd": round(agg["total_cost_usd"], 6),
                "mean_quality_per_1k_tokens": round(
                    (avg_quality / max(1.0, avg_tokens)) * 1000.0, 2
                ),
            }

        return {
            "benchmark_version": "1.0.0",
            "executed_at": datetime.now(UTC).isoformat(),
            "provider": self.provider.provider_name,
            "model": self.provider.default_model,
            "evaluation_method": (
                "synthetic_structural"
                if self.provider.provider_name == "fake"
                else "automated_structural"
            ),
            "aggregate_by_strategy": summary_table,
            "overall_conclusion": self._build_overall_conclusion(
                summary_table, provider_name=self.provider.provider_name
            ),
            "cases": case_results,
        }

    @staticmethod
    def _analyze_tradeoffs(strategy_runs: dict[str, Any]) -> dict[str, Any]:
        base = strategy_runs.get(DeliberationStrategy.SINGLE_MODEL_BASELINE.value, {}).get(
            "scorecard"
        )
        indep = strategy_runs.get(DeliberationStrategy.INDEPENDENT_PERSPECTIVES.value, {}).get(
            "scorecard"
        )
        delib = strategy_runs.get(DeliberationStrategy.DELIBERATIVE_EXCHANGE.value, {}).get(
            "scorecard"
        )

        if not (base and indep and delib):
            return {"summary": "Partial strategy subset executed."}

        base_tokens = max(1, base["total_tokens"])
        indep_token_mult = round(indep["total_tokens"] / base_tokens, 2)
        delib_token_mult = round(delib["total_tokens"] / base_tokens, 2)

        quality_delta_indep = round(
            indep["overall_quality_score"] - base["overall_quality_score"], 2
        )
        quality_delta_delib = round(
            delib["overall_quality_score"] - base["overall_quality_score"], 2
        )

        # Compare structural rubric scores and token counts without inferring usefulness.
        if quality_delta_delib <= 0.15:
            recommendation = (
                "The baseline has comparable structural rubric coverage in this case. "
                f"Deliberative exchange used {delib_token_mult}x its tokens. "
                "A usefulness judgment requires independent human review."
            )
        elif delib["overall_quality_score"] - indep["overall_quality_score"] <= 0.10:
            recommendation = (
                f"Independent perspectives scored {quality_delta_indep} rubric points above the baseline "
                f"at {indep_token_mult}x its tokens. Deliberative exchange used {delib_token_mult}x "
                "baseline tokens for a small additional structural score."
            )
        else:
            recommendation = (
                f"Deliberative exchange scored {quality_delta_delib} rubric points above the baseline "
                f"at {delib_token_mult}x its tokens. The score reflects structural markers, "
                "not independently judged answer quality."
            )

        return {
            "quality_delta_independent_vs_baseline": quality_delta_indep,
            "quality_delta_deliberative_vs_baseline": quality_delta_delib,
            "token_multiplier_independent_vs_baseline": indep_token_mult,
            "token_multiplier_deliberative_vs_baseline": delib_token_mult,
            "most_token_efficient_strategy": max(
                [base, indep, delib], key=lambda s: s["quality_per_1k_tokens"]
            )["strategy"],
            "highest_quality_strategy": max(
                [base, indep, delib], key=lambda s: s["overall_quality_score"]
            )["strategy"],
            "finding": recommendation,
        }

    @staticmethod
    def _build_overall_conclusion(summary_table: dict[str, Any], *, provider_name: str) -> str:
        b = summary_table.get(DeliberationStrategy.SINGLE_MODEL_BASELINE.value, {})
        i = summary_table.get(DeliberationStrategy.INDEPENDENT_PERSPECTIVES.value, {})
        d = summary_table.get(DeliberationStrategy.DELIBERATIVE_EXCHANGE.value, {})
        if not (b and i and d):
            return "Benchmark completed on partial strategy set."

        token_ratio_i = round(i["mean_tokens"] / max(1.0, b["mean_tokens"]), 1)
        token_ratio_d = round(d["mean_tokens"] / max(1.0, b["mean_tokens"]), 1)
        prefix = (
            "Synthetic smoke test with a deterministic fake provider. "
            if provider_name == "fake"
            else "Automated structural benchmark. "
        )
        return (
            prefix
            + f"Across {b['cases_evaluated']} cases, independent perspectives used {token_ratio_i}x "
            f"and deliberative exchange used {token_ratio_d}x the baseline tokens. "
            f"Their structural rubric scores were {i['mean_overall_quality_score']} and "
            f"{d['mean_overall_quality_score']}, versus {b['mean_overall_quality_score']} for the baseline. "
            "These scores do not establish answer quality or usefulness; compare real model outputs "
            "with independent human review before making those claims."
        )
