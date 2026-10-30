"""
Model Provider Abstraction for Perspective Loom.

Provides a unified, testable protocol for model execution across:
1. `FakeModelProvider`: Deterministic, zero-cost, offline provider for CI and reproducible tests.
2. `OpenAICompatibleProvider`: Supports GitHub Models (`https://models.inference.ai.azure.com`) and OpenAI.
3. `OllamaProvider`: Supports local Ollama execution with proper model configuration and no stdout leaks.

Includes timeout enforcement, bounded retries, token usage accounting, and cost estimation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

logger = logging.getLogger("ai_app")

# Approximate per-1k-token pricing for cost transparency in traces & benchmarks
MODEL_PRICING_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.00015, 0.00060),
    "gpt-4o": (0.00250, 0.01000),
    "gpt-3.5-turbo": (0.00050, 0.00150),
    "llama3.2": (0.0, 0.0),
    "fake-deterministic-v1": (0.00010, 0.00030),  # Simulated nominal cost for strategy comparisons
}


def estimate_tokens(text: str) -> int:
    """Fast, deterministic token approximation (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_cost_usd(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_rate, out_rate = MODEL_PRICING_PER_1K_TOKENS.get(model_name, (0.00015, 0.00060))
    return round((prompt_tokens / 1000.0) * in_rate + (completion_tokens / 1000.0) * out_rate, 6)


@dataclass
class ProviderResponse:
    """Standardized response envelope from any model provider."""

    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    retries: int = 0


class ModelProvider(Protocol):
    """Protocol implemented by all model providers."""

    provider_name: str
    default_model: str

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        response_format: str | None = None,
    ) -> ProviderResponse: ...

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Iterator[str]: ...


class FakeModelProvider:
    """
    Deterministic model provider for unit tests, CI, and offline evaluation verification.

    Generates structured, context-aware responses keyed by the prompt and perspective
    instructions so that single-model, multi-perspective, and deliberative-exchange
    workflows can be tested end-to-end without paid API credentials.
    """

    provider_name = "fake"
    default_model = "fake-deterministic-v1"

    def __init__(
        self,
        model_name: str | None = None,
        fail_on_roles: set[str] | None = None,
    ) -> None:
        self.default_model = model_name or self.default_model
        self.fail_on_roles = fail_on_roles or set()

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        response_format: str | None = None,
    ) -> ProviderResponse:
        t0 = time.perf_counter()
        used_model = model or self.default_model
        system_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        user_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")

        for role_to_fail in self.fail_on_roles:
            if (
                role_to_fail.lower() in system_text.lower()
                or role_to_fail.lower() in user_text.lower()
            ):
                raise RuntimeError(f"Simulated provider failure for role '{role_to_fail}'")

        content = self._synthesize_deterministic_response(system_text, user_text, response_format)
        prompt_tokens = estimate_tokens(system_text + "\n" + user_text)
        completion_tokens = min(max_tokens, estimate_tokens(content))
        latency_ms = round((time.perf_counter() - t0) * 1000.0 + 1.5, 2)
        cost = estimate_cost_usd(used_model, prompt_tokens, completion_tokens)

        return ProviderResponse(
            content=content,
            model=used_model,
            provider=self.provider_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=cost,
            retries=0,
        )

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Iterator[str]:
        resp = self.complete(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        words = resp.content.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")

    def _synthesize_deterministic_response(
        self,
        system_text: str,
        user_text: str,
        response_format: str | None,
    ) -> str:
        combined = f"{system_text}\n{user_text}"
        digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:8]

        # 1. Legacy collaboration decision check
        if "should_collaborate" in user_text and "chosen_collaborator" in user_text:
            should_collab = any(
                kw in user_text.lower()
                for kw in ["quantum", "dream", "void", "meaning", "architecture", "transform"]
            )
            chosen = "Quantum Philosopher"
            for line in user_text.splitlines():
                line_s = line.strip()
                if line_s.startswith("- ") and ":" in line_s:
                    chosen = line_s[2:].split(":", 1)[0].strip()
                    break
            return json.dumps(
                {
                    "should_collaborate": should_collab,
                    "chosen_collaborator": chosen if should_collab else "",
                    "reasoning": (
                        f"Cross-perspective synthesis with {chosen} adds complementary methodological depth."
                        if should_collab
                        else "Primary perspective suffices for this direct query."
                    ),
                }
            )

        # 2. Legacy array-formatted role response
        if "Format your response exactly like this:" in system_text and "[" in system_text:
            role_name = "Perspective"
            if "You are hosting a dialogue between " in system_text:
                header = system_text.split("You are hosting a dialogue between ", 1)[1].split(
                    ".", 1
                )[0]
                parts = [p.strip() for p in header.split(" and ")]
                primary = parts[0] if parts else "Primary"
                secondary = parts[1] if len(parts) > 1 else "Collaborator"
                return json.dumps(
                    [
                        {
                            "role": primary,
                            "response": f"From the {primary} methodological lens, we first distinguish empirical facts from interpretive meaning ({digest}).",
                        },
                        {
                            "role": secondary,
                            "response": f"Complementing {primary}, {secondary} highlights the boundary conditions and unexamined assumptions.",
                        },
                        {
                            "role": "Synthesis",
                            "response": f"Integrating {primary} and {secondary} preserves both structural rigor and interpretive nuance.",
                        },
                    ]
                )
            if "You are " in system_text:
                role_name = system_text.split("You are ", 1)[1].splitlines()[0].rstrip(".")
            return json.dumps(
                [
                    {
                        "role": role_name,
                        "response": f"{role_name} analysis: examining core premises, evidence boundaries, and open uncertainties ({digest}).",
                    }
                ]
            )

        # 3. Engine structured JSON outputs (analysis / critique / synthesis / judge)
        if response_format == "analysis_json":
            return self._build_fake_analysis_json(system_text, user_text, digest)
        if response_format == "critique_json":
            return self._build_fake_critique_json(system_text, user_text, digest)
        if response_format == "synthesis_json":
            return self._build_fake_synthesis_json(system_text, user_text, digest)
        if response_format == "baseline_json":
            return self._build_fake_baseline_json(system_text, user_text, digest)
        if response_format == "judge_json":
            return self._build_fake_judge_json(system_text, user_text)

        # 4. General text fallback (legacy full_dialogue / synthesis)
        return (
            f"Structured perspective response [{digest}]: Evaluating the question across "
            "empirical evidence, architectural trade-offs, and interpretive boundaries while "
            "preserving uncertainty where claims cannot be verified."
        )

    def _build_fake_analysis_json(self, system_text: str, user_text: str, digest: str) -> str:
        perspective_name = "Perspective"
        for line in system_text.splitlines():
            if line.startswith("PERSPECTIVE_NAME:"):
                perspective_name = line.split(":", 1)[1].strip()
                break

        evidence_refs: list[str] = []
        for line in user_text.splitlines():
            if line.strip().startswith("[EVIDENCE "):
                ref = line.strip().split("]", 1)[0].replace("[EVIDENCE ", "").strip()
                evidence_refs.append(ref)

        q_lower = user_text.lower()
        if "pragmatist" in perspective_name.lower():
            thesis = (
                "Favor modular monolith boundaries with PostgreSQL transactional guarantees and explicit timeouts "
                "before introducing distributed brokers or microservices."
            )
            analysis = (
                "Given the stated workload and team constraints, network-partitioned services or external message "
                "brokers add operational failure modes without proportional throughput gains. Retain SQLite for "
                "zero-dependency local CI and use PostgreSQL with connection pooling in deployed environments."
            )
            limitations = [
                "Assumes synchronous or bounded streaming latency under 30s per deliberation run.",
                "Requires revisit if concurrent deliberation throughput exceeds single-node database IOPS.",
            ]
            uncertainty = "low"
        elif "security" in perspective_name.lower():
            thesis = (
                "Enforce per-user data isolation, header/session authentication, secret redaction in logs, "
                "and strict schema validation at all transport boundaries."
            )
            analysis = (
                "Unauthenticated history endpoints and shared default accounts create immediate cross-user data "
                "exposure. All private deliberation runs must be scoped to an authenticated principal or isolated "
                "API key, with secrets and raw personal prompts stripped from operational logs."
            )
            limitations = [
                "API-key authentication must be paired with TLS termination at the reverse proxy in production.",
            ]
            uncertainty = "low"
        elif "domain boundary" in perspective_name.lower():
            thesis = (
                "Decouple the deliberation orchestrator and perspective schemas from Django HTTP views so the "
                "same engine can serve REST, NDJSON streaming, CLI benchmarks, and future MCP tools."
            )
            analysis = (
                "By defining typed dataclasses (`DeliberationRequest`, `PerspectiveSpec`, `DeliberationRunResult`) "
                "and a `ModelProvider` protocol, downstream consumers such as Nexus Flow can supply custom symbol "
                "ontologies or evidence items without touching Django ORM internals."
            )
            limitations = [
                "Avoid building speculative network RPC layers until cross-repository MCP integration is scheduled.",
            ]
            uncertainty = "low"
        elif "epistemologist" in perspective_name.lower():
            thesis = (
                "Separate falsifiable empirical claims and measurable latency/cost metrics from philosophical or "
                "symbolic interpretations."
            )
            analysis = (
                "Where empirical benchmarks or physical measurements exist, claims must be evaluated against a "
                "null baseline (single-model execution). Symbolic, phenomenological, or metaphysical claims are "
                "non-falsifiable interpretive frameworks and must be labeled accordingly rather than presented as fact."
            )
            limitations = [
                "Empirical metrics cannot adjudicate personal existential meaning or aesthetic resonance.",
            ]
            uncertainty = "moderate"
        elif "quantum" in perspective_name.lower():
            thesis = (
                "Examine how observation framing and contextuality shape the space of possible answers without "
                "conflating physical formalism with mystical claims."
            )
            analysis = (
                "In quantum foundations, measurement outcomes depend on the experimental arrangement (contextuality). "
                "By analogy—and strictly as a philosophical metaphor rather than physical proof—different interpretive "
                "lenses surface distinct aspects of a complex problem that a single framing obscures."
            )
            limitations = [
                "Analogical extension from physics to cognition is heuristic, not a physical mechanism.",
            ]
            uncertainty = "moderate"
        else:
            # Symbolic / contemplative / existential perspectives
            thesis = (
                f"Through the {perspective_name} lens, treat the inquiry as an open-ended exploration of meaning, "
                "agency, and ambiguity rather than a closed factual lookup."
            )
            analysis = (
                f"Applying the {perspective_name} interpretive methodology ({digest}), we examine the tension "
                "between structured order and lived uncertainty. Rather than imposing a single authoritative symbol "
                "meaning, this perspective surfaces multiple possible associations—inviting the questioner to weigh "
                "their own lived context alongside philosophical and contemplative traditions."
                if "dream" in q_lower or "symbol" in q_lower or "meaning" in q_lower
                else f"From the {perspective_name} vantage point ({digest}), we question unexamined assumptions, "
                "highlight long-term human consequences, and distinguish contemplative metaphor from empirical fact."
            )
            limitations = [
                f"{perspective_name} offers a symbolic/philosophical lens, not empirical or clinical authority.",
                "Personal associations of the user take precedence over canonical archetype definitions.",
            ]
            uncertainty = "high"

        return json.dumps(
            {
                "core_thesis": thesis,
                "analysis": analysis,
                "supporting_evidence_refs": evidence_refs,
                "assumptions_and_limitations": limitations,
                "uncertainty_level": uncertainty,
            }
        )

    def _build_fake_critique_json(self, system_text: str, user_text: str, digest: str) -> str:
        critic_name = "Critic"
        for line in system_text.splitlines():
            if line.startswith("CRITIC_PERSPECTIVE:"):
                critic_name = line.split(":", 1)[1].strip()
                break

        targets: list[str] = []
        for line in user_text.splitlines():
            if line.startswith("- Peer ["):
                peer = line.split("- Peer [", 1)[1].split("]", 1)[0]
                if peer != critic_name:
                    targets.append(peer)

        return json.dumps(
            {
                "target_perspectives": targets or ["Peer Perspectives"],
                "points_of_tension": [
                    f"{critic_name} notes tension between operational/empirical minimalism and broader interpretive exploration ({digest}).",
                    "Peer analyses weight immediate implementation constraints differently from long-horizon extensibility.",
                ],
                "evidence_challenges": [
                    "Ensure every causal or performance claim cites supplied evidence or explicit benchmark metrics rather than analogy.",
                ],
                "constructive_revision": (
                    f"Integrate {critic_name}'s boundary constraints with peer insights by separating verified "
                    "requirements (Tier 1) from optional evolutionary extensions and interpretive hypotheses (Tier 2)."
                ),
            }
        )

    def _build_fake_synthesis_json(self, system_text: str, user_text: str, digest: str) -> str:
        return json.dumps(
            {
                "summary": (
                    "Multi-perspective deliberation converges on a layered resolution: enforce strict empirical, "
                    "security, and operational baselines first, while preserving distinct interpretive and architectural "
                    f"trade-offs where genuine uncertainty remains ({digest})."
                ),
                "convergent_agreements": [
                    "Distinguish verified empirical evidence and concrete system constraints from metaphorical or speculative claims.",
                    "Maintain clean boundaries between core domain schemas, model providers, and transport layers.",
                    "Protect user privacy, isolate history records, and surface explicit uncertainty bounds.",
                ],
                "preserved_disagreements": [
                    "Trade-off between strict minimalism (avoiding any extra abstraction) and extensible schema contracts for future consumers.",
                    "Tension between purely falsificationist criteria and value-laden existential or symbolic interpretation on open-ended questions.",
                ],
                "uncertainties_and_limits": [
                    "Real-world latency and cost trade-offs depend on the chosen hosted or local model provider under production concurrency.",
                    "For symbolic or personal prompts, no automated engine can replace the user's own contextual associations.",
                ],
                "open_questions": [
                    "At what concrete workload or latency threshold should synchronous deliberation transition to asynchronous background workers?",
                    "Which domain-specific evaluation rubrics correlate strongest with human expert judgment?",
                ],
                "actionable_recommendations": [
                    "Adopt the smallest deterministic architecture that satisfies verified constraints and test it with reproducible baselines.",
                    "Record full execution traces (latency, token usage, cost, and disagreements) so multi-perspective value can be audited empirically.",
                ],
                "epistemic_note": (
                    "This synthesis separates empirical/technical constraints from philosophical and symbolic interpretations; "
                    "unresolved tensions are intentionally preserved rather than flattened."
                ),
            }
        )

    def _build_fake_baseline_json(self, system_text: str, user_text: str, digest: str) -> str:
        return json.dumps(
            {
                "summary": (
                    f"Single-model direct response ({digest}): Provides a concise, unified answer addressing the prompt "
                    "from a single generalist perspective without independent cross-examination."
                ),
                "convergent_agreements": [
                    "Direct single-pass analysis of the primary question and stated constraints.",
                ],
                "preserved_disagreements": [],
                "uncertainties_and_limits": [
                    "Generated in a single pass without independent perspective critique or cross-examination.",
                ],
                "open_questions": [
                    "Would independent domain perspectives surface hidden trade-offs missed by a single prompt?",
                ],
                "actionable_recommendations": [
                    "Apply standard domain best practices for the stated problem.",
                ],
                "epistemic_note": "Single-model baseline output.",
            }
        )

    def _build_fake_judge_json(self, system_text: str, user_text: str) -> str:
        return json.dumps(
            {
                "clarity": 4.2,
                "tradeoff_depth": 4.5,
                "epistemic_honesty": 4.6,
                "constraint_satisfaction": 4.4,
                "rationale": (
                    "Deterministic evaluation rubric assessment: response explicitly separates evidence from "
                    "interpretation and documents concrete trade-offs and uncertainties."
                ),
            }
        )


