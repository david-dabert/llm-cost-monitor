"""Export cost data to CSV, JSON, and PDF invoice format."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def export_csv(records: list[dict], output_path: Path) -> None:
    """Export usage records to a CSV file."""
    if not records:
        output_path.write_text("No data
")
        return

    fieldnames = [
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def export_json(records: list[dict], output_path: Path) -> None:
    """Export usage records to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

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

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, default=str)


def export_pdf(
    records: list[dict],
    output_path: Path,
    project: Optional[str] = None,
) -> None:
    """Export usage records to a PDF invoice-style document."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate,
            Table,
            TableStyle,
            Paragraph,
            Spacer,
        )
    except ImportError:
        raise ImportError(
            "reportlab is required for PDF export. Install it with: pip install reportlab"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    title = f"LLM Cost Report"
    if project:
        title += f" - {project}"
    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Spacer(1, 5 * mm))

    total_cost = sum(r.get("cost_usd", 0) for r in records)
    total_input = sum(r.get("input_tokens", 0) for r in records)
    total_output = sum(r.get("output_tokens", 0) for r in records)

    summary_text = (
        f"Generated: {datetime.utcnow().strftime(chr(37)+"Y-"+chr(37)+"m-"+chr(37)+"d "+chr(37)+"H:"+chr(37)+"M UTC")}<br/>"
        f"Total Requests: {len(records):,}<br/>"
        f"Total Cost: \${total_cost:.4f}<br/>"
        f"Total Input Tokens: {total_input:,}<br/>"
        f"Total Output Tokens: {total_output:,}"
    )
    elements.append(Paragraph(summary_text, styles["Normal"]))
    elements.append(Spacer(1, 10 * mm))

    model_costs: dict[str, dict] = {}
    for r in records:
        model = r.get("model", "unknown")
        if model not in model_costs:
            model_costs[model] = {"requests": 0, "cost": 0.0, "tokens": 0}
        model_costs[model]["requests"] += 1
        model_costs[model]["cost"] += r.get("cost_usd", 0)
        model_costs[model]["tokens"] += r.get("total_tokens", 0)

    table_data = [["Model", "Requests", "Tokens", "Cost (USD)"]]
    for model, stats in sorted(model_costs.items(), key=lambda x: -x[1]["cost"]):
        table_data.append([
            model,
            str(stats["requests"]),
            f"{stats[chr(39)+'tokens'+chr(39) if False else 'tokens']:,}",
            f"\${stats['cost']:.4f}",
        ])
    table_data.append(["TOTAL", str(len(records)), "", f"\${total_cost:.4f}"])

    table = Table(table_data, colWidths=[150, 70, 80, 80])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f0f4ff")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    elements.append(table)

    doc.build(elements)
