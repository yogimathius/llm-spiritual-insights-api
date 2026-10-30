from django.core.management.base import BaseCommand

from ai_app.engine.perspectives import DEFAULT_PERSPECTIVE_SPECS
from ai_app.models.llm_role import LLMRole


class Command(BaseCommand):
    help = "Initialize or update versioned Perspective Loom roles (historical & technical)"

    def handle(self, *args, **kwargs):
        created_roles = {}
        for spec in DEFAULT_PERSPECTIVE_SPECS:
            role, _ = LLMRole.objects.update_or_create(
                name=spec.name,
                defaults={
                    "slug": spec.slug,
                    "version": spec.version,
                    "domain": spec.domain,
                    "purpose": spec.purpose,
                    "description": spec.purpose,
                    "prompt_template": spec.system_instructions,
                    "interpretive_methodology": spec.interpretive_methodology,
                    "boundaries_and_limitations": spec.boundaries_and_limitations,
                    "epistemic_type": spec.epistemic_type,
                    "evidence_requirements": spec.evidence_requirements,
                    "permitted_tools": spec.permitted_tools,
                    "is_historical_persona": spec.is_historical_persona,
                    "model_name": spec.preferred_model,
                    "max_tokens": spec.max_tokens,
                    "temperature": spec.temperature,
                    "collaboration_triggers": ", ".join(spec.collaboration_triggers),
                },
            )
            created_roles[spec.name] = {
                "instance": role,
                "collaborators": spec.recommended_collaborators,
            }
            self.stdout.write(
                self.style.SUCCESS(f"Synchronized perspective: {role.name} (v{role.version})")
            )

        for role_data in created_roles.values():
            role = role_data["instance"]
            role.collaborators.clear()
            for collaborator_name in role_data["collaborators"]:
                if collaborator_name in created_roles:
                    collaborator = created_roles[collaborator_name]["instance"]
                    role.collaborators.add(collaborator)

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully synchronized {len(created_roles)} perspectives with collaborations."
            )
        )