class OpenAICompatibleProvider:
    """
    Provider for OpenAI and GitHub Models (`https://models.inference.ai.azure.com`).
    Uses the `openai` SDK when installed, with a clean stdlib `urllib` fallback.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "gpt-4o-mini",
        provider_name: str = "github_models",
    ) -> None:
        self.provider_name = provider_name
        self.default_model = default_model
        self.api_key = api_key or os.getenv("GITHUB_TOKEN") or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = (
            base_url or os.getenv("OPENAI_BASE_URL") or "https://models.inference.ai.azure.com"
        )
        parsed_base_url = urlparse(self.base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("Provider base URL must use HTTP or HTTPS.")

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        response_format: str | None = None,
    ) -> ProviderResponse:
        if not self.api_key:
            raise RuntimeError(
                f"Missing API credentials for provider '{self.provider_name}'. "
                "Set GITHUB_TOKEN or OPENAI_API_KEY, or use provider='fake' / 'ollama'."
            )

        used_model = model or self.default_model
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            t0 = time.perf_counter()
            try:
                content, p_tokens, c_tokens = self._call_api(
                    messages=messages,
                    model=used_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                )
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                cost = estimate_cost_usd(used_model, p_tokens, c_tokens)
                return ProviderResponse(
                    content=content,
                    model=used_model,
                    provider=self.provider_name,
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    latency_ms=latency_ms,
                    estimated_cost_usd=cost,
                    retries=attempt,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    f"Provider {self.provider_name} attempt {attempt + 1} failed: {type(exc).__name__}"
                )
                if attempt < max_retries:
                    time.sleep(min(1.0 * (attempt + 1), 3.0))

        raise RuntimeError(
            f"Provider '{self.provider_name}' failed after {max_retries + 1} attempts: {last_error}"
        )

    def _call_api(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
    ) -> tuple[str, int, int]:
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=timeout_seconds,
            )
            response = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            p_tokens = getattr(usage, "prompt_tokens", 0) or estimate_tokens(json.dumps(messages))
            c_tokens = getattr(usage, "completion_tokens", 0) or estimate_tokens(content)
            return content, p_tokens, c_tokens
        except ImportError:
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            payload = json.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            ).encode("utf-8")
            req = urllib.request.Request(  # noqa: S310 - base URL validated as HTTP(S)
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            p_tokens = usage.get("prompt_tokens") or estimate_tokens(json.dumps(messages))
            c_tokens = usage.get("completion_tokens") or estimate_tokens(content)
            return content, p_tokens, c_tokens

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Iterator[str]:
        resp = self.complete(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        yield resp.content


class OllamaProvider:
    """
    Local Ollama provider.
    Fixes historical bugs:
    - Respects configured `model_name` in both sync and streaming calls (never hardcodes `llama2`).
    - Never prints raw tokens to stdout during server execution.
    - Works via the `ollama` package if installed or direct HTTP calls to `OLLAMA_HOST`.
    """

    provider_name = "ollama"

    def __init__(
        self,
        *,
        host: str | None = None,
        default_model: str | None = None,
    ) -> None:
        configured_host = host or os.getenv("OLLAMA_HOST") or "http://localhost:11434"
        if "://" not in configured_host:
            configured_host = f"http://{configured_host}"
        self.host = configured_host.rstrip("/")
        parsed_host = urlparse(self.host)
        if parsed_host.scheme not in {"http", "https"} or not parsed_host.netloc:
            raise ValueError("Ollama host must use HTTP or HTTPS.")
        self.default_model = default_model or os.getenv("DEFAULT_OLLAMA_MODEL") or "llama3.2"

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        response_format: str | None = None,
    ) -> ProviderResponse:
        used_model = model or self.default_model
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            t0 = time.perf_counter()
            try:
                content = self._call_ollama(
                    messages=messages,
                    model=used_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                )
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                p_tokens = estimate_tokens(json.dumps(messages))
                c_tokens = estimate_tokens(content)
                return ProviderResponse(
                    content=content,
                    model=used_model,
                    provider=self.provider_name,
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    latency_ms=latency_ms,
                    estimated_cost_usd=0.0,
                    retries=attempt,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(f"Ollama attempt {attempt + 1} failed: {type(exc).__name__}")
                if attempt < max_retries:
                    time.sleep(0.5 * (attempt + 1))

        raise RuntimeError(f"Ollama provider failed after {max_retries + 1} attempts: {last_error}")

    def _call_ollama(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
    ) -> str:
        try:
            from ollama import Client  # type: ignore

            result = Client(host=self.host, timeout=timeout_seconds).chat(
                model=model,
                messages=messages,
                stream=False,
                options={"temperature": temperature, "num_predict": max_tokens},
            )
            if isinstance(result, dict):
                return result.get("message", {}).get("content", "")
            return getattr(getattr(result, "message", None), "content", "")
        except ImportError:
            url = f"{self.host}/api/chat"
            payload = json.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                }
            ).encode("utf-8")
            req = urllib.request.Request(  # noqa: S310 - host validated as HTTP(S)
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
                body = json.loads(resp.read().decode("utf-8"))
            return body.get("message", {}).get("content", "")

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Iterator[str]:
        used_model = model or self.default_model
        try:
            from ollama import chat  # type: ignore

            stream_iter = chat(
                model=used_model,
                messages=messages,
                stream=True,
                options={"temperature": temperature, "num_predict": max_tokens},
            )
            for chunk in stream_iter:
                if isinstance(chunk, dict):
                    piece = chunk.get("message", {}).get("content", "")
                else:
                    piece = getattr(getattr(chunk, "message", None), "content", "")
                if piece:
                    yield piece
        except ImportError:
            resp = self.complete(
                messages, model=used_model, temperature=temperature, max_tokens=max_tokens
            )
            yield resp.content


def get_model_provider(
    provider_name: str | None = None,
    *,
    use_ollama: bool = False,
    model_name: str | None = None,
) -> ModelProvider:
    """Factory resolving the configured model provider."""
    if use_ollama or provider_name == "ollama":
        return OllamaProvider(default_model=model_name)

    resolved = (provider_name or os.getenv("DEFAULT_MODEL_PROVIDER") or "fake").strip().lower()
    if resolved == "fake":
        return FakeModelProvider(model_name=model_name)
    if resolved in {"openai", "github_models", "hosted"}:
        return OpenAICompatibleProvider(
            default_model=model_name or os.getenv("DEFAULT_HOSTED_MODEL") or "gpt-4o-mini",
            provider_name=resolved,
        )
    raise ValueError(
        f"Unsupported model provider '{resolved}'. Supported: fake, github_models, openai, ollama."
    )
