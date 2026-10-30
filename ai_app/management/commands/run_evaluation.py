from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from ai_app.evaluation.runner import ExperimentRunner


class Command(BaseCommand):
    help = "Run the Perspective Loom evaluation laboratory comparing Strategies A, B, and C"

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            type=str,
            default="fake",
            help="Model provider to use (fake, github_models, openai, ollama)",
        )
        parser.add_argument(
            "--model",
            type=str,
            default=None,
            help="Optional model name override",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="",
            help="Optional file path to write JSON evaluation report",
        )

    def handle(self, *args, **options):
        provider_name = options["provider"]
        model_name = options["model"]
        output_path = options["output"]

        runner = ExperimentRunner(provider_name=provider_name, model_name=model_name)
        report = runner.run_benchmark_suite()

        self.stdout.write(self.style.SUCCESS("=== Perspective Loom Evaluation Benchmark ==="))
        self.stdout.write(f"Provider: {report['provider']} | Model: {report['model']}")
        for strat, metrics in report["aggregate_by_strategy"].items():
            self.stdout.write(
                f"  - {strat:26s}: quality={metrics['mean_overall_quality_score']:.2f}/5.0 | "
                f"disagreement={metrics['mean_disagreement_preservation_score']:.2f}/5.0 | "
                f"mean_tokens={metrics['mean_tokens']:6.1f} | "
                f"quality/1k_tok={metrics['mean_quality_per_1k_tokens']:.2f} | "
                f"cost=${metrics['total_estimated_cost_usd']:.6f}"
            )
        self.stdout.write("\nConclusion:")
        self.stdout.write(f"  {report['overall_conclusion']}\n")

        if output_path:
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Saved evaluation report to {out_file}"))
