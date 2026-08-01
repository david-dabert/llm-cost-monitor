"""Basic usage example for llm-cost-monitor.

This example demonstrates how to:
1. Track costs programmatically (without the proxy)
2. Set budgets and check them
3. Generate reports
"""

from llm_cost_monitor.pricing import PricingDatabase
from llm_cost_monitor.tracker import CostTracker, UsageRecord, Budget
from llm_cost_monitor.alerts import AlertManager
from llm_cost_monitor.dashboard import print_report


def main():
    pricing = PricingDatabase()
    tracker = CostTracker(db_path=":memory:")

    cost = pricing.calculate_cost(
        model_name="gpt-4o",
        input_tokens=2000,
        output_tokens=500,
    )
    print(f"Cost for 2K input + 500 output tokens on GPT-4o: ${cost:.6f}")

    cost_opus = pricing.calculate_cost(
        model_name="claude-opus-4-6",
        input_tokens=2000,
        output_tokens=500,
    )
    print(f"Same request on Claude Opus 4.6: ${cost_opus:.6f}")

    record = UsageRecord(
        model="gpt-4o",
        provider="openai",
        input_tokens=2000,
        output_tokens=500,
        cost_usd=cost,
        project="my-chatbot",
        task="user-query",
    )
    tracker.record_usage(record)

    for i in range(10):
        c = pricing.calculate_cost("claude-sonnet-4-5", input_tokens=1500, output_tokens=800)
        tracker.record_usage(UsageRecord(
            model="claude-sonnet-4-5",
            provider="anthropic",
            input_tokens=1500,
            output_tokens=800,
            cost_usd=c,
            project="my-chatbot",
            task=f"batch-task-{i}",
        ))

    budget = Budget(
        project="my-chatbot",
        daily_limit=5.00,
        weekly_limit=25.00,
        monthly_limit=100.00,
    )
    tracker.set_budget(budget)

    violations, warnings = tracker.check_budget("my-chatbot")
    if warnings:
        print("\nBudget warnings:")
        for w in warnings:
            print(f"  {w}")
    if violations:
        print("\nBudget violations:")
        for v in violations:
            print(f"  {v}")

    alerts = AlertManager(tracker=tracker)
    alerts.check_budgets("my-chatbot")

    summary = tracker.get_summary("my-chatbot")
    print(f"\nProject summary:")
    print(f"  Total requests: {summary['total_requests']}")
    print(f"  Total cost: ${summary['total_cost_usd']:.4f}")
    print(f"  Today: ${summary['daily_cost']:.4f}")

    print("\n--- Full Report ---")
    print_report(tracker, project="my-chatbot")

    tracker.close()


if __name__ == "__main__":
    main()
