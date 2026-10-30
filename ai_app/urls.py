from django.urls import path

from .views.deliberation import (
    compare_strategies_view,
    evaluate_run_view,
    get_run_detail,
    list_runs,
    perspectives_view,
    start_deliberation,
    stream_deliberation,
)
from .views.dialogue import ask_role, full_dialogue, stream_dialogue
from .views.history import get_conversation_history
from .views.roles import list_roles

urlpatterns = [
    # Legacy prototype endpoints (preserved & hardened)
    path("roles/", list_roles, name="list_roles"),
    path("ask-role/", ask_role, name="ask_role"),
    path("history/", get_conversation_history, name="get_history"),
    path("full-dialogue/", full_dialogue, name="full_dialogue"),
    path("stream-dialogue/", stream_dialogue, name="stream_dialogue"),
    # Modernized Deliberation & Evaluation Platform endpoints
    path("perspectives/", perspectives_view, name="perspectives"),
    path("deliberate/", start_deliberation, name="start_deliberation"),
    path("deliberate/stream/", stream_deliberation, name="stream_deliberation"),
    path("runs/", list_runs, name="list_runs"),
    path("runs/<str:run_id>/", get_run_detail, name="get_run_detail"),
    path("evaluate/", evaluate_run_view, name="evaluate_run"),
    path("compare/", compare_strategies_view, name="compare_strategies"),
]
