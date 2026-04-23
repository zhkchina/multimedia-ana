from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def service_metrics(summary: dict[str, Any], service_name: str) -> dict[str, Any]:
    service = summary["services"].get(service_name, {})
    return service.get("summary", {})


def build_report(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    services = sorted(set(before.get("services", {}).keys()) | set(after.get("services", {}).keys()))
    comparison: dict[str, Any] = {
        "before_generated_at": before.get("generated_at"),
        "after_generated_at": after.get("generated_at"),
        "services": {},
    }
    for service_name in services:
        before_metrics = service_metrics(before, service_name)
        after_metrics = service_metrics(after, service_name)
        before_avg = before_metrics.get("avg_elapsed_seconds")
        after_avg = after_metrics.get("avg_elapsed_seconds")
        comparison["services"][service_name] = {
            "before": before_metrics,
            "after": after_metrics,
            "delta_avg_elapsed_seconds": (
                round(after_avg - before_avg, 3)
                if isinstance(before_avg, (int, float)) and isinstance(after_avg, (int, float))
                else None
            ),
        }
    return comparison


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Multimedia QA Comparison",
        "",
        f"- before: `{report.get('before_generated_at')}`",
        f"- after: `{report.get('after_generated_at')}`",
        "",
        "| service | before avg(s) | after avg(s) | delta avg(s) | before success | after success |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for service_name, item in report.get("services", {}).items():
        before = item.get("before", {})
        after = item.get("after", {})
        lines.append(
            "| {service} | {before_avg} | {after_avg} | {delta} | {before_ok}/{before_total} | {after_ok}/{after_total} |".format(
                service=service_name,
                before_avg=before.get("avg_elapsed_seconds"),
                after_avg=after.get("avg_elapsed_seconds"),
                delta=item.get("delta_avg_elapsed_seconds"),
                before_ok=before.get("success_count"),
                before_total=before.get("run_count"),
                after_ok=after.get("success_count"),
                after_total=after.get("run_count"),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two multimedia QA summary.json files.")
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    before = load_summary(Path(args.before))
    after = load_summary(Path(args.after))
    report = build_report(before, after)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = to_markdown(report)
    if args.output_md:
        Path(args.output_md).write_text(markdown, encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
