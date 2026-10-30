"""
Persistence models for Deliberation Runs and Evaluation Records.
"""

from django.db import models

from ai_app.models.user import User


class DeliberationRun(models.Model):
    """Persists a complete deliberation execution, its structured outputs, and telemetry trace."""

    run_id = models.CharField(max_length=64, unique=True, db_index=True)
    trace_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="deliberation_runs",
    )
    question = models.TextField()
    strategy = models.CharField(max_length=64)
    domain = models.CharField(max_length=64, default="research_philosophy")
    status = models.CharField(max_length=32, default="completed")
    provider = models.CharField(max_length=64, default="fake")
    model_name = models.CharField(max_length=100, default="fake-deterministic-v1")
    perspectives_used = models.JSONField(default=list)
    evidence_supplied = models.JSONField(default=list)
    independent_analyses = models.JSONField(default=list)
    critiques = models.JSONField(default=list)
    synthesis = models.JSONField(default=dict)
    trace = models.JSONField(default=dict)
    evaluation = models.JSONField(default=dict, blank=True)
    total_latency_ms = models.FloatField(default=0.0)
    total_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.run_id} ({self.strategy} - {self.status})"
