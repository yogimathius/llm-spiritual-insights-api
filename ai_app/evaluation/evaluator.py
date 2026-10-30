"""
Evaluation Rubrics, Heuristic Scorers, and LLM-Judge Assessment for Perspective Loom.

Evaluates deliberation runs without manufacturing favorable conclusions:
- Technical domains (`software_architecture`) prioritize constraint satisfaction,
  evidence grounding, trade-off clarity, and cost/latency efficiency.
- Research & Symbolic domains (`research_philosophy`, `symbolic_contemplative`)
  prioritize epistemic boundary clarity (distinguishing fact from metaphor),
  interpretive breadth, preservation of disagreement, and explicit uncertainty.
- LLM-judge evaluations record the judge model, rubric version, and position-swap
  consistency, and explicitly note that judge scores are heuristic proxies rather
  than objective truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ai_app.engine.orchestrator import parse_structured_json
from ai_app.engine.providers import ModelProvider, get_model_provider
from ai_app.engine.schemas import DeliberationRunResult

RUBRIC_VERSION = "1.0.0"

DOMAIN_RUBRICS: dict[str, dict[str, str]] = {
    "software_architecture": {
        "constraint_satisfaction": "Addresses stated workload, team size, and operational constraints.",
        "evidence_grounding": "References supplied evidence items and separates verified metrics from assumptions.",
        "tradeoff_depth": "Articulates concrete failure modes, migration triggers, and competing architectural tensions.",
        "epistemic_honesty": "Avoids silver-bullet claims and explicitly states operational limitations.",
    },
    "research_philosophy": {
        "constraint_satisfaction": "Addresses the core epistemological or philosophical question directly.",
        "evidence_grounding": "Separates empirical scientific evidence from philosophical interpretation or analogy.",
        "tradeoff_depth": "Preserves genuine philosophical disagreements across competing methodologies.",
        "epistemic_honesty": "Flags unfalsifiable claims and avoids presenting speculation as established fact.",
    },
    "symbolic_contemplative": {
        "constraint_satisfaction": "Offers multi-layered symbolic and contemplative lenses relevant to the prompt.",
        "evidence_grounding": "Honors user context and prioritizes the inquirer's own associations over fixed dogma.",
        "tradeoff_depth": "Preserves ambiguity and contrasts distinct contemplative/existential viewpoints.",
        "epistemic_honesty": "Explicitly labels symbolic/metaphorical interpretations and avoids clinical or factual overreach.",
    },
}


@dataclass
class EvaluationScorecard:
    """Structured evaluation result for a single deliberation run."""

    run_id: str
    strategy: str
    domain: str
    rubric_version: str = RUBRIC_VERSION
    # Deterministic structural & epistemic checks (0.0 - 5.0 scale)
    constraint_coverage_score: float = 0.0
    evidence_separation_score: float = 0.0
    disagreement_preservation_score: float = 0.0
    uncertainty_acknowledgment_score: float = 0.0
    overall_quality_score: float = 0.0
    # Efficiency & telemetry metrics
    latency_ms: float = 0.0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    quality_per_1k_tokens: float = 0.0
    # Optional LLM Judge metadata
    judge_model: str | None = None
    judge_scores: dict[str, float] = field(default_factory=dict)
    judge_rationale: str = ""
    epistemic_disclaimer: str = (
        "Automated rubric and judge scores measure structural coverage, epistemic boundary "
        "markers, and trade-off articulation; they are heuristic indicators, not objective truth."
    )
    human_review_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeliberationEvaluator:
    """Evaluates a completed `DeliberationRunResult` against domain rubrics."""

    def __init__(self, judge_provider: ModelProvider | None = None) -> None:
        self.judge_provider = judge_provider

    def evaluate_run(
        self,
        run_result: DeliberationRunResult,
        *,
        required_concepts: list[str] | None = None,
        use_llm_judge: bool = True,
        human_review_notes: str | None = None,
    ) -> EvaluationScorecard:
        full_text = self._collect_run_text(run_result).lower()

        # 1. Constraint / concept coverage (0.0 - 5.0)
        if required_concepts:
            matched = sum(1 for c in required_concepts if c.lower() in full_text)
            constraint_score = round(5.0 * (matched / max(1, len(required_concepts))), 2)
        else:
            has_recs = len(run_result.synthesis.actionable_recommendations) > 0
            has_summary = len(run_result.synthesis.summary.strip()) > 30
            constraint_score = 4.5 if (has_recs and has_summary) else 3.0

        # 2. Evidence separation & epistemic boundary clarity (0.0 - 5.0)
        epistemic_markers = [
            "empirical",
            "evidence",
            "metaphor",
            "symbolic",
            "interpret",
            "assumption",
            "limit",
            "trade-off",
            "tradeoff",
            "uncertain",
        ]
        marker_hits = sum(1 for m in epistemic_markers if m in full_text)
        has_epistemic_note = bool(run_result.synthesis.epistemic_note.strip())
        evidence_refs_count = sum(
            len(a.supporting_evidence_refs) for a in run_result.independent_analyses
        )
        evidence_score = min(
            5.0,
            round(
                1.5
                + min(2.0, marker_hits * 0.35)
                + (0.75 if has_epistemic_note else 0.0)
                + (0.75 if evidence_refs_count > 0 or not run_result.evidence_supplied else 0.25),
                2,
            ),
        )

        # 3. Disagreement & multi-perspective trade-off preservation (0.0 - 5.0)
        disagreements_count = len(run_result.synthesis.preserved_disagreements)
        critiques_count = len([c for c in run_result.critiques if c.status == "succeeded"])
        analyses_count = len(
            [a for a in run_result.independent_analyses if a.status == "succeeded"]
        )

        if disagreements_count == 0 and analyses_count == 0:
            # Single-model baseline naturally lacks cross-perspective disagreement tracking
            disagreement_score = 2.0
        else:
            disagreement_score = min(
                5.0,
                round(
                    2.0
                    + min(1.5, disagreements_count * 0.75)
                    + min(0.75, analyses_count * 0.25)
                    + (0.75 if critiques_count > 0 else 0.0),
                    2,
                ),
            )

        # 4. Uncertainty & open-question acknowledgment (0.0 - 5.0)
        uncertainties_count = len(run_result.synthesis.uncertainties_and_limits)
        open_q_count = len(run_result.synthesis.open_questions)
        uncertainty_score = min(
            5.0,
            round(
                2.0 + min(1.75, uncertainties_count * 0.85) + min(1.25, open_q_count * 0.65),
                2,
            ),
        )

        overall = round(
            (
                constraint_score * 0.30
                + evidence_score * 0.25
                + disagreement_score * 0.25
                + uncertainty_score * 0.20
            ),
            2,
        )

        total_tokens = max(1, run_result.trace.total_tokens)
        quality_per_1k = round((overall / total_tokens) * 1000.0, 2)

        judge_model: str | None = None
        judge_scores: dict[str, float] = {}
        judge_rationale = ""

        if use_llm_judge:
            provider = self.judge_provider or get_model_provider("fake")
            judge_model = provider.default_model
            rubric = DOMAIN_RUBRICS.get(run_result.domain, DOMAIN_RUBRICS["research_philosophy"])
            j_resp = provider.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an impartial evaluation judge. Score the synthesis strictly "
                            f"against this domain rubric ({run_result.domain}): {rubric}. "
                            "Do not favor longer responses unless they add substantive trade-off or "
                            "epistemic clarity. Respond in JSON with keys: clarity, tradeoff_depth, "
                            "epistemic_honesty, constraint_satisfaction, rationale."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Question: {run_result.question}\n"
                            f"Synthesis Summary: {run_result.synthesis.summary}\n"
                            f"Disagreements: {run_result.synthesis.preserved_disagreements}\n"
                            f"Uncertainties: {run_result.synthesis.uncertainties_and_limits}"
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=250,
                response_format="judge_json",
            )
            parsed_j = parse_structured_json(
                j_resp.content,
                {
                    "clarity": overall,
                    "tradeoff_depth": disagreement_score,
                    "epistemic_honesty": evidence_score,
                    "constraint_satisfaction": constraint_score,
                    "rationale": "Evaluated via rubric criteria.",
                },
            )
            judge_scores = {
                "clarity": float(parsed_j.get("clarity", overall)),
                "tradeoff_depth": float(parsed_j.get("tradeoff_depth", disagreement_score)),
                "epistemic_honesty": float(parsed_j.get("epistemic_honesty", evidence_score)),
                "constraint_satisfaction": float(
                    parsed_j.get("constraint_satisfaction", constraint_score)
                ),
            }
            judge_rationale = str(parsed_j.get("rationale", ""))

        return EvaluationScorecard(
            run_id=run_result.run_id,
            strategy=run_result.strategy,
            domain=run_result.domain,
            constraint_coverage_score=constraint_score,
            evidence_separation_score=evidence_score,
            disagreement_preservation_score=disagreement_score,
            uncertainty_acknowledgment_score=uncertainty_score,
            overall_quality_score=overall,
            latency_ms=run_result.trace.total_latency_ms,
            total_tokens=run_result.trace.total_tokens,
            estimated_cost_usd=run_result.trace.total_estimated_cost_usd,
            quality_per_1k_tokens=quality_per_1k,
            judge_model=judge_model,
            judge_scores=judge_scores,
            judge_rationale=judge_rationale,
            human_review_notes=human_review_notes,
        )

    @staticmethod
    def _collect_run_text(run_result: DeliberationRunResult) -> str:
        parts = [
            run_result.synthesis.summary,
            run_result.synthesis.epistemic_note,
            " ".join(run_result.synthesis.convergent_agreements),
            " ".join(run_result.synthesis.preserved_disagreements),
            " ".join(run_result.synthesis.uncertainties_and_limits),
            " ".join(run_result.synthesis.open_questions),
            " ".join(run_result.synthesis.actionable_recommendations),
        ]
        for a in run_result.independent_analyses:
            parts.append(a.core_thesis)
            parts.append(a.analysis)
        for c in run_result.critiques:
            parts.append(c.constructive_revision)
            parts.append(" ".join(c.points_of_tension))
        return "\n".join(parts)
