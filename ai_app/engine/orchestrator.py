"""
Modular Deliberation Engine for Perspective Loom.

Independent of Django HTTP handlers. Implements three controlled strategies:
- Strategy A (`single_model_baseline`): Direct single-model baseline response.
- Strategy B (`independent_perspectives`): Concurrent independent perspective analyses + synthesis.
- Strategy C (`deliberative_exchange`): Concurrent independent analyses + cross-examination critiques + synthesis.

Enforces:
- Separation of supplied empirical evidence from generated interpretations
- Concurrent perspective execution via bounded thread pool
- Partial-failure resilience (if one perspective fails, the run degrades gracefully to `partial_failure`)
- Complete trace correlation (latency, token usage, estimated cost, retries)
- Optional NDJSON event generator for real-time progress streaming
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ai_app.engine.perspectives import DEFAULT_REGISTRY, PerspectiveRegistry
from ai_app.engine.providers import ModelProvider, get_model_provider
from ai_app.engine.schemas import (
    CritiqueExchange,
    DeliberationRequest,
    DeliberationRunResult,
    DeliberationStrategy,
    EvidenceItem,
    ExecutionTrace,
    PerspectiveAnalysis,
    PerspectiveSpec,
    StepTrace,
    SynthesisResult,
)

logger = logging.getLogger("ai_app")


def parse_structured_json(raw_text: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """
    Robust JSON extraction that handles fenced markdown blocks, leading/trailing
    prose, or malformed model outputs without crashing the deliberation pipeline.
    """
    if not raw_text:
        return fallback
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            cleaned = cleaned[brace_start : brace_end + 1]

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            merged = dict(fallback)
            merged.update(parsed)
            return merged
    except json.JSONDecodeError:
        logger.warning("Failed to parse structured JSON from model output; using safe fallback.")
    return fallback


class DeliberationEngine:
    """Core orchestrator for multi-perspective analysis, critique, and synthesis."""

    def __init__(
        self,
        *,
        registry: PerspectiveRegistry | None = None,
        provider: ModelProvider | None = None,
        max_workers: int = 4,
    ) -> None:
        self.registry = registry or DEFAULT_REGISTRY
        self.provider = provider
        self.max_workers = max_workers

    def run(self, request: DeliberationRequest) -> DeliberationRunResult:
        """Execute a complete synchronous deliberation workflow and return structured results."""
        events = list(self.stream_run(request))
        final_event = events[-1]
        result_obj: DeliberationRunResult = final_event["result_object"]
        return result_obj

    def stream_run(self, request: DeliberationRequest) -> Iterator[dict[str, Any]]:
        """
        Execute a deliberation workflow while yielding structured progress events.
        The final yielded dictionary contains `type == 'complete'` and `result_object`.
        """
        request.validate()
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        provider = self.provider or get_model_provider(
            request.provider_name,
            model_name=request.model_name,
        )
        model_name = request.model_name or provider.default_model

        trace = ExecutionTrace(
            trace_id=request.trace_id,
            provider=provider.provider_name,
            model=model_name,
        )
        run_start = time.perf_counter()

        yield {
            "type": "run_started",
            "run_id": run_id,
            "trace_id": request.trace_id,
            "strategy": request.strategy,
            "question": request.question,
        }

        # Strategy A: Single-Model Baseline
        if request.strategy == DeliberationStrategy.SINGLE_MODEL_BASELINE.value:
            synthesis, step_trace = self._execute_single_model_baseline(
                request=request,
                provider=provider,
                model_name=model_name,
            )
            trace.record_step(step_trace)
            trace.total_latency_ms = round((time.perf_counter() - run_start) * 1000.0, 2)
            trace.finalize()

            status = "completed" if step_trace.status == "succeeded" else "failed"
            result = DeliberationRunResult(
                run_id=run_id,
                question=request.question,
                strategy=request.strategy,
                domain=request.domain,
                status=status,
                perspectives_used=[],
                evidence_supplied=request.evidence,
                independent_analyses=[],
                critiques=[],
                synthesis=synthesis,
                trace=trace,
            )
            yield {
                "type": "synthesis_completed",
                "run_id": run_id,
                "synthesis": synthesis.to_dict(),
            }
            yield {
                "type": "complete",
                "run_id": run_id,
                "status": status,
                "result": result.to_dict(),
                "result_object": result,
            }
            return

        # Select perspectives for Strategy B or Strategy C
        perspectives = self.registry.select_for_request(
            request.question,
            requested_names=request.perspective_names or None,
            domain=request.domain,
            max_perspectives=request.max_perspectives,
        )

        yield {
            "type": "perspectives_selected",
            "run_id": run_id,
            "perspectives": [
                {"slug": p.slug, "name": p.name, "version": p.version, "domain": p.domain}
                for p in perspectives
            ],
        }

        # Step 1: Independent concurrent perspective analyses
        analyses, analysis_traces = self._execute_independent_analyses(
            request=request,
            perspectives=perspectives,
            provider=provider,
            model_name=model_name,
        )
        for analysis, s_trace in zip(analyses, analysis_traces, strict=False):
            trace.record_step(s_trace)
            yield {
                "type": "perspective_analysis",
                "run_id": run_id,
                "data": analysis.to_dict(),
            }

        succeeded_analyses = [a for a in analyses if a.status == "succeeded"]

        # Step 2: Optional Critique / Cross-Examination Round (Strategy C)
        critiques: list[CritiqueExchange] = []
        if (
            request.strategy == DeliberationStrategy.DELIBERATIVE_EXCHANGE.value
            and request.enable_critique_round
            and len(succeeded_analyses) >= 2
        ):
            critiques, critique_traces = self._execute_critique_round(
                request=request,
                perspectives=perspectives,
                analyses=succeeded_analyses,
                provider=provider,
                model_name=model_name,
            )
            for critique, c_trace in zip(critiques, critique_traces, strict=False):
                trace.record_step(c_trace)
                yield {
                    "type": "perspective_critique",
                    "run_id": run_id,
                    "data": critique.to_dict(),
                }

        # Step 3: Structured Synthesis
        if succeeded_analyses:
            synthesis, synth_trace = self._execute_synthesis(
                request=request,
                analyses=succeeded_analyses,
                critiques=[c for c in critiques if c.status == "succeeded"],
                provider=provider,
                model_name=model_name,
            )
            trace.record_step(synth_trace)
        else:
            synthesis = SynthesisResult(
                summary="Deliberation failed because no perspective analyses succeeded.",
                convergent_agreements=[],
                preserved_disagreements=[],
                uncertainties_and_limits=["All perspective calls failed."],
                open_questions=[],
                actionable_recommendations=[],
                epistemic_note="Execution failed.",
            )

        trace.total_latency_ms = round((time.perf_counter() - run_start) * 1000.0, 2)
        trace.finalize()

        if not succeeded_analyses:
            run_status = "failed"
        elif trace.partial_failures > 0:
            run_status = "partial_failure"
        else:
            run_status = "completed"

        result = DeliberationRunResult(
            run_id=run_id,
            question=request.question,
            strategy=request.strategy,
            domain=request.domain,
            status=run_status,
            perspectives_used=[
                {
                    "slug": p.slug,
                    "name": p.name,
                    "version": p.version,
                    "domain": p.domain,
                    "epistemic_type": p.epistemic_type,
                }
                for p in perspectives
            ],
            evidence_supplied=request.evidence,
            independent_analyses=analyses,
            critiques=critiques,
            synthesis=synthesis,
            trace=trace,
        )

        yield {
            "type": "synthesis_completed",
            "run_id": run_id,
            "synthesis": synthesis.to_dict(),
        }
        yield {
            "type": "complete",
            "run_id": run_id,
            "status": run_status,
            "result": result.to_dict(),
            "result_object": result,
        }

    def _format_evidence_block(self, evidence: list[EvidenceItem]) -> str:
        if not evidence:
            return "No external evidence items supplied. Rely strictly on explicit logical analysis and flag unverified empirical assumptions."
        lines = []
        for item in evidence:
            lines.append(
                f"[EVIDENCE {item.source_id}] ({item.source_type}, verified={item.verified}) {item.title}: {item.content}"
            )
        return "\n".join(lines)

    def _execute_single_model_baseline(
        self,
        *,
        request: DeliberationRequest,
        provider: ModelProvider,
        model_name: str,
    ) -> tuple[SynthesisResult, StepTrace]:
        evidence_text = self._format_evidence_block(request.evidence)
        system_prompt = (
            "You are a capable analytical assistant answering a complex question directly. "
            "Respond in JSON with keys: summary, convergent_agreements, preserved_disagreements, "
            "uncertainties_and_limits, open_questions, actionable_recommendations, epistemic_note."
        )
        user_prompt = (
            f"Question: {request.question}\n\n"
            f"Supplied Evidence:\n{evidence_text}\n\n"
            "Provide a rigorous single-pass response in valid JSON."
        )
        t0 = time.perf_counter()
        try:
            resp = provider.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model_name,
                temperature=0.5,
                max_tokens=500,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
                response_format="baseline_json",
            )
            parsed = parse_structured_json(
                resp.content,
                {
                    "summary": resp.content,
                    "convergent_agreements": [],
                    "preserved_disagreements": [],
                    "uncertainties_and_limits": ["Single-model baseline without cross-perspective critique."],
                    "open_questions": [],
                    "actionable_recommendations": [],
                    "epistemic_note": "Single-model baseline output.",
                },
            )
            synthesis = SynthesisResult(
                summary=str(parsed.get("summary", "")),
                convergent_agreements=list(parsed.get("convergent_agreements", [])),
                preserved_disagreements=list(parsed.get("preserved_disagreements", [])),
                uncertainties_and_limits=list(parsed.get("uncertainties_and_limits", [])),
                open_questions=list(parsed.get("open_questions", [])),
                actionable_recommendations=list(parsed.get("actionable_recommendations", [])),
                epistemic_note=str(parsed.get("epistemic_note", "Single-model baseline.")),
                latency_ms=resp.latency_ms,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                estimated_cost_usd=resp.estimated_cost_usd,
                model_used=resp.model,
            )
            step = StepTrace(
                step_name="single_model_baseline",
                actor="baseline_model",
                status="succeeded",
                latency_ms=resp.latency_ms,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                estimated_cost_usd=resp.estimated_cost_usd,
                retries=resp.retries,
            )
            return synthesis, step
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            synthesis = SynthesisResult(
                summary="Baseline execution failed.",
                convergent_agreements=[],
                preserved_disagreements=[],
                uncertainties_and_limits=[str(exc)],
                open_questions=[],
                actionable_recommendations=[],
                epistemic_note="Error during baseline execution.",
            )
            step = StepTrace(
                step_name="single_model_baseline",
                actor="baseline_model",
                status="failed",
                latency_ms=latency_ms,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=0.0,
                error=str(exc),
            )
            return synthesis, step

    def _execute_independent_analyses(
        self,
        *,
        request: DeliberationRequest,
        perspectives: list[PerspectiveSpec],
        provider: ModelProvider,
        model_name: str,
    ) -> tuple[list[PerspectiveAnalysis], list[StepTrace]]:
        evidence_text = self._format_evidence_block(request.evidence)

        def _run_one(spec: PerspectiveSpec) -> tuple[PerspectiveAnalysis, StepTrace]:
            system_prompt = (
                f"PERSPECTIVE_NAME: {spec.name}\n"
                f"PERSPECTIVE_VERSION: {spec.version}\n"
                f"EPISTEMIC_TYPE: {spec.epistemic_type}\n"
                f"METHODOLOGY: {spec.interpretive_methodology}\n"
                f"BOUNDARIES: {spec.boundaries_and_limitations}\n"
                f"EVIDENCE_REQUIREMENTS: {spec.evidence_requirements}\n\n"
                f"{spec.system_instructions}\n\n"
                "Respond strictly in JSON with keys: core_thesis, analysis, "
                "supporting_evidence_refs (list), assumptions_and_limitations (list), "
                "uncertainty_level ('low'|'moderate'|'high')."
            )
            user_prompt = (
                f"Question: {request.question}\n\n"
                f"Supplied Evidence (keep separate from speculative interpretation):\n{evidence_text}\n"
            )
            if request.human_intervention_note:
                user_prompt += f"\nHuman Participant Guidance: {request.human_intervention_note}\n"

            t0 = time.perf_counter()
            try:
                resp = provider.complete(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=model_name,
                    temperature=spec.temperature,
                    max_tokens=spec.max_tokens,
                    timeout_seconds=request.timeout_seconds,
                    max_retries=request.max_retries,
                    response_format="analysis_json",
                )
                parsed = parse_structured_json(
                    resp.content,
                    {
                        "core_thesis": f"{spec.name} perspective on the question.",
                        "analysis": resp.content,
                        "supporting_evidence_refs": [],
                        "assumptions_and_limitations": [spec.boundaries_and_limitations],
                        "uncertainty_level": "moderate",
                    },
                )
                analysis = PerspectiveAnalysis(
                    perspective_name=spec.name,
                    perspective_slug=spec.slug,
                    perspective_version=spec.version,
                    epistemic_type=spec.epistemic_type,
                    core_thesis=str(parsed.get("core_thesis", "")),
                    analysis=str(parsed.get("analysis", "")),
                    supporting_evidence_refs=list(parsed.get("supporting_evidence_refs", [])),
                    assumptions_and_limitations=list(parsed.get("assumptions_and_limitations", [])),
                    uncertainty_level=str(parsed.get("uncertainty_level", "moderate")),
                    latency_ms=resp.latency_ms,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    estimated_cost_usd=resp.estimated_cost_usd,
                    model_used=resp.model,
                    status="succeeded",
                )
                step = StepTrace(
                    step_name="independent_analysis",
                    actor=spec.name,
                    status="succeeded",
                    latency_ms=resp.latency_ms,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    estimated_cost_usd=resp.estimated_cost_usd,
                    retries=resp.retries,
                )
                return analysis, step
            except Exception as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                logger.error(f"Perspective '{spec.name}' failed during independent analysis: {exc}")
                analysis = PerspectiveAnalysis(
                    perspective_name=spec.name,
                    perspective_slug=spec.slug,
                    perspective_version=spec.version,
                    epistemic_type=spec.epistemic_type,
                    core_thesis="",
                    analysis="",
                    latency_ms=latency_ms,
                    model_used=model_name,
                    status="failed",
                    error_message=str(exc),
                )
                step = StepTrace(
                    step_name="independent_analysis",
                    actor=spec.name,
                    status="failed",
                    latency_ms=latency_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    estimated_cost_usd=0.0,
                    error=str(exc),
                )
                return analysis, step

        workers = min(self.max_workers, max(1, len(perspectives)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pairs = list(pool.map(_run_one, perspectives))

        analyses = [p[0] for p in pairs]
        traces = [p[1] for p in pairs]
        return analyses, traces

    def _execute_critique_round(
        self,
        *,
        request: DeliberationRequest,
        perspectives: list[PerspectiveSpec],
        analyses: list[PerspectiveAnalysis],
        provider: ModelProvider,
        model_name: str,
    ) -> tuple[list[CritiqueExchange], list[StepTrace]]:
        spec_by_name = {s.name: s for s in perspectives}
        peer_summary_lines = [
            f"- Peer [{a.perspective_name}] ({a.epistemic_type}): Thesis='{a.core_thesis}' | Analysis='{a.analysis}'"
            for a in analyses
        ]
        peer_block = "\n".join(peer_summary_lines)

        def _critique_one(analysis: PerspectiveAnalysis) -> tuple[CritiqueExchange, StepTrace]:
            spec = spec_by_name.get(analysis.perspective_name)
            system_prompt = (
                f"CRITIC_PERSPECTIVE: {analysis.perspective_name}\n"
                f"METHODOLOGY: {spec.interpretive_methodology if spec else ''}\n"
                "Conduct an evidence-based cross-examination of peer perspectives. "
                "Challenge unsubstantiated claims, identify genuine points of tension, "
                "and propose a constructive revision. Respond in JSON with keys: "
                "target_perspectives (list), points_of_tension (list), "
                "evidence_challenges (list), constructive_revision (string)."
            )
            user_prompt = (
                f"Question: {request.question}\n\n"
                f"Independent Peer Analyses:\n{peer_block}\n"
            )
            t0 = time.perf_counter()
            try:
                resp = provider.complete(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=model_name,
                    temperature=0.6,
                    max_tokens=300,
                    timeout_seconds=request.timeout_seconds,
                    max_retries=request.max_retries,
                    response_format="critique_json",
                )
                parsed = parse_structured_json(
                    resp.content,
                    {
                        "target_perspectives": [
                            a.perspective_name
                            for a in analyses
                            if a.perspective_name != analysis.perspective_name
                        ],
                        "points_of_tension": [resp.content],
                        "evidence_challenges": [],
                        "constructive_revision": resp.content,
                    },
                )
                critique = CritiqueExchange(
                    critic_perspective=analysis.perspective_name,
                    target_perspectives=list(parsed.get("target_perspectives", [])),
                    points_of_tension=list(parsed.get("points_of_tension", [])),
                    evidence_challenges=list(parsed.get("evidence_challenges", [])),
                    constructive_revision=str(parsed.get("constructive_revision", "")),
                    latency_ms=resp.latency_ms,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    estimated_cost_usd=resp.estimated_cost_usd,
                    model_used=resp.model,
                    status="succeeded",
                )
                step = StepTrace(
                    step_name="critique_exchange",
                    actor=analysis.perspective_name,
                    status="succeeded",
                    latency_ms=resp.latency_ms,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    estimated_cost_usd=resp.estimated_cost_usd,
                    retries=resp.retries,
                )
                return critique, step
            except Exception as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                critique = CritiqueExchange(
                    critic_perspective=analysis.perspective_name,
                    target_perspectives=[],
                    points_of_tension=[],
                    evidence_challenges=[],
                    constructive_revision="",
                    latency_ms=latency_ms,
                    model_used=model_name,
                    status="failed",
                    error_message=str(exc),
                )
                step = StepTrace(
                    step_name="critique_exchange",
                    actor=analysis.perspective_name,
                    status="failed",
                    latency_ms=latency_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    estimated_cost_usd=0.0,
                    error=str(exc),
                )
                return critique, step

        workers = min(self.max_workers, max(1, len(analyses)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pairs = list(pool.map(_critique_one, analyses))

        return [p[0] for p in pairs], [p[1] for p in pairs]

    def _execute_synthesis(
        self,
        *,
        request: DeliberationRequest,
        analyses: list[PerspectiveAnalysis],
        critiques: list[CritiqueExchange],
        provider: ModelProvider,
        model_name: str,
    ) -> tuple[SynthesisResult, StepTrace]:
        evidence_text = self._format_evidence_block(request.evidence)
        analyses_text = "\n\n".join(
            f"[{a.perspective_name} | {a.epistemic_type} | uncertainty={a.uncertainty_level}]\n"
            f"Thesis: {a.core_thesis}\nAnalysis: {a.analysis}\nLimitations: {a.assumptions_and_limitations}"
            for a in analyses
        )
        critiques_text = (
            "\n\n".join(
                f"[Critic: {c.critic_perspective} -> {c.target_perspectives}]\n"
                f"Tensions: {c.points_of_tension}\nRevision: {c.constructive_revision}"
                for c in critiques
            )
            if critiques
            else "No cross-examination round executed (independent perspectives strategy)."
        )

        system_prompt = (
            "You are the Perspective Loom Synthesis Engine. Your task is to synthesize "
            "independent perspective analyses and cross-examination critiques without "
            "flattening meaningful disagreements or blurring empirical evidence with metaphor. "
            "Respond strictly in JSON with keys: summary, convergent_agreements (list), "
            "preserved_disagreements (list), uncertainties_and_limits (list), "
            "open_questions (list), actionable_recommendations (list), epistemic_note (string)."
        )
        user_prompt = (
            f"Question: {request.question}\n\n"
            f"Supplied Evidence:\n{evidence_text}\n\n"
            f"Independent Analyses:\n{analyses_text}\n\n"
            f"Critique Exchanges:\n{critiques_text}\n"
        )
        if request.human_intervention_note:
            user_prompt += f"\nHuman Participant Guidance: {request.human_intervention_note}\n"

        t0 = time.perf_counter()
        try:
            resp = provider.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model_name,
                temperature=0.4,
                max_tokens=600,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
                response_format="synthesis_json",
            )
            parsed = parse_structured_json(
                resp.content,
                {
                    "summary": resp.content,
                    "convergent_agreements": [],
                    "preserved_disagreements": [],
                    "uncertainties_and_limits": [],
                    "open_questions": [],
                    "actionable_recommendations": [],
                    "epistemic_note": "Distinguish empirical evidence from interpretive perspectives.",
                },
            )
            synthesis = SynthesisResult(
                summary=str(parsed.get("summary", "")),
                convergent_agreements=list(parsed.get("convergent_agreements", [])),
                preserved_disagreements=list(parsed.get("preserved_disagreements", [])),
                uncertainties_and_limits=list(parsed.get("uncertainties_and_limits", [])),
                open_questions=list(parsed.get("open_questions", [])),
                actionable_recommendations=list(parsed.get("actionable_recommendations", [])),
                epistemic_note=str(parsed.get("epistemic_note", "")),
                latency_ms=resp.latency_ms,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                estimated_cost_usd=resp.estimated_cost_usd,
                model_used=resp.model,
            )
            step = StepTrace(
                step_name="synthesis",
                actor="synthesis_engine",
                status="succeeded",
                latency_ms=resp.latency_ms,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                estimated_cost_usd=resp.estimated_cost_usd,
                retries=resp.retries,
            )
            return synthesis, step
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            synthesis = SynthesisResult(
                summary="Synthesis step failed; inspect individual perspective analyses.",
                convergent_agreements=[],
                preserved_disagreements=[],
                uncertainties_and_limits=[str(exc)],
                open_questions=[],
                actionable_recommendations=[],
                epistemic_note="Synthesis error.",
            )
            step = StepTrace(
                step_name="synthesis",
                actor="synthesis_engine",
                status="failed",
                latency_ms=latency_ms,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=0.0,
                error=str(exc),
            )
            return synthesis, step
