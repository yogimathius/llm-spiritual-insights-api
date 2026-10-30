from django.db import models


class LLMRole(models.Model):
    """
    Configurable perspective / role model.
    Retains backward compatibility with legacy fields (`name`, `description`,
    `prompt_template`, `model_name`, `max_tokens`, `temperature`, `collaborators`,
    `collaboration_triggers`) while adding versioned methodology and epistemic boundary metadata.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, blank=True, default="")
    version = models.CharField(max_length=32, default="1.0.0")
    domain = models.CharField(max_length=64, default="research_philosophy")
    purpose = models.TextField(blank=True, default="")
    description = models.TextField()
    prompt_template = models.TextField()
    interpretive_methodology = models.TextField(blank=True, default="")
    boundaries_and_limitations = models.TextField(blank=True, default="")
    epistemic_type = models.CharField(max_length=64, default="philosophical_inquiry")
    evidence_requirements = models.TextField(blank=True, default="")
    permitted_tools = models.JSONField(default=list, blank=True)
    is_historical_persona = models.BooleanField(default=False)
    model_name = models.CharField(max_length=100, default="gpt-4o-mini")
    max_tokens = models.IntegerField(default=350)
    temperature = models.FloatField(default=0.7)
    collaborators = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="can_collaborate_with",
    )
    collaboration_triggers = models.TextField(
        blank=True,
        help_text="Keywords or patterns that suggest collaboration with this role",
    )

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"
