"""Export cost data to CSV, JSON, and Markdown report format.

All export functions return strings for flexibility (write to file or stdout).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Optional


FIELDNAMES = [
    "timestamp",
    "model",
    "provider",
    "project",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "total_tokens",
    "cost_usd",
    "latency_ms",
    "task",
]


def export_csv(records: list[dict]) -> str:
    """Export usage records to CSV format. Returns a string."""
    if not records:
        return "No data\n"

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow(record)
    return output.getvalue()


def export_json(records: list[dict]) -> str:
    """Export usage records to JSON format. Returns a string."""
    total_cost = sum(r.get("cost_usd", 0) for r in records)
    total_input = sum(r.get("input_tokens", 0) for r in records)
    total_output = sum(r.get("output_tokens", 0) for r in records)

    export_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "record_count": len(records),
        "summary": {
            "total_cost_usd": round(total_cost, 6),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_requests": len(records),
        },
        "records": records,
    }

    return json.dumps(export_data, indent=2, default=str)


def export_markdown(
    records: list[dict],
    summary: Optional[dict] = None,
) -> str:
    """Export usage records to a Markdown report. Returns a string."""
    lines = []
    lines.append("# LLM Cost Monitor Report")
    lines.append("")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Summary section
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total Requests | {summary.get('total_requests', 0):,} |")
        lines.append(f"| Total Cost | ${summary.get('total_cost_usd', 0):.4f} |")
        lines.append(f"| Today | ${summary.get('daily_cost', 0):.4f} |")
        lines.append(f"| This Week | ${summary.get('weekly_cost', 0):.4f} |")
        lines.append(f"| This Month | ${summary.get('monthly_cost', 0):.4f} |")
        lines.append(f"| Avg Latency | {summary.get('avg_latency_ms', 0):.0f}ms |")
        lines.append("")

    # Cost by model
    model_costs: dict[str, dict] = {}
    for r in records:
        model = r.get("model", "unknown")
        if model not in model_costs:
            model_costs[model] = {
                "requests": 0,
                "cost": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        model_costs[model]["requests"] += 1
        model_costs[model]["cost"] += r.get("cost_usd", 0)
        model_costs[model]["input_tokens"] += r.get("input_tokens", 0)
        model_costs[model]["output_tokens"] += r.get("output_tokens", 0)

    if model_costs:
        lines.append("## Cost by Model")
        lines.append("")
        lines.append("| Model | Requests | Input Tokens | Output Tokens | Cost |")
        lines.append("|-------|----------|-------------|--------------|------|")

        for model, stats in sorted(
            model_costs.items(), key=lambda x: -x[1]["cost"]
        ):
            lines.append(
                f"| {model} "
                f"| {stats['requests']:,} "
                f"| {stats['input_tokens']:,} "
                f"| {stats['output_tokens']:,} "
                f"| ${stats['cost']:.4f} |"
            )
        lines.append("")

    # Recent requests table (last 20)
    if records:
        lines.append("## Recent Requests")
        lines.append("")
        lines.append("| Timestamp | Model | Tokens | Cost | Project |")
        lines.append("|-----------|-------|--------|------|---------|")

        for r in records[:20]:
            ts = r.get("timestamp", "")[:19]
            total_tokens = r.get("input_tokens", 0) + r.get("output_tokens", 0)
            lines.append(
                f"| {ts} "
                f"| {r.get('model', '?')} "
                f"| {total_tokens:,} "
                f"| ${r.get('cost_usd', 0):.6f} "
                f"| {r.get('project', '')} |"
            )
        lines.append("")

    return "\n".join(lines)
