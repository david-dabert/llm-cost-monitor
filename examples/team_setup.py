"""Multi-project team setup example for llm-cost-monitor.

This example demonstrates how to:
1. Configure multiple projects with different budgets
2. Track costs across teams
3. Set up Slack alerts
4. Export reports for accounting
"""

from pathlib import Path

from llm_cost_monitor.pricing import PricingDatabase, ModelPricing
from llm_cost_monitor.tracker import CostTracker, UsageRecord, Budget
from llm_cost_monitor.alerts import AlertManager
from llm_cost_monitor.exporters import export_csv, export_json


def main():
    db_path = "/tmp/llm-cost-team-demo.db"
    tracker = CostTracker(db_path=db_path)
    pricing = PricingDatabase()

    projects = {
        "frontend-chatbot": {
            "daily": 20.00,
            "weekly": 100.00,
            "monthly": 400.00,
            "primary_model": "gpt-4o-mini",
        },
        "data-pipeline": {
            "daily": 50.00,
            "weekly": 250.00,
            "monthly": 1000.00,
            "primary_model": "claude-sonnet-4-5",
        },
        "research-agent": {
            "daily": 100.00,
            "weekly": 500.00,
            "monthly": 2000.00,
            "primary_model": "claude-opus-4-6",
        },
    }

    for project_name, config in projects.items():
        budget = Budget(
            project=project_name,
            daily_limit=config["daily"],
            weekly_limit=config["weekly"],
            monthly_limit=config["monthly"],
        )
        tracker.set_budget(budget)
        print(f"Budget set for {project_name}: "
              f"${config['daily']}/day, ${config['monthly']}/month")

    simulated_usage = [
        ("frontend-chatbot", "gpt-4o-mini", 5000, 2000, 20),
        ("frontend-chatbot", "gpt-4o-mini", 3000, 1500, 15),
        ("data-pipeline", "claude-sonnet-4-5", 10000, 5000, 5),
        ("data-pipeline", "claude-sonnet-4-5", 8000, 4000, 8),
        ("research-agent", "claude-opus-4-6", 20000, 10000, 3),
        ("research-agent", "gpt-4o", 15000, 8000, 2),
    ]

    for project, model, inp, out, count in simulated_usage:
        cost = pricing.calculate_cost(model, input_tokens=inp, output_tokens=out)
        if cost is None:
            continue
        for _ in range(count):
            tracker.record_usage(UsageRecord(
                model=model,
                provider=pricing.get_pricing(model).provider,
                input_tokens=inp,
                output_tokens=out,
                cost_usd=cost,
                project=project,
            ))

    alert_manager = AlertManager(
        tracker=tracker,
        slack_webhook=None,
        budget_threshold=0.8,
    )

    print("\n--- Budget Status ---")
    for project_name in projects:
        alerts = alert_manager.check_budgets(project_name)
        summary = tracker.get_summary(project_name)
        print(f"\n{project_name}:")
        print(f"  Requests: {summary['total_requests']}")
        print(f"  Today: ${summary['daily_cost']:.4f}")
        print(f"  Month: ${summary['monthly_cost']:.4f}")

    print("\n--- Anomaly Check ---")
    for project_name in projects:
        anomaly = alert_manager.check_anomaly(project_name)
        if anomaly:
            print(f"  {project_name}: {anomaly.message}")
        else:
            print(f"  {project_name}: No anomalies detected")

    print("\n--- Exporting Reports ---")
    records = tracker.get_recent_records(limit=10_000)

    csv_path = Path("/tmp/llm-costs-team.csv")
    export_csv(records, csv_path)
    print(f"  CSV exported to {csv_path}")

    json_path = Path("/tmp/llm-costs-team.json")
    export_json(records, json_path)
    print(f"  JSON exported to {json_path}")

    pricing.set_pricing(
        "ft:gpt-4o-mini:my-org",
        ModelPricing(
            model_id="ft:gpt-4o-mini:my-org",
            provider="openai",
            input_per_m=0.30,
            output_per_m=1.20,
        ),
    )
    print(f"\nCustom pricing added for fine-tuned model")

    print("\n--- Cost Comparison (1M input + 500K output tokens) ---")
    comparison_models = [
        "gpt-4o", "gpt-4o-mini", "gpt-4.1",
        "claude-opus-4-6", "claude-sonnet-4-5", "claude-haiku-3-5",
        "gemini-2.5-pro", "gemini-2.5-flash",
    ]
    for model in comparison_models:
        cost = pricing.calculate_cost(model, input_tokens=1_000_000, output_tokens=500_000)
        if cost is not None:
            print(f"  {model:<25} ${cost:>10.2f}")

    tracker.close()
    print(f"\nDone. Database at: {db_path}")


if __name__ == "__main__":
    main()
