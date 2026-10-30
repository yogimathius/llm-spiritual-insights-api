"""
Typed domain schemas for the Perspective Loom deliberation engine.

Designed with standard dataclasses and strict validation so the core domain
has zero coupling to Django request handlers or external framework lock-in,
while offering seamless JSON serialization and optional Pydantic interoperability.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class DeliberationStrategy(str, Enum):
    """Supported deliberation strategies for execution and evaluation."""

    SINGLE_MODEL_BASELINE = "single_model_baseline"
    INDEPENDENT_PERSPECTIVES = "independent_perspectives"
    DELIBERATIVE_EXCHANGE = "deliberative_exchange"


class EpistemicType(str, Enum):
    """Distinguishes factual evidence from philosophical or symbolic claims."""

    EMPIRICAL_EVIDENCE = "empirical_evidence"
    ARCHITECTURAL_TRADEOFF = "architectural_tradeoff"
    PHILOSOPHICAL_INQUIRY = "philosophical_inquiry"
    SYMBOLIC_METAPHOR = "symbolic_metaphor"
    CONTEMPLATIVE_TRADITION = "contemplative_tradition"


class DomainCategory(str, Enum):
    """Primary operating domains for Perspective Loom."""

    SOFTWARE_ARCHITECTURE = "software_architecture"
    RESEARCH_PHILOSOPHY = "research_philosophy"
    SYMBOLIC_CONTEMPLATIVE = "symbolic_contemplative"


@dataclass(frozen=True)
class PerspectiveSpec:
    """
    Versioned, configurable role/perspective definition.

    Roles represent structured interpretive methodologies rather than
    authoritative personalities.
    """

    slug: str
    name: str
    version: str
    domain: str
    purpose: str
    system_instructions: str
    interpretive_methodology: str
    boundaries_and_limitations: str
    epistemic_type: str = EpistemicType.PHILOSOPHICAL_INQUIRY.value
    permitted_tools: list[str] = field(default_factory=list)
    evidence_requirements: str = (
        "Distinguish established empirical facts from interpretive or metaphorical claims."
    )
    preferred_model: str = "gpt-4o-mini"
    max_tokens: int = 350
    temperature: float = 0.7
    collaboration_triggers: list[str] = field(default_factory=list)
    recommended_collaborators: list[str] = field(default_factory=list)
    is_historical_persona: bool = False

    def validate(self) -> None:
        if not self.slug or not self.slug.strip():
            raise ValueError("PerspectiveSpec.slug must not be empty")
        if not self.name or not self.name.strip():
            raise ValueError("PerspectiveSpec.name must not be empty")
        if not self.version or not self.version.strip():
            raise ValueError("PerspectiveSpec.version must not be empty")
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError("PerspectiveSpec.temperature must be between 0.0 and 2.0")
        if self.max_tokens < 16 or self.max_tokens > 8192:
            raise ValueError("PerspectiveSpec.max_tokens must be between 16 and 8192")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceItem:
    """Explicit evidence supplied by the user or retrieved via verified tools."""

    source_id: str
    title: str
    content: str
    source_type: str = "user_provided"  # user_provided | benchmark_constraint | tool_verified
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeliberationRequest:
    """Validated input schema for initiating a deliberation run."""

    question: str
    strategy: str = DeliberationStrategy.DELIBERATIVE_EXCHANGE.value
    domain: str = DomainCategory.RESEARCH_PHILOSOPHY.value
    perspective_names: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    provider_name: str = "fake"
    model_name: str | None = None
    max_perspectives: int = 4
    enable_critique_round: bool = True
    timeout_seconds: float = 30.0
    max_retries: int = 2
    user_id: str | None = None
    human_intervention_note: str | None = None
    trace_id: str = field(default_factory=lambda: f"trace-{uuid.uuid4().hex[:12]}")

    def validate(self) -> None:
        if not self.question or not self.question.strip():
            raise ValueError("Question must be a non-empty string.")
        if len(self.question) > 10000:
            raise ValueError("Question exceeds maximum length of 10,000 characters.")
        valid_strategies = {s.value for s in DeliberationStrategy}
        if self.strategy not in valid_strategies:
            raise ValueError(
                f"Invalid strategy '{self.strategy}'. Must be one of {sorted(valid_strategies)}"
            )
        if self.max_perspectives < 1 or self.max_perspectives > 12:
            raise ValueError("max_perspectives must be between 1 and 12.")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 0 and 300.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerspectiveAnalysis:
    """Independent analysis produced by a single perspective."""

    perspective_name: str
    perspective_slug: str
    perspective_version: str
    epistemic_type: str
    core_thesis: str
    analysis: str
    supporting_evidence_refs: list[str] = field(default_factory=list)
    assumptions_and_limitations: list[str] = field(default_factory=list)
    uncertainty_level: str = "moderate"  # low | moderate | high
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model_used: str = ""
    status: str = "succeeded"  # succeeded | failed
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CritiqueExchange:
    """Controlled cross-examination critique from one perspective on peer analyses."""

    critic_perspective: str
    target_perspectives: list[str]
    points_of_tension: list[str]
    evidence_challenges: list[str]
    constructive_revision: str
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model_used: str = ""
    status: str = "succeeded"
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SynthesisResult:
    """
    Final synthesis that preserves meaningful differences, epistemic boundaries,
    uncertainties, and open questions.
    """

    summary: str
    convergent_agreements: list[str]
    preserved_disagreements: list[str]
    uncertainties_and_limits: list[str]
    open_questions: list[str]
    actionable_recommendations: list[str]
    epistemic_note: str
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepTrace:
    """Granular trace event for a single execution step."""

    step_name: str
    actor: str
    status: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    retries: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionTrace:
    """Aggregate inspectable telemetry across a complete deliberation run."""

    trace_id: str
    provider: str
    model: str
    started_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    completed_at: str | None = None
    total_latency_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_estimated_cost_usd: float = 0.0
    total_retries: int = 0
    partial_failures: int = 0
    steps: list[StepTrace] = field(default_factory=list)

    def record_step(self, step: StepTrace) -> None:
        self.steps.append(step)
        self.total_latency_ms = round(self.total_latency_ms + step.latency_ms, 2)
        self.total_prompt_tokens += step.prompt_tokens
        self.total_completion_tokens += step.completion_tokens
        self.total_tokens = self.total_prompt_tokens + self.total_completion_tokens
        self.total_estimated_cost_usd = round(
            self.total_estimated_cost_usd + step.estimated_cost_usd, 6
        )
        self.total_retries += step.retries
        if step.status != "succeeded":
            self.partial_failures += 1

    def finalize(self) -> None:
        self.completed_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeliberationRunResult:
    """Complete structured output of a deliberation run."""

    run_id: str
    question: str
    strategy: str
    domain: str
    status: str  # completed | partial_failure | failed
    perspectives_used: list[dict[str, str]]
    evidence_supplied: list[EvidenceItem]
    independent_analyses: list[PerspectiveAnalysis]
    critiques: list[CritiqueExchange]
    synthesis: SynthesisResult
    trace: ExecutionTrace

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
