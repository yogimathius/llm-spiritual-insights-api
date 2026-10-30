"""
MCP-Ready Tool Surface & External Integration Contract for Perspective Loom.

Provides transport-agnostic tool descriptors and JSON-RPC 2.0 compatible
invocation handlers for:
- `list_perspectives`
- `deliberate`
- `compare_deliberations`
- `evaluate_deliberation`

Also defines the `SymbolOntologyContext` extension hook so future consumers
such as **Nexus Flow** (the Rust-based dream interpretation platform) can pass
symbol ontology entries as structured evidence without coupling Perspective Loom
to external repositories.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ai_app.engine.orchestrator import DeliberationEngine
from ai_app.engine.perspectives import DEFAULT_REGISTRY
from ai_app.engine.providers import get_model_provider
from ai_app.engine.schemas import DeliberationRequest, EvidenceItem
from ai_app.evaluation.evaluator import DeliberationEvaluator
from ai_app.evaluation.runner import ExperimentRunner


@dataclass
class SymbolOntologyEntry:
    """
    Extensible contract for symbolic/archetypal context (e.g., from Nexus Flow).
    Always treated as heuristic associative context, never as fixed dogma.
    """

    symbol_id: str
    term: str
    user_associations: list[str] = field(default_factory=list)
    cultural_motifs: list[str] = field(default_factory=list)
    ambiguity_notes: str = "Prioritize the user's lived associations over canonical meanings."

    def to_evidence_item(self) -> EvidenceItem:
        assoc = ", ".join(self.user_associations) or "none specified"
        motifs = ", ".join(self.cultural_motifs) or "open symbolic motif"
        return EvidenceItem(
            source_id=f"ONTOLOGY-{self.symbol_id}",
            title=f"Symbol Context: {self.term}",
            content=(
                f"User associations: [{assoc}]. Historical/cultural motifs: [{motifs}]. "
                f"Epistemic guidance: {self.ambiguity_notes}"
            ),
            source_type="user_provided",
            verified=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MCP_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_perspectives",
        "description": "List versioned reasoning perspectives available in Perspective Loom.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (software_architecture, research_philosophy, symbolic_contemplative)",
                },
                "include_historical": {
                    "type": "boolean",
                    "default": True,
                },
            },
        },
    },
    {
        "name": "deliberate",
        "description": "Execute a structured multi-perspective deliberation (single_model_baseline, independent_perspectives, or deliberative_exchange).",
        "inputSchema": {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {"type": "string"},
                "strategy": {
                    "type": "string",
                    "enum": [
                        "single_model_baseline",
                        "independent_perspectives",
                        "deliberative_exchange",
                    ],
                    "default": "deliberative_exchange",
                },
                "domain": {"type": "string", "default": "research_philosophy"},
                "perspectives": {"type": "array", "items": {"type": "string"}},
                "provider": {"type": "string", "default": "fake"},
            },
        },
    },
    {
        "name": "compare_deliberations",
        "description": "Compare single-model baseline against independent perspectives and deliberative exchange on a question.",
        "inputSchema": {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {"type": "string"},
                "domain": {"type": "string", "default": "research_philosophy"},
                "perspectives": {"type": "array", "items": {"type": "string"}},
                "provider": {"type": "string", "default": "fake"},
            },
        },
    },
    {
        "name": "evaluate_deliberation",
        "description": "Run a deliberation and score its output against domain-specific epistemic and trade-off rubrics.",
        "inputSchema": {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {"type": "string"},
                "strategy": {"type": "string", "default": "deliberative_exchange"},
                "domain": {"type": "string", "default": "research_philosophy"},
                "required_concepts": {"type": "array", "items": {"type": "string"}},
                "provider": {"type": "string", "default": "fake"},
            },
        },
    },
]


def invoke_mcp_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one of the Perspective Loom MCP tool contracts deterministically."""
    args = arguments or {}

    if tool_name == "list_perspectives":
        specs = DEFAULT_REGISTRY.list_all(
            domain=args.get("domain"),
            include_historical=bool(args.get("include_historical", True)),
        )
        return {"perspectives": [s.to_dict() for s in specs]}

    if tool_name == "deliberate":
        ontology_items = [
            SymbolOntologyEntry(**entry).to_evidence_item()
            for entry in args.get("symbol_ontology", [])
            if isinstance(entry, dict)
        ]
        provider_name = str(args.get("provider") or "fake")
        req = DeliberationRequest(
            question=str(args.get("question") or ""),
            strategy=str(args.get("strategy") or "deliberative_exchange"),
            domain=str(args.get("domain") or "research_philosophy"),
            perspective_names=list(args.get("perspectives") or []),
            evidence=ontology_items,
            provider_name=provider_name,
        )
        engine = DeliberationEngine(
            registry=DEFAULT_REGISTRY,
            provider=get_model_provider(provider_name),
        )
        return engine.run(req).to_dict()

    if tool_name == "compare_deliberations":
        provider_name = str(args.get("provider") or "fake")
        runner = ExperimentRunner(provider_name=provider_name)
        return runner.compare_on_question(
            question=str(args.get("question") or ""),
            domain=str(args.get("domain") or "research_philosophy"),
            perspective_names=args.get("perspectives"),
            required_concepts=args.get("required_concepts"),
        )

    if tool_name == "evaluate_deliberation":
        provider_name = str(args.get("provider") or "fake")
        provider = get_model_provider(provider_name)
        req = DeliberationRequest(
            question=str(args.get("question") or ""),
            strategy=str(args.get("strategy") or "deliberative_exchange"),
            domain=str(args.get("domain") or "research_philosophy"),
            provider_name=provider_name,
        )
        engine = DeliberationEngine(registry=DEFAULT_REGISTRY, provider=provider)
        run_res = engine.run(req)
        evaluator = DeliberationEvaluator(judge_provider=provider)
        scorecard = evaluator.evaluate_run(
            run_res,
            required_concepts=args.get("required_concepts"),
        )
        return {
            "run": run_res.to_dict(),
            "scorecard": scorecard.to_dict(),
        }

    raise KeyError(f"Unknown MCP tool: '{tool_name}'")
