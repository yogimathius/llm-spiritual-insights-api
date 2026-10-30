"""
Deliberation & Evaluation API views for Perspective Loom (Phase 2 - Phase 4).

Exposes:
- `GET/POST /ai/perspectives/`: Inspect or register versioned perspective definitions
- `POST /ai/deliberate/`: Execute a structured deliberation (Strategies A, B, or C) and persist the run
- `POST /ai/deliberate/stream/`: Stream real-time NDJSON progress events for a deliberation run
- `GET /ai/runs/`: List deliberation runs scoped to the requesting user
- `GET /ai/runs/<run_id>/`: Retrieve a specific deliberation run with full trace & telemetry
- `POST /ai/evaluate/`: Score a completed run against domain rubrics and optional human review notes
- `POST /ai/compare/`: Execute a reproducible side-by-side comparison across Strategies A, B, and C
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ai_app.engine.orchestrator import DeliberationEngine
from ai_app.engine.perspectives import DEFAULT_REGISTRY
from ai_app.engine.providers import get_model_provider
from ai_app.engine.schemas import (
    CritiqueExchange,
    DeliberationRequest,
    DeliberationRunResult,
    EvidenceItem,
    ExecutionTrace,
    PerspectiveAnalysis,
    PerspectiveSpec,
    SynthesisResult,
)
from ai_app.evaluation.evaluator import DeliberationEvaluator
from ai_app.evaluation.runner import ExperimentRunner
from ai_app.models.deliberation import DeliberationRun
from ai_app.models.llm_role import LLMRole
from ai_app.security import check_api_key_if_required, csrf_protect_session, resolve_request_user

logger = logging.getLogger("ai_app")


def _parse_deliberation_request(data: dict[str, Any], username: str | None) -> DeliberationRequest:
    raw_evidence = data.get("evidence") or []
    if not isinstance(raw_evidence, list):
        raise ValueError("'evidence' must be a list of evidence objects.")

    evidence_items: list[EvidenceItem] = []
    for idx, ev in enumerate(raw_evidence):
        if isinstance(ev, dict):
            evidence_items.append(
                EvidenceItem(
                    source_id=str(ev.get("source_id") or f"EV-{idx + 1}"),
                    title=str(ev.get("title") or "Supplied Evidence"),
                    content=str(ev.get("content") or ""),
                    source_type=str(ev.get("source_type") or "user_provided"),
                    verified=bool(ev.get("verified", True)),
                )
            )
        elif isinstance(ev, str):
            evidence_items.append(
                EvidenceItem(
                    source_id=f"EV-{idx + 1}",
                    title="User Evidence",
                    content=ev,
                )
            )

    use_ollama = bool(data.get("use_ollama", False))
    provider_name = str(
        data.get("provider") or ("ollama" if use_ollama else "fake")
    ).strip()

    req = DeliberationRequest(
        question=str(data.get("question") or data.get("prompt") or "").strip(),
        strategy=str(data.get("strategy") or "deliberative_exchange").strip(),
        domain=str(data.get("domain") or "research_philosophy").strip(),
        perspective_names=list(data.get("perspectives") or []),
        evidence=evidence_items,
        provider_name=provider_name,
        model_name=data.get("model"),
        max_perspectives=int(data.get("max_perspectives", 3)),
        enable_critique_round=bool(data.get("enable_critique_round", True)),
        timeout_seconds=float(data.get("timeout_seconds", 30.0)),
        max_retries=int(data.get("max_retries", 2)),
        user_id=username,
        human_intervention_note=data.get("human_intervention_note"),
    )
    req.validate()
    return req


def _persist_run(result: DeliberationRunResult, user_obj: Any) -> DeliberationRun:
    return DeliberationRun.objects.create(
        run_id=result.run_id,
        trace_id=result.trace.trace_id,
        user=user_obj,
        question=result.question,
        strategy=result.strategy,
        domain=result.domain,
        status=result.status,
        provider=result.trace.provider,
        model_name=result.trace.model,
        perspectives_used=result.perspectives_used,
        evidence_supplied=[e.to_dict() for e in result.evidence_supplied],
        independent_analyses=[a.to_dict() for a in result.independent_analyses],
        critiques=[c.to_dict() for c in result.critiques],
        synthesis=result.synthesis.to_dict(),
        trace=result.trace.to_dict(),
        total_latency_ms=result.trace.total_latency_ms,
        total_tokens=result.trace.total_tokens,
        estimated_cost_usd=result.trace.total_estimated_cost_usd,
    )


@csrf_protect_session
@require_http_methods(["GET", "POST"])
def perspectives_view(request: HttpRequest) -> JsonResponse:
    """List or register versioned PerspectiveSpecs."""
    if request.method == "GET":
        domain = request.GET.get("domain")
        include_hist = request.GET.get("include_historical", "true").lower() != "false"
        specs = DEFAULT_REGISTRY.list_all(
            domain=domain or None,
            include_historical=include_hist,
        )
        return JsonResponse(
            {
                "count": len(specs),
                "perspectives": [s.to_dict() for s in specs],
            }
        )

    # POST: Register a new or updated custom perspective
    auth_err = check_api_key_if_required(request)
    if auth_err is not None:
        return auth_err

    try:
        data = json.loads(request.body or b"{}")
        spec = PerspectiveSpec(
            slug=str(data.get("slug") or "").strip(),
            name=str(data.get("name") or "").strip(),
            version=str(data.get("version") or "1.0.0").strip(),
            domain=str(data.get("domain") or "research_philosophy").strip(),
            purpose=str(data.get("purpose") or "").strip(),
            system_instructions=str(data.get("system_instructions") or "").strip(),
            interpretive_methodology=str(data.get("interpretive_methodology") or "").strip(),
            boundaries_and_limitations=str(data.get("boundaries_and_limitations") or "").strip(),
            epistemic_type=str(data.get("epistemic_type") or "philosophical_inquiry").strip(),
            permitted_tools=list(data.get("permitted_tools") or []),
            evidence_requirements=str(
                data.get("evidence_requirements")
                or "Distinguish empirical evidence from interpretation."
            ),
            preferred_model=str(data.get("preferred_model") or "gpt-4o-mini"),
            max_tokens=int(data.get("max_tokens", 350)),
            temperature=float(data.get("temperature", 0.7)),
            collaboration_triggers=list(data.get("collaboration_triggers") or []),
            recommended_collaborators=list(data.get("recommended_collaborators") or []),
            is_historical_persona=bool(data.get("is_historical_persona", False)),
        )
        DEFAULT_REGISTRY.register(spec)
        LLMRole.objects.update_or_create(
            name=spec.name,
            defaults={
                "slug": spec.slug,
                "version": spec.version,
                "domain": spec.domain,
                "purpose": spec.purpose,
                "description": spec.purpose,
                "prompt_template": spec.system_instructions,
                "interpretive_methodology": spec.interpretive_methodology,
                "boundaries_and_limitations": spec.boundaries_and_limitations,
                "epistemic_type": spec.epistemic_type,
                "evidence_requirements": spec.evidence_requirements,
                "permitted_tools": spec.permitted_tools,
                "is_historical_persona": spec.is_historical_persona,
                "model_name": spec.preferred_model,
                "max_tokens": spec.max_tokens,
                "temperature": spec.temperature,
                "collaboration_triggers": ", ".join(spec.collaboration_triggers),
            },
        )
        return JsonResponse({"perspective": spec.to_dict()}, status=201)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_protect_session
@require_POST
def start_deliberation(request: HttpRequest) -> JsonResponse:
    """Execute a structured deliberation workflow and persist its run record."""
    user_obj, auth_err = resolve_request_user(request, require_explicit_identity=False)
    if auth_err is not None or user_obj is None:
        return auth_err or JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        if not request.body:
            return JsonResponse({"error": "Empty request body"}, status=400)
        data = json.loads(request.body)
        delib_req = _parse_deliberation_request(data, user_obj.username)
        provider = get_model_provider(delib_req.provider_name, model_name=delib_req.model_name)
        engine = DeliberationEngine(registry=DEFAULT_REGISTRY, provider=provider)
        result = engine.run(delib_req)
        _persist_run(result, user_obj)
        return JsonResponse(result.to_dict(), status=200)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    except (ValueError, KeyError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error(f"Error in start_deliberation: {type(exc).__name__}")
        return JsonResponse({"error": "Internal deliberation error"}, status=500)


@csrf_protect_session
@require_POST
def stream_deliberation(request: HttpRequest):
    """Stream NDJSON progress events for a deliberation run and persist on completion."""
    user_obj, auth_err = resolve_request_user(request, require_explicit_identity=False)
    if auth_err is not None or user_obj is None:
        return auth_err or JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        if not request.body:
            return JsonResponse({"error": "Empty request body"}, status=400)
        data = json.loads(request.body)
        delib_req = _parse_deliberation_request(data, user_obj.username)
        provider = get_model_provider(delib_req.provider_name, model_name=delib_req.model_name)
        engine = DeliberationEngine(registry=DEFAULT_REGISTRY, provider=provider)

        def _event_generator():
            for event in engine.stream_run(delib_req):
                if event.get("type") == "complete" and "result_object" in event:
                    result_obj: DeliberationRunResult = event.pop("result_object")
                    _persist_run(result_obj, user_obj)
                yield json.dumps(event) + "\n"

        return StreamingHttpResponse(
            _event_generator(), content_type="application/x-ndjson"
        )
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    except (ValueError, KeyError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_GET
def list_runs(request: HttpRequest) -> JsonResponse:
    """List persisted deliberation runs isolated to the requesting user."""
    user_obj, auth_err = resolve_request_user(request, require_explicit_identity=True)
    if auth_err is not None or user_obj is None:
        return auth_err or JsonResponse({"error": "Unauthorized"}, status=401)

    runs = DeliberationRun.objects.filter(user=user_obj).order_by("-created_at")[:50]
    items = [
        {
            "run_id": r.run_id,
            "trace_id": r.trace_id,
            "question": r.question,
            "strategy": r.strategy,
            "domain": r.domain,
            "status": r.status,
            "provider": r.provider,
            "model_name": r.model_name,
            "total_latency_ms": r.total_latency_ms,
            "total_tokens": r.total_tokens,
            "estimated_cost_usd": r.estimated_cost_usd,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]
    return JsonResponse({"user": user_obj.username, "runs": items})


@require_GET
def get_run_detail(request: HttpRequest, run_id: str) -> JsonResponse:
    """Retrieve a specific deliberation run scoped to its owner."""
    user_obj, auth_err = resolve_request_user(request, require_explicit_identity=True)
    if auth_err is not None or user_obj is None:
        return auth_err or JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        run_obj = DeliberationRun.objects.get(run_id=run_id)
    except DeliberationRun.DoesNotExist:
        return JsonResponse({"error": f"Run '{run_id}' not found"}, status=404)

    if run_obj.user and run_obj.user != user_obj:
        return JsonResponse({"error": "Forbidden: run belongs to another user"}, status=403)

    return JsonResponse(
        {
            "run_id": run_obj.run_id,
            "trace_id": run_obj.trace_id,
            "question": run_obj.question,
            "strategy": run_obj.strategy,
            "domain": run_obj.domain,
            "status": run_obj.status,
            "perspectives_used": run_obj.perspectives_used,
            "evidence_supplied": run_obj.evidence_supplied,
            "independent_analyses": run_obj.independent_analyses,
            "critiques": run_obj.critiques,
            "synthesis": run_obj.synthesis,
            "trace": run_obj.trace,
            "evaluation": run_obj.evaluation,
            "created_at": run_obj.created_at.isoformat(),
        }
    )


@csrf_protect_session
@require_POST
def evaluate_run_view(request: HttpRequest) -> JsonResponse:
    """Evaluate a persisted deliberation run against domain rubrics."""
    user_obj, auth_err = resolve_request_user(request, require_explicit_identity=True)
    if auth_err is not None or user_obj is None:
        return auth_err or JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        data = json.loads(request.body or b"{}")
        run_id = str(data.get("run_id") or "").strip()
        if not run_id:
            return JsonResponse({"error": "Missing 'run_id'"}, status=400)

        run_obj = DeliberationRun.objects.get(run_id=run_id)
        if run_obj.user and run_obj.user != user_obj:
            return JsonResponse({"error": "Forbidden: run belongs to another user"}, status=403)

        # Rehydrate DeliberationRunResult for evaluation
        synth_dict = run_obj.synthesis or {}
        trace_dict = run_obj.trace or {}
        rehydrated = DeliberationRunResult(
            run_id=run_obj.run_id,
            question=run_obj.question,
            strategy=run_obj.strategy,
            domain=run_obj.domain,
            status=run_obj.status,
            perspectives_used=run_obj.perspectives_used,
            evidence_supplied=[EvidenceItem(**e) for e in (run_obj.evidence_supplied or [])],
            independent_analyses=[
                PerspectiveAnalysis(**a) for a in (run_obj.independent_analyses or [])
            ],
            critiques=[CritiqueExchange(**c) for c in (run_obj.critiques or [])],
            synthesis=SynthesisResult(**synth_dict),
            trace=ExecutionTrace(
                trace_id=trace_dict.get("trace_id", run_obj.trace_id),
                provider=trace_dict.get("provider", run_obj.provider),
                model=trace_dict.get("model", run_obj.model_name),
                total_latency_ms=run_obj.total_latency_ms,
                total_tokens=run_obj.total_tokens,
                total_estimated_cost_usd=run_obj.estimated_cost_usd,
            ),
        )

        evaluator = DeliberationEvaluator()
        scorecard = evaluator.evaluate_run(
            rehydrated,
            required_concepts=data.get("required_concepts"),
            use_llm_judge=bool(data.get("use_llm_judge", True)),
            human_review_notes=data.get("human_review_notes"),
        )
        run_obj.evaluation = scorecard.to_dict()
        run_obj.save(update_fields=["evaluation"])
        return JsonResponse({"run_id": run_id, "evaluation": scorecard.to_dict()})
    except DeliberationRun.DoesNotExist:
        return JsonResponse({"error": "Run not found"}, status=404)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_protect_session
@require_POST
def compare_strategies_view(request: HttpRequest) -> JsonResponse:
    """Compare Strategies A, B, and C side-by-side on a question or benchmark."""
    _, auth_err = resolve_request_user(request, require_explicit_identity=False)
    if auth_err is not None:
        return auth_err

    try:
        data = json.loads(request.body or b"{}")
        question = str(data.get("question") or data.get("prompt") or "").strip()
        if not question:
            return JsonResponse({"error": "Missing 'question'"}, status=400)

        provider_name = str(data.get("provider") or "fake").strip()
        runner = ExperimentRunner(
            provider_name=provider_name,
            model_name=data.get("model"),
        )
        raw_ev = data.get("evidence") or []
        evidence_items = [
            EvidenceItem(
                source_id=str(ev.get("source_id") or f"EV-{i + 1}"),
                title=str(ev.get("title") or "Evidence"),
                content=str(ev.get("content") or ""),
            )
            for i, ev in enumerate(raw_ev)
            if isinstance(ev, dict)
        ]

        report = runner.compare_on_question(
            question=question,
            domain=str(data.get("domain") or "research_philosophy"),
            perspective_names=data.get("perspectives"),
            evidence=evidence_items,
            required_concepts=data.get("required_concepts"),
            strategies=data.get("strategies"),
        )
        return JsonResponse(report)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
