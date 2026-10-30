import logging
from typing import Any

from django.forms.models import model_to_dict

logger = logging.getLogger("ai_app")


class ResponseFormatter:
    @staticmethod
    def format_roles(roles: Any) -> list[dict[str, Any]]:
        formatted = []
        for role in roles:
            formatted.append(
                {
                    "name": role.name,
                    "slug": getattr(role, "slug", "") or role.name.lower().replace(" ", "-"),
                    "version": getattr(role, "version", "1.0.0"),
                    "domain": getattr(role, "domain", "research_philosophy"),
                    "purpose": getattr(role, "purpose", "") or role.description,
                    "description": role.description,
                    "interpretive_methodology": getattr(role, "interpretive_methodology", ""),
                    "boundaries_and_limitations": getattr(role, "boundaries_and_limitations", ""),
                    "epistemic_type": getattr(role, "epistemic_type", "philosophical_inquiry"),
                    "is_historical_persona": getattr(role, "is_historical_persona", False),
                }
            )
        return formatted

    @staticmethod
    def format_history(history_items: Any) -> list[dict[str, Any]]:
        history_list = list(history_items)
        history_data = [
            model_to_dict(item, fields=["id", "prompt", "response"])
            for item in history_list
        ]

        for i, item in enumerate(history_list):
            history_data[i]["role"] = item.role.name if item.role else None
            history_data[i]["user"] = item.user.username if item.user else None
            history_data[i]["created_at"] = item.created_at.isoformat()

        return history_data
