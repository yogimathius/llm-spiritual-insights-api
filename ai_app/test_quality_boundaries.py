"""Regression tests for request, ownership, and provider boundaries."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase, TestCase, override_settings

from ai_app.engine.providers import (
    FakeModelProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    get_model_provider,
)
from ai_app.models.deliberation import DeliberationRun
from ai_app.models.llm_role import LLMRole
from ai_app.services.dialogue_generator import DialogueGenerator
from ai_app.views.deliberation import _parse_deliberation_request


class RequestBoundaryTests(TestCase):
    @override_settings(PERSPECTIVE_LOOM_API_KEY="service-key")
    def test_private_routes_reject_requests_without_credentials(self) -> None:
        client = Client()
        for route in (
            "/ai/ask-role/",
            "/ai/full-dialogue/",
            "/ai/stream-dialogue/",
            "/ai/perspectives/",
            "/ai/deliberate/",
            "/ai/deliberate/stream/",
            "/ai/evaluate/",
            "/ai/compare/",
        ):
            with self.subTest(route=route):
                response = client.post(
                    route,
                    data="{}",
                    content_type="application/json",
                    HTTP_X_PERSPECTIVE_USER="alice",
                )
                self.assertEqual(response.status_code, 401)
        for route in ("/ai/history/", "/ai/runs/", "/ai/runs/missing/"):
            with self.subTest(route=route):
                response = client.get(route, HTTP_X_PERSPECTIVE_USER="alice")
                self.assertEqual(response.status_code, 401)
        self.assertFalse(DeliberationRun.objects.exists())

    @override_settings(PERSPECTIVE_LOOM_API_KEY="service-key")
    def test_post_routes_reject_json_arrays_as_bad_requests(self) -> None:
        client = Client()
        for route in (
            "/ai/ask-role/",
            "/ai/full-dialogue/",
            "/ai/stream-dialogue/",
            "/ai/perspectives/",
            "/ai/deliberate/",
            "/ai/deliberate/stream/",
            "/ai/evaluate/",
            "/ai/compare/",
        ):
            with self.subTest(route=route):
                response = client.post(
                    route,
                    data="[]",
                    content_type="application/json",
                    HTTP_X_API_KEY="service-key",
                    HTTP_X_PERSPECTIVE_USER="alice",
                )
                self.assertEqual(response.status_code, 400)

    @override_settings(PERSPECTIVE_LOOM_API_KEY="service-key")
    def test_deliberation_rejects_wrong_numeric_field_types(self) -> None:
        for route in ("/ai/deliberate/", "/ai/deliberate/stream/"):
            with self.subTest(route=route):
                response = self.client.post(
                    route,
                    data=json.dumps({"question": "A question", "max_perspectives": []}),
                    content_type="application/json",
                    HTTP_X_API_KEY="service-key",
                    HTTP_X_PERSPECTIVE_USER="alice",
                )
                self.assertEqual(response.status_code, 400)

    @override_settings(PERSPECTIVE_LOOM_API_KEY="service-key")
    def test_unowned_run_is_not_readable_or_evaluable(self) -> None:
        DeliberationRun.objects.create(run_id="legacy-run", trace_id="legacy-trace", user=None)
        headers = {"HTTP_X_API_KEY": "service-key", "HTTP_X_PERSPECTIVE_USER": "alice"}
        detail = self.client.get("/ai/runs/legacy-run/", **headers)
        evaluation = self.client.post(
            "/ai/evaluate/",
            data=json.dumps({"run_id": "legacy-run"}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(detail.status_code, 403)
        self.assertEqual(evaluation.status_code, 403)

    @override_settings(DEFAULT_MODEL_PROVIDER="ollama")
    def test_deliberation_uses_configured_provider_by_default(self) -> None:
        request = _parse_deliberation_request({"question": "Which approach?"}, "alice")
        self.assertEqual(request.provider_name, "ollama")
        explicit = _parse_deliberation_request(
            {"question": "Which approach?", "provider": "fake"}, "alice"
        )
        self.assertEqual(explicit.provider_name, "fake")

    @override_settings(PERSPECTIVE_LOOM_API_KEY="service-key", DEFAULT_MODEL_PROVIDER="invalid-provider")
    def test_comparison_uses_configured_provider_by_default(self) -> None:
        response = self.client.post(
            "/ai/compare/",
            data=json.dumps({"question": "Which approach?"}),
            content_type="application/json",
            HTTP_X_API_KEY="service-key",
            HTTP_X_PERSPECTIVE_USER="alice",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported model provider", response.json()["error"])

    @override_settings(PERSPECTIVE_LOOM_API_KEY="service-key")
    def test_partial_stream_is_persisted_with_failure_status(self) -> None:
        request_data = {
            "question": "Compare the approaches",
            "strategy": "independent_perspectives",
            "perspectives": ["Systems Pragmatist", "Security & Trust Auditor"],
        }
        with patch(
            "ai_app.views.deliberation.get_model_provider",
            return_value=FakeModelProvider(fail_on_roles={"Security & Trust Auditor"}),
        ):
            response = self.client.post(
                "/ai/deliberate/stream/",
                data=json.dumps(request_data),
                content_type="application/json",
                HTTP_X_API_KEY="service-key",
                HTTP_X_PERSPECTIVE_USER="alice",
            )
            events = [json.loads(chunk) for chunk in response.streaming_content]
        complete = events[-1]
        self.assertEqual(complete["type"], "complete")
        self.assertEqual(complete["result"]["status"], "partial_failure")
        self.assertEqual(
            DeliberationRun.objects.get(run_id=complete["run_id"]).status,
            "partial_failure",
        )


class ProviderBoundaryTests(SimpleTestCase):
    def test_hosted_provider_retries_transient_failure(self) -> None:
        provider = OpenAICompatibleProvider(api_key="test-key")
        with patch.object(
            provider,
            "_call_api",
            side_effect=[TimeoutError("temporary"), ("answer", 12, 4)],
        ), patch("ai_app.engine.providers.time.sleep"):
            result = provider.complete([{"role": "user", "content": "hello"}], max_retries=1)
        self.assertEqual(result.content, "answer")
        self.assertEqual(result.retries, 1)
        self.assertEqual(result.prompt_tokens, 12)

    def test_hosted_provider_exhausts_retry_budget(self) -> None:
        provider = OpenAICompatibleProvider(api_key="test-key")
        with patch.object(provider, "_call_api", side_effect=TimeoutError("temporary")) as call, patch(
            "ai_app.engine.providers.time.sleep"
        ):
            with self.assertRaises(RuntimeError):
                provider.complete([{"role": "user", "content": "hello"}], max_retries=1)
        self.assertEqual(call.call_count, 2)

    def test_ollama_client_receives_requested_timeout(self) -> None:
        observed: dict[str, object] = {}

        class ClientStub:
            def __init__(self, *, host: str, timeout: float) -> None:
                observed.update(host=host, timeout=timeout)

            def chat(self, **kwargs: object) -> dict[str, object]:
                return {"message": {"content": "local answer"}}

        provider = OllamaProvider(host="http://localhost:11434")
        with patch("ollama.Client", ClientStub), patch("ollama.chat", side_effect=AssertionError("global client used")):
            result = provider._call_ollama(
                messages=[{"role": "user", "content": "hello"}],
                model="local-model",
                temperature=0.4,
                max_tokens=100,
                timeout_seconds=1.25,
            )
        self.assertEqual(result, "local answer")
        self.assertEqual(observed, {"host": "http://localhost:11434", "timeout": 1.25})

    @patch.dict("os.environ", {"DEFAULT_HOSTED_MODEL": ""})
    def test_empty_hosted_model_setting_uses_safe_default(self) -> None:
        provider = get_model_provider("openai")
        self.assertEqual(provider.default_model, "gpt-4o-mini")


class DialoguePrivacyTests(TestCase):
    def setUp(self) -> None:
        self.role = LLMRole.objects.create(
            name="Test Role", description="A test role", prompt_template="Respond carefully"
        )

    def test_invalid_model_json_is_returned_without_entering_logs(self) -> None:
        private_response = "private-model-text-98432"
        service = Mock()
        service.create_completion.side_effect = [
            '{"should_collaborate": false}',
            private_response,
        ]
        generator = DialogueGenerator(service)
        with self.assertLogs("ai_app", level="WARNING") as captured:
            result = generator.process_single_role(self.role.name, "question")
        self.assertEqual(result["response_data"][0]["response"], private_response)
        self.assertNotIn(private_response, "\n".join(captured.output))

    def test_processing_error_does_not_log_raw_model_response(self) -> None:
        private_response = '[{"role": "Test Role", "response": 42, "note": "private-98432"}]'
        service = Mock()
        service.create_completion.side_effect = [
            '{"should_collaborate": false}',
            private_response,
        ]
        generator = DialogueGenerator(service)
        with self.assertLogs("ai_app", level="ERROR") as captured:
            result = generator.process_single_role(self.role.name, "question")
        self.assertEqual(result["response_data"][0]["response"], "Error processing response")
        self.assertNotIn("private-98432", "\n".join(captured.output))

    def test_full_dialogue_error_does_not_log_provider_exception_detail(self) -> None:
        service = Mock()
        service.create_completion.side_effect = RuntimeError("private-token-98432")
        generator = DialogueGenerator(service)
        with self.assertLogs("ai_app", level="ERROR") as captured:
            result = generator.process_full_dialogue("question", False)
        self.assertEqual(result["conversation"], [])
        self.assertNotIn("private-token-98432", "\n".join(captured.output))

    def test_stream_error_does_not_disclose_provider_exception_detail(self) -> None:
        service = Mock()
        service.create_completion.side_effect = RuntimeError("private-token-98432")
        generator = DialogueGenerator(service)
        with self.assertLogs("ai_app", level="ERROR") as captured:
            events = list(generator.stream_full_dialogue("question", False))
        error = next(event for event in events if event["type"] == "error")
        self.assertEqual(error["data"]["error"], "Response generation failed")
        self.assertNotIn("private-token-98432", "\n".join(captured.output))

    def test_synthesis_failure_does_not_log_provider_exception_detail(self) -> None:
        service = Mock()
        service.create_completion.side_effect = ["role response", RuntimeError("private-synth-98432")]
        generator = DialogueGenerator(service)
        with self.assertLogs("ai_app", level="ERROR") as captured:
            with self.assertRaises(RuntimeError):
                generator.process_full_dialogue("question", False)
        self.assertNotIn("private-synth-98432", "\n".join(captured.output))

    def test_stream_synthesis_failure_returns_generic_error(self) -> None:
        service = Mock()
        service.create_completion.side_effect = ["role response", RuntimeError("private-synth-98432")]
        generator = DialogueGenerator(service)
        with self.assertLogs("ai_app", level="ERROR") as captured:
            events = list(generator.stream_full_dialogue("question", False))
        error = next(event for event in events if event["type"] == "error")
        self.assertEqual(error["data"]["error"], "Response generation failed")
        self.assertNotIn("private-synth-98432", "\n".join(captured.output))
