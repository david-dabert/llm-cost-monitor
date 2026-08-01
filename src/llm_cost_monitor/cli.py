"""CLI interface for llm-cost-monitor.

Commands:
    llm-cost start       Start the proxy server
    llm-cost dashboard   Launch the web dashboard
    llm-cost report      Print a cost report
    llm-cost budget      Manage budgets (set, list)
    llm-cost alert       Manage alerts (add, list)
    llm-cost optimize    Run the optimization engine
    llm-cost export      Export data to CSV, JSON, or Markdown
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from llm_cost_monitor import __version__

DEFAULT_DB = "costs.db"
console = Console()


def _get_tracker(db_path: str):
    """Create a CostTracker instance."""
    from llm_cost_monitor.tracker import CostTracker
    resolved = str(Path(db_path).expanduser())
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    return CostTracker(resolved)


@click.group()
@click.option("--db", default=DEFAULT_DB, envvar="LLM_COST_DB",
              help="Path to SQLite database.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.version_option(version=__version__)
@click.pass_context
def main(ctx, db, verbose):
    """LLM Cost Monitor - Track and control your LLM API spending."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@main.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", "-p", default=8080, type=int, help="Proxy port.")
@click.option("--log-level", default="INFO", help="Logging level.")
@click.pass_context
def start(ctx, host, port, log_level):
    """Start the transparent proxy server."""
    from llm_cost_monitor.proxy import start_proxy

    db_path = ctx.obj["db_path"]
    console.print(f"[bold blue]Starting LLM Cost Monitor proxy on {host}:{port}[/]")
    console.print(f"[dim]Database: {db_path}[/]")
    console.print(f"[dim]Route requests to http://{host}:{port}/<provider>/v1/...[/]")
    console.print("[dim]Press Ctrl+C to stop.[/]")
    start_proxy(host=host, port=port, db_path=db_path, log_level=log_level)


@main.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", "-p", default=5050, type=int, help="Dashboard port.")
@click.pass_context
def dashboard(ctx, host, port):
    """Launch the web dashboard."""
    from llm_cost_monitor.dashboard import start_dashboard

    db_path = ctx.obj["db_path"]
    console.print(f"[bold blue]Starting dashboard on http://{host}:{port}[/]")
    start_dashboard(db_path=db_path, host=host, port=port)


@main.command()
@click.option("--days", default=7, type=int, help="Number of days to include.")
@click.option("--project", default=None, help="Filter by project name.")
@click.option("--model", default=None, help="Filter by model name.")
@click.pass_context
def report(ctx, days, project, model):
    """Print a cost summary report to the terminal."""
    db_path = ctx.obj["db_path"]
    tracker = _get_tracker(db_path)

    summary = tracker.get_summary(project)
    console.print()
    console.print("[bold blue]LLM Cost Monitor Report[/]")
    console.print(f"[dim]Period: last {days} days[/]")
    if project:
        console.print(f"[dim]Project: {project}[/]")
    console.print()

    summary_table = Table(title="Cost Summary", show_header=False)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", justify="right")
    summary_table.add_row("Total Requests", f"{summary['total_requests']:,}")
    summary_table.add_row("Total Cost", f"${summary['total_cost_usd']:.4f}")
    summary_table.add_row("Today", f"${summary['daily_cost']:.4f}")
    summary_table.add_row("This Week", f"${summary['weekly_cost']:.4f}")
    summary_table.add_row("This Month", f"${summary['monthly_cost']:.4f}")
    summary_table.add_row("Avg Latency", f"{summary['avg_latency_ms']:.0f}ms")
    console.print(summary_table)
    console.print()

    start = datetime.utcnow() - timedelta(days=days)
    models = tracker.get_cost_by_model(start=start, project=project)
    if model:
        models = [m for m in models if model.lower() in m["model"].lower()]

    model_table = Table(title="Cost by Model")
    model_table.add_column("Model", style="cyan")
    model_table.add_column("Provider", style="dim")
    model_table.add_column("Requests", justify="right")
    model_table.add_column("Input Tokens", justify="right")
    model_table.add_column("Output Tokens", justify="right")
    model_table.add_column("Cost", justify="right", style="green")

    for m in models:
        model_table.add_row(
            m["model"], m["provider"],
            f"{m['request_count']:,}",
            f"{m['total_input_tokens']:,}",
            f"{m['total_output_tokens']:,}",
            f"${m['total_cost']:.4f}",
        )
    console.print(model_table)
    tracker.close()


