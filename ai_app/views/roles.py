from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from ai_app.engine.perspectives import DEFAULT_REGISTRY
from ai_app.models.llm_role import LLMRole
from ai_app.services.response_formatter import ResponseFormatter


@require_GET
def list_roles(request: HttpRequest) -> JsonResponse:
    roles = LLMRole.objects.all()
    if roles.exists():
        roles_data = ResponseFormatter.format_roles(roles)
    else:
        # Fallback to in-memory registry if DB roles haven't been initialized yet
        roles_data = [
            {
                "name": spec.name,
                "slug": spec.slug,
                "version": spec.version,
                "domain": spec.domain,
                "purpose": spec.purpose,
                "description": spec.purpose,
                "interpretive_methodology": spec.interpretive_methodology,
                "boundaries_and_limitations": spec.boundaries_and_limitations,
                "epistemic_type": spec.epistemic_type,
                "is_historical_persona": spec.is_historical_persona,
            }
            for spec in DEFAULT_REGISTRY.list_all()
        ]
    return JsonResponse({"roles": roles_data})
