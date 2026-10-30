import json
import logging

from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST

from ai_app.http import load_json_object
from ai_app.models.history import History
from ai_app.models.llm_role import LLMRole
from ai_app.security import csrf_protect_session, resolve_request_user
from ai_app.services.dialogue_generator import DialogueGenerator
from ai_app.services.model_rotation import OpenAIService

logger = logging.getLogger("ai_app")


@csrf_protect_session
@require_POST
def ask_role(request: HttpRequest) -> JsonResponse:
    try:
        user_obj, auth_err = resolve_request_user(request, require_explicit_identity=False)
        if auth_err is not None or user_obj is None:
            return auth_err or JsonResponse({"error": "Authentication failed"}, status=401)

        if not request.body:
            return JsonResponse({"error": "Empty request body"}, status=400)

        data = load_json_object(request.body)
        user_prompt = str(data.get("prompt") or "").strip()
        role_name = str(data.get("role") or "").strip()
        use_ollama = bool(data.get("use_ollama", False))

        if not user_prompt or not role_name:
            return JsonResponse({"error": "Missing prompt or role"}, status=400)

        if len(user_prompt) > 10000:
            return JsonResponse({"error": "Prompt exceeds 10,000 character limit"}, status=400)

        role_obj = LLMRole.objects.get(name=role_name)
        openai_service = OpenAIService(use_ollama=use_ollama)
        dialogue_generator = DialogueGenerator(openai_service)

        result = dialogue_generator.process_single_role(role_name, user_prompt)

        History.objects.create(
            user=user_obj,
            prompt=user_prompt,
            response=result["raw_content"],
            role=role_obj,
        )

        return JsonResponse(
            {
                "response": result["response_data"],
                "collaboration": (
                    result["collab_decision"]
                    if result["collab_decision"].get("should_collaborate")
                    else None
                ),
            }
        )

    except (json.JSONDecodeError, ValueError):
        logger.warning("Invalid JSON payload received on ask_role")
        return JsonResponse({"error": "Invalid JSON format"}, status=400)
    except LLMRole.DoesNotExist:
        return JsonResponse({"error": f"Role '{role_name}' not found"}, status=404)
    except Exception as exc:
        logger.error(f"Error in ask_role processing: {type(exc).__name__}")
        return JsonResponse({"error": "Internal server error"}, status=500)


@csrf_protect_session
@require_POST
def full_dialogue(request: HttpRequest) -> JsonResponse:
    try:
        _, auth_err = resolve_request_user(request, require_explicit_identity=False)
        if auth_err is not None:
            return auth_err

        if not request.body:
            return JsonResponse({"error": "Empty request body"}, status=400)

        data = load_json_object(request.body)
        user_prompt = str(data.get("prompt") or "").strip()
        should_debate = bool(data.get("debate", False))
        use_ollama = bool(data.get("use_ollama", False))

        if not user_prompt:
            return JsonResponse({"error": "No prompt provided"}, status=400)

        if len(user_prompt) > 10000:
            return JsonResponse({"error": "Prompt exceeds 10,000 character limit"}, status=400)

        openai_service = OpenAIService(use_ollama=use_ollama)
        dialogue_generator = DialogueGenerator(openai_service)
        result = dialogue_generator.process_full_dialogue(user_prompt, should_debate)

        return JsonResponse(
            {
                "original_prompt": user_prompt,
                "conversation": result["conversation"],
                "final_analysis": result["final_analysis"],
            }
        )

    except (json.JSONDecodeError, ValueError):
        logger.warning("Invalid JSON payload received on full_dialogue")
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as exc:
        logger.error(f"Error in full_dialogue: {type(exc).__name__}")
        return JsonResponse({"error": "Internal server error"}, status=500)


@csrf_protect_session
@require_POST
def stream_dialogue(request: HttpRequest):
    try:
        _, auth_err = resolve_request_user(request, require_explicit_identity=False)
        if auth_err is not None:
            return auth_err

        if not request.body:
            return JsonResponse({"error": "Empty request body"}, status=400)

        data = load_json_object(request.body)
        user_prompt = str(data.get("prompt") or "").strip()
        should_debate = bool(data.get("debate", False))
        use_ollama = bool(data.get("use_ollama", False))
        if not user_prompt:
            return JsonResponse({"error": "No prompt provided"}, status=400)

        def response_stream():
            openai_service = OpenAIService(use_ollama=use_ollama)
            dialogue_generator = DialogueGenerator(openai_service)

            yield json.dumps({"type": "start", "data": {"prompt": user_prompt}}) + "\n"

            for response in dialogue_generator.stream_full_dialogue(user_prompt, should_debate):
                yield json.dumps(response) + "\n"

            yield json.dumps({"type": "complete", "data": None}) + "\n"

        return StreamingHttpResponse(response_stream(), content_type="application/x-ndjson")

    except (json.JSONDecodeError, ValueError):
        logger.warning("Invalid JSON payload received on stream_dialogue")
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as exc:
        logger.error(f"Error in stream_dialogue: {type(exc).__name__}")
        return JsonResponse({"error": "Internal server error"}, status=500)