@main.group()
@click.pass_context
def budget(ctx):
    """Manage budgets (set, list)."""
    pass


@budget.command("set")
@click.option("--project", required=True, help="Project name.")
@click.option("--daily", type=float, default=None, help="Daily budget in USD.")
@click.option("--weekly", type=float, default=None, help="Weekly budget in USD.")
@click.option("--monthly", type=float, default=None, help="Monthly budget in USD.")
@click.pass_context
def budget_set(ctx, project, daily, weekly, monthly):
    """Set budget limits for a project."""
    from llm_cost_monitor.tracker import Budget

    if daily is None and weekly is None and monthly is None:
        console.print("[red]At least one of --daily, --weekly, or --monthly is required.[/]")
        return

    db_path = ctx.obj["db_path"]
    tracker = _get_tracker(db_path)
    b = Budget(project=project, daily_limit=daily, weekly_limit=weekly, monthly_limit=monthly)
    tracker.set_budget(b)
    console.print(f"[green]Budget set for project '{project}':[/]")
    if daily is not None:
        console.print(f"  Daily:   ${daily:.2f}")
    if weekly is not None:
        console.print(f"  Weekly:  ${weekly:.2f}")
    if monthly is not None:
        console.print(f"  Monthly: ${monthly:.2f}")
    tracker.close()


@budget.command("list")
@click.pass_context
def budget_list(ctx):
    """List all configured budgets with current spend."""
    db_path = ctx.obj["db_path"]
    tracker = _get_tracker(db_path)
    budgets = tracker.list_budgets()

    if not budgets:
        console.print("[dim]No budgets configured.[/]")
        tracker.close()
        return

    table = Table(title="Budgets")
    table.add_column("Project", style="cyan")
    table.add_column("Daily Limit", justify="right")
    table.add_column("Weekly Limit", justify="right")
    table.add_column("Monthly Limit", justify="right")
    table.add_column("Today", justify="right", style="green")
    table.add_column("This Week", justify="right")
    table.add_column("This Month", justify="right")

    for b in budgets:
        daily = tracker.get_daily_cost(b.project)
        weekly = tracker.get_weekly_cost(b.project)
        monthly = tracker.get_monthly_cost(b.project)

        d_limit = f"${b.daily_limit:.2f}" if b.daily_limit else "-"
        w_limit = f"${b.weekly_limit:.2f}" if b.weekly_limit else "-"
        m_limit = f"${b.monthly_limit:.2f}" if b.monthly_limit else "-"

        table.add_row(
            b.project,
            d_limit, w_limit, m_limit,
            f"${daily:.4f}", f"${weekly:.4f}", f"${monthly:.4f}",
        )

        violations, warnings = tracker.check_budget(b.project)
        for w in warnings:
            console.print(f"  [yellow]{w}[/]")
        for v in violations:
            console.print(f"  [red]{v}[/]")

    console.print(table)
    tracker.close()


@main.group()
@click.pass_context
def alert(ctx):
    """Manage alerts (add, list)."""
    pass


@alert.command("add")
@click.option("--type", "alert_type", required=True,
              type=click.Choice(["slack", "discord", "email"]),
              help="Alert channel type.")
@click.option("--webhook-url", default=None, help="Webhook URL (slack/discord).")
@click.option("--email", "email_addr", default=None, help="Email address.")
@click.option("--smtp-host", default="smtp.gmail.com", help="SMTP host.")
@click.option("--smtp-port", default=587, type=int, help="SMTP port.")
@click.pass_context
def alert_add(ctx, alert_type, webhook_url, email_addr, smtp_host, smtp_port):
    """Add an alert channel."""
    db_path = ctx.obj["db_path"]
    tracker = _get_tracker(db_path)
    conn = tracker._get_conn()

    if alert_type in ("slack", "discord"):
        if not webhook_url:
            console.print("[red]--webhook-url required for slack/discord alerts[/]")
            return
        config = {"webhook_url": webhook_url}
    elif alert_type == "email":
        if not email_addr:
            console.print("[red]--email required for email alerts[/]")
            return
        config = {"to": email_addr, "smtp_host": smtp_host, "smtp_port": smtp_port}
    else:
        return

    conn.execute(
        "INSERT INTO alerts (channel, config) VALUES (?, ?)",
        (alert_type, json.dumps(config)),
    )
    conn.commit()
    console.print(f"[green]Alert channel '{alert_type}' added.[/]")
    tracker.close()


