"""CLI interface for llm-cost-monitor.

Commands:
    llm-cost start       Start the proxy server
    llm-cost dashboard   Open the live terminal dashboard
    llm-cost report      Print a cost report
    llm-cost budget set  Set project budgets
    llm-cost budget show Show project budget status
    llm-cost export      Export data to CSV, JSON, or PDF
    llm-cost models      List supported models and pricing
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import click

DEFAULT_DB = "~/.llm-cost-monitor/costs.db"


def _get_tracker(db_path: str) -> "CostTracker":
    """Create a CostTracker instance."""
    from llm_cost_monitor.tracker import CostTracker

    resolved = str(Path(db_path).expanduser())
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    return CostTracker(resolved)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """LLM Cost Monitor - Track and control your LLM API spending."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@main.command()
@click.option("--host", default="127.0.0.1", help="Proxy host.")
@click.option("--port", "-p", default=8080, type=int, help="Proxy port.")
@click.option("--db", default=DEFAULT_DB, help="Database path.")
@click.option("--project", default="default", help="Default project name.")
def start(host: str, port: int, db: str, project: str) -> None:
    """Start the LLM cost monitoring proxy."""
    from llm_cost_monitor.proxy import start_proxy

    click.echo(f"Starting LLM Cost Monitor proxy on {host}:{port}")
    click.echo(f"Database: {db}")
    click.echo(f"Default project: {project}")
    click.echo("Press Ctrl+C to stop.")
    start_proxy(host=host, port=port, db_path=db, project=project)


@main.command()
@click.option("--db", default=DEFAULT_DB, help="Database path.")
@click.option("--project", default=None, help="Filter by project.")
@click.option("--refresh", default=2.0, type=float, help="Refresh interval in seconds.")
def dashboard(db: str, project: Optional[str], refresh: float) -> None:
    """Open the live terminal dashboard."""
    from llm_cost_monitor.dashboard import render_dashboard

    tracker = _get_tracker(db)
    try:
        render_dashboard(tracker, project=project, refresh_seconds=refresh)
    finally:
        tracker.close()


@main.command()
@click.option("--db", default=DEFAULT_DB, help="Database path.")
@click.option("--project", default=None, help="Filter by project.")
@click.option(
    "--period",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default="monthly",
    help="Report period.",
)
def report(db: str, project: Optional[str], period: str) -> None:
    """Print a cost report."""
    from llm_cost_monitor.dashboard import print_report

    tracker = _get_tracker(db)
    try:
        print_report(tracker, project=project, period=period)
    finally:
        tracker.close()


@main.group()
def budget() -> None:
    """Manage project budgets."""
    pass


@budget.command("set")
@click.option("--db", default=DEFAULT_DB, help="Database path.")
@click.option("--project", required=True, help="Project name.")
@click.option("--daily", type=float, default=None, help="Daily budget in USD.")
@click.option("--weekly", type=float, default=None, help="Weekly budget in USD.")
@click.option("--monthly", type=float, default=None, help="Monthly budget in USD.")
def budget_set(
    db: str,
    project: str,
    daily: Optional[float],
    weekly: Optional[float],
    monthly: Optional[float],
) -> None:
    """Set budget limits for a project."""
    from llm_cost_monitor.tracker import Budget

    if daily is None and weekly is None and monthly is None:
        click.echo("Error: At least one of --daily, --weekly, or --monthly is required.")
        return

    tracker = _get_tracker(db)
    try:
        b = Budget(project=project, daily_limit=daily, weekly_limit=weekly, monthly_limit=monthly)
        tracker.set_budget(b)
        click.echo(f"Budget set for project '{project}':")
        if daily is not None:
            click.echo(f"  Daily:   ${daily:.2f}")
        if weekly is not None:
            click.echo(f"  Weekly:  ${weekly:.2f}")
        if monthly is not None:
            click.echo(f"  Monthly: ${monthly:.2f}")
    finally:
        tracker.close()


@budget.command("show")
@click.option("--db", default=DEFAULT_DB, help="Database path.")
@click.option("--project", required=True, help="Project name.")
def budget_show(db: str, project: str) -> None:
    """Show budget status for a project."""
    tracker = _get_tracker(db)
    try:
        b = tracker.get_budget(project)
        if b is None:
            click.echo(f"No budget set for project '{project}'.")
            return
        daily = tracker.get_daily_cost(project)
        weekly = tracker.get_weekly_cost(project)
        monthly = tracker.get_monthly_cost(project)

        click.echo(f"Budget for '{project}':")
        if b.daily_limit:
            pct = (daily / b.daily_limit) * 100 if b.daily_limit else 0
            click.echo(f"  Daily:   ${daily:.4f} / ${b.daily_limit:.2f} ({pct:.0f}%)")
        if b.weekly_limit:
            pct = (weekly / b.weekly_limit) * 100 if b.weekly_limit else 0
            click.echo(f"  Weekly:  ${weekly:.4f} / ${b.weekly_limit:.2f} ({pct:.0f}%)")
        if b.monthly_limit:
            pct = (monthly / b.monthly_limit) * 100 if b.monthly_limit else 0
            click.echo(f"  Monthly: ${monthly:.4f} / ${b.monthly_limit:.2f} ({pct:.0f}%)")

        violations, warnings = tracker.check_budget(project)
        for w in warnings:
            click.echo(f"  [WARNING] {w}")
        for v in violations:
            click.echo(f"  [EXCEEDED] {v}")
    finally:
        tracker.close()


@main.command("export")
@click.option("--db", default=DEFAULT_DB, help="Database path.")
@click.option("--project", default=None, help="Filter by project.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["csv", "json", "pdf"]),
    default="csv",
    help="Export format.",
)
@click.option("--output", "-o", required=True, help="Output file path.")
@click.option("--days", default=30, type=int, help="Number of days to export.")
def export_data(
    db: str,
    project: Optional[str],
    fmt: str,
    output: str,
    days: int,
) -> None:
    """Export cost data to CSV, JSON, or PDF."""
    from llm_cost_monitor.exporters import export_csv, export_json, export_pdf

    tracker = _get_tracker(db)
    try:
        records = tracker.get_recent_records(limit=10_000, project=project)
        output_path = Path(output)

        if fmt == "csv":
            export_csv(records, output_path)
        elif fmt == "json":
            export_json(records, output_path)
        elif fmt == "pdf":
            export_pdf(records, output_path, project=project)

        click.echo(f"Exported {len(records)} records to {output_path}")
    finally:
        tracker.close()


@main.command()
def models() -> None:
    """List supported models and their pricing."""
    from llm_cost_monitor.pricing import PricingDatabase

    db = PricingDatabase()
    for provider in db.list_providers():
        click.echo(f"\n{provider.upper()}")
        click.echo("-" * 60)
        for m in db.models_by_provider(provider):
            cached = f" (cached: ${m.cached_input_per_m:.4f}/M)" if m.cached_input_per_m else ""
            click.echo(
                f"  {m.model_id:<25} "
                f"in: ${m.input_per_m:>8.4f}/M  "
                f"out: ${m.output_per_m:>8.4f}/M"
                f"{cached}"
            )
    click.echo()


if __name__ == "__main__":
    main()
