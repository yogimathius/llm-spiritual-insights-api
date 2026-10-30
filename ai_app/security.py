"""
Authentication, authorization, and user-isolation helpers for Perspective Loom.

Eliminates the historical defects:
- Hardcoded reliance on `User.objects.get(username="testuser")` (which crashed with 500 if missing)
- Unauthenticated global history exposure (`/ai/history/` returning every user's conversations)
- Missing API key and user-scoping controls
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt, csrf_protect

from ai_app.models.user import User

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.\-@]{1,64}$")


def check_api_key_if_required(request: HttpRequest) -> JsonResponse | None:
    """
    If `settings.REQUIRE_AUTH` is enabled or `PERSPECTIVE_LOOM_API_KEY` is configured,
    verify that the caller provides either:
    - An authenticated Django session user (`request.user.is_authenticated`)
    - Header `X-API-Key: <key>` or `Authorization: Bearer <key>`
    """
    configured_key = getattr(settings, "PERSPECTIVE_LOOM_API_KEY", "") or ""
    require_auth = getattr(settings, "REQUIRE_AUTH", False)

    django_user = getattr(request, "user", None)
    if django_user is not None and getattr(django_user, "is_authenticated", False):
        return None

    provided_key = request.headers.get("X-API-Key", "").strip()
    if not provided_key:
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.lower().startswith("bearer "):
            provided_key = auth_header[7:].strip()

    if configured_key:
        if not provided_key or not hmac.compare_digest(provided_key, configured_key):
            return JsonResponse(
                {"error": "Unauthorized: valid API key or authenticated session required."},
                status=401,
            )
        return None

    if require_auth:
        return JsonResponse(
            {"error": "Authentication required."},
            status=401,
        )

    return None


def resolve_request_user(
    request: HttpRequest,
    *,
    require_explicit_identity: bool = False,
) -> tuple[User | None, JsonResponse | None]:
    """
    Resolve the `ai_app.models.user.User` record scoped to the current request.

    Resolution order:
    1. Authenticated Django `request.user`
    2. `X-Perspective-User` HTTP header
    3. `user` query parameter (on GET)
    4. Private reads require a verified Django session or a configured, valid API key.
       `X-Perspective-User` only selects a scope for a trusted API client; it does not
       authenticate a user by itself.
    5. Otherwise creates/retrieves an isolated `anonymous-local` user record (never crashing).
    """
    auth_error = check_api_key_if_required(request)
    if auth_error is not None:
        return None, auth_error

    username: str | None = None
    django_user = getattr(request, "user", None)
    session_authenticated = bool(
        django_user is not None and getattr(django_user, "is_authenticated", False)
    )
    if (
        require_explicit_identity
        and not session_authenticated
        and not getattr(settings, "PERSPECTIVE_LOOM_API_KEY", "")
    ):
        return (
            None,
            JsonResponse(
                {
                    "error": "Private records require an authenticated session or configured API key."
                },
                status=401,
            ),
        )

    if session_authenticated:
        username = getattr(django_user, "username", None)

    if not username:
        header_user = request.headers.get("X-Perspective-User", "").strip()
        if header_user:
            username = header_user

    if not username and request.method == "GET":
        query_user = request.GET.get("user", "").strip()
        if query_user:
            username = query_user

    if not username:
        if require_explicit_identity:
            return (
                None,
                JsonResponse(
                    {
                        "error": (
                            "Authentication or explicit user scope ('X-Perspective-User' header) "
                            "is required to access private history."
                        )
                    },
                    status=401,
                ),
            )
        username = "anonymous-local"

    if not USERNAME_PATTERN.match(username):
        return (
            None,
            JsonResponse(
                {"error": "Invalid username format in request identity."},
                status=400,
            ),
        )

    user_obj, _ = User.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@local.perspective-loom.internal"},
    )
    return user_obj, None


def require_valid_auth(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator enforcing API key / session check before executing a view."""

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        err = check_api_key_if_required(request)
        if err is not None:
            return err
        return view_func(request, *args, **kwargs)

    return _wrapped


def csrf_protect_session(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """Require a CSRF token for session writes while allowing header-key API clients."""
    protected_view = csrf_protect(view_func)

    @csrf_exempt
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        django_user = getattr(request, "user", None)
        if django_user is not None and getattr(django_user, "is_authenticated", False):
            return protected_view(request, *args, **kwargs)
        return view_func(request, *args, **kwargs)

    return _wrapped