@alert.command("list")
@click.pass_context
def alert_list(ctx):
    """List all configured alert channels."""
    db_path = ctx.obj["db_path"]
    tracker = _get_tracker(db_path)
    conn = tracker._get_conn()
    rows = conn.execute("SELECT * FROM alerts ORDER BY id").fetchall()

    if not rows:
        console.print("[dim]No alert channels configured.[/]")
        tracker.close()
        return

    table = Table(title="Alert Channels")
    table.add_column("ID", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Configuration")

    for row in rows:
        config = json.loads(row["config"])
        display = {}
        for k, v in config.items():
            if "url" in k.lower() and isinstance(v, str) and len(v) > 20:
                display[k] = v[:20] + "..."
            else:
                display[k] = v
        table.add_row(str(row["id"]), row["channel"], str(display))

    console.print(table)
    tracker.close()


@main.command()
@click.option("--days", default=30, type=int, help="Number of days to analyze.")
@click.pass_context
def optimize(ctx, days):
    """Run the optimization engine and print recommendations."""
    from llm_cost_monitor.pricing import PricingDatabase
    from llm_cost_monitor.optimizer import CostOptimizer

    db_path = ctx.obj["db_path"]
    tracker = _get_tracker(db_path)
    pricing = PricingDatabase()
    optimizer = CostOptimizer(tracker, pricing)
    recommendations = optimizer.run_all(days=days)

    if not recommendations:
        console.print("[dim]No optimization recommendations at this time.[/]")
        console.print("[dim]Insufficient usage data for analysis.[/]")
        tracker.close()
        return

    console.print()
    console.print("[bold blue]Optimization Recommendations[/]")
    console.print(f"[dim]Based on {days} days of usage data[/]")
    console.print()

    for i, rec in enumerate(recommendations, 1):
        savings = rec["estimated_savings"]
        style = "green" if savings > 1 else "yellow"
        console.print(f"[bold]{i}. {rec['strategy']}[/]")
        console.print(f"   {rec['description']}")
        console.print(f"   [{style}]Estimated savings: ${savings:.2f}/month[/]")
        console.print()

    tracker.close()


@main.command("export")
@click.option("--format", "fmt", default="csv",
              type=click.Choice(["csv", "json", "markdown"]),
              help="Output format.")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout).")
@click.option("--days", default=30, type=int, help="Number of days to include.")
@click.option("--project", default=None, help="Filter by project name.")
@click.pass_context
def export_cmd(ctx, fmt, output, days, project):
    """Export request logs to CSV, JSON, or Markdown."""
    from llm_cost_monitor.exporters import export_csv, export_json, export_markdown

    db_path = ctx.obj["db_path"]
    tracker = _get_tracker(db_path)
    records = tracker.get_recent_records(limit=100_000, project=project)

    if days:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        records = [r for r in records if r.get("timestamp", "") >= cutoff]

    if fmt == "csv":
        content = export_csv(records)
    elif fmt == "json":
        content = export_json(records)
    else:
        summary = tracker.get_summary(project)
        content = export_markdown(records, summary)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(content)
        console.print(f"[green]Exported {len(records)} records to {output}[/]")
    else:
        click.echo(content)

    tracker.close()


@main.command()
def models():
    """List supported models and their pricing."""
    from llm_cost_monitor.pricing import PricingDatabase

    db = PricingDatabase()
    for provider in db.list_providers():
        console.print(f"\n[bold]{provider.upper()}[/]")
        console.print("-" * 60)
        for m in db.models_by_provider(provider):
            cached = (f" (cached: ${m.cached_input_per_m:.4f}/M)"
                      if m.cached_input_per_m else "")
            console.print(
                f"  {m.model_id:<28} "
                f"in: ${m.input_per_m:>8.4f}/M  "
                f"out: ${m.output_per_m:>8.4f}/M"
                f"{cached}"
            )
    console.print()


if __name__ == "__main__":
    main()
