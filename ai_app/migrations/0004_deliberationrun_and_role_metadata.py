# Generated migration for Perspective Loom Phase 1 & Phase 2 models

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_app", "0003_llmrole_collaboration_triggers_llmrole_collaborators"),
    ]

    operations = [
        migrations.AddField(
            model_name="llmrole",
            name="boundaries_and_limitations",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="domain",
            field=models.CharField(default="research_philosophy", max_length=64),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="epistemic_type",
            field=models.CharField(default="philosophical_inquiry", max_length=64),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="evidence_requirements",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="interpretive_methodology",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="is_historical_persona",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="permitted_tools",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="purpose",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="slug",
            field=models.SlugField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="version",
            field=models.CharField(default="1.0.0", max_length=32),
        ),
        migrations.AlterField(
            model_name="llmrole",
            name="max_tokens",
            field=models.IntegerField(default=350),
        ),
        migrations.AlterField(
            model_name="llmrole",
            name="model_name",
            field=models.CharField(default="gpt-4o-mini", max_length=100),
        ),
        migrations.AlterField(
            model_name="llmrole",
            name="name",
            field=models.CharField(max_length=100, unique=True),
        ),
        migrations.CreateModel(
            name="DeliberationRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("run_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("trace_id", models.CharField(db_index=True, max_length=64)),
                ("question", models.TextField()),
                ("strategy", models.CharField(max_length=64)),
                (
                    "domain",
                    models.CharField(default="research_philosophy", max_length=64),
                ),
                ("status", models.CharField(default="completed", max_length=32)),
                ("provider", models.CharField(default="fake", max_length=64)),
                (
                    "model_name",
                    models.CharField(default="fake-deterministic-v1", max_length=100),
                ),
                ("perspectives_used", models.JSONField(default=list)),
                ("evidence_supplied", models.JSONField(default=list)),
                ("independent_analyses", models.JSONField(default=list)),
                ("critiques", models.JSONField(default=list)),
                ("synthesis", models.JSONField(default=dict)),
                ("trace", models.JSONField(default=dict)),
                ("evaluation", models.JSONField(blank=True, default=dict)),
                ("total_latency_ms", models.FloatField(default=0.0)),
                ("total_tokens", models.IntegerField(default=0)),
                ("estimated_cost_usd", models.FloatField(default=0.0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliberation_runs",
                        to="ai_app.user",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
