import logging

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from ai_app.models.history import History
from ai_app.security import resolve_request_user
from ai_app.services.response_formatter import ResponseFormatter

logger = logging.getLogger("ai_app")


@require_GET
def get_conversation_history(request: HttpRequest) -> JsonResponse:
    """
    Return conversation history strictly isolated to the authenticated user
    or explicit `X-Perspective-User` principal. Never dumps cross-user history.
    """
    user_obj, auth_err = resolve_request_user(
        request, require_explicit_identity=True
    )
    if auth_err is not None or user_obj is None:
        return auth_err or JsonResponse({"error": "Unauthorized"}, status=401)

    history = (
        History.objects.filter(user=user_obj)
        .select_related("role", "user")
        .order_by("-created_at")
    )
    history_data = ResponseFormatter.format_history(history)
    return JsonResponse({"user": user_obj.username, "history": history_data})
