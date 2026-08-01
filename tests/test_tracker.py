"""Tests for the cost tracking engine."""

from datetime import datetime, timedelta

import pytest

from llm_cost_monitor.tracker import Budget, CostTracker, UsageRecord


@pytest.fixture
def tracker():
    """Create an in-memory tracker for testing."""
    t = CostTracker(db_path=":memory:")
    yield t
    t.close()


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""

    def test_default_values(self):
        record = UsageRecord()
        assert record.model == "unknown"
        assert record.input_tokens == 0
        assert record.cost_usd == 0.0
        assert record.timestamp is not None

    def test_total_tokens_auto_calculated(self):
        record = UsageRecord(input_tokens=100, output_tokens=50)
        assert record.total_tokens == 150

    def test_explicit_total_tokens_preserved(self):
        record = UsageRecord(input_tokens=100, output_tokens=50, total_tokens=200)
        assert record.total_tokens == 200

    def test_custom_timestamp(self):
        ts = "2026-01-01T00:00:00"
        record = UsageRecord(timestamp=ts)
        assert record.timestamp == ts


class TestCostTracker:
    """Tests for CostTracker."""

    def test_record_usage(self, tracker):
        record = UsageRecord(
            model="gpt-4o",
            provider="openai",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.006,
            project="test-project",
        )
        row_id = tracker.record_usage(record)
        assert row_id is not None
        assert row_id > 0

    def test_get_summary_empty(self, tracker):
        summary = tracker.get_summary()
        assert summary["total_requests"] == 0
        assert summary["total_cost_usd"] == 0

    def test_get_summary_with_data(self, tracker):
        for i in range(5):
            tracker.record_usage(UsageRecord(
                model="gpt-4o",
                provider="openai",
                input_tokens=1000,
                output_tokens=500,
                cost_usd=0.006,
            ))
        summary = tracker.get_summary()
        assert summary["total_requests"] == 5
        assert abs(summary["total_cost_usd"] - 0.03) < 1e-6

    def test_get_daily_cost(self, tracker):
        tracker.record_usage(UsageRecord(
            model="gpt-4o",
            cost_usd=1.50,
        ))
        daily = tracker.get_daily_cost()
        assert daily >= 1.50

    def test_get_cost_by_model(self, tracker):
        tracker.record_usage(UsageRecord(model="gpt-4o", provider="openai", cost_usd=1.0))
        tracker.record_usage(UsageRecord(model="gpt-4o", provider="openai", cost_usd=2.0))
        tracker.record_usage(UsageRecord(model="claude-opus-4-6", provider="anthropic", cost_usd=5.0))

        breakdown = tracker.get_cost_by_model()
        assert len(breakdown) == 2
        assert breakdown[0]["model"] == "claude-opus-4-6"
        assert breakdown[0]["total_cost"] == 5.0
        assert breakdown[1]["model"] == "gpt-4o"
        assert breakdown[1]["total_cost"] == 3.0

    def test_get_cost_by_project(self, tracker):
        tracker.record_usage(UsageRecord(project="alpha", cost_usd=10.0))
        tracker.record_usage(UsageRecord(project="beta", cost_usd=3.0))
        tracker.record_usage(UsageRecord(project="alpha", cost_usd=5.0))

        breakdown = tracker.get_cost_by_project()
        assert len(breakdown) == 2
        assert breakdown[0]["project"] == "alpha"
        assert breakdown[0]["total_cost"] == 15.0

    def test_project_filter(self, tracker):
        tracker.record_usage(UsageRecord(project="alpha", cost_usd=10.0))
        tracker.record_usage(UsageRecord(project="beta", cost_usd=3.0))

        summary_alpha = tracker.get_summary(project="alpha")
        assert summary_alpha["total_cost_usd"] == 10.0

        summary_beta = tracker.get_summary(project="beta")
        assert summary_beta["total_cost_usd"] == 3.0

    def test_recent_records(self, tracker):
        for i in range(20):
            tracker.record_usage(UsageRecord(model=f"model-{i}", cost_usd=float(i)))

        recent = tracker.get_recent_records(limit=5)
        assert len(recent) == 5
        assert recent[0]["model"] == "model-19"

    def test_daily_trend(self, tracker):
        tracker.record_usage(UsageRecord(cost_usd=5.0))
        tracker.record_usage(UsageRecord(cost_usd=3.0))

        trend = tracker.get_daily_trend(days=7)
        assert len(trend) >= 1
        today_entry = trend[-1]
        assert today_entry["total_cost"] == 8.0


class TestBudget:
    """Tests for Budget management."""

    def test_set_and_get_budget(self, tracker):
        budget = Budget(
            project="test",
            daily_limit=10.0,
            weekly_limit=50.0,
            monthly_limit=200.0,
        )
        tracker.set_budget(budget)
        retrieved = tracker.get_budget("test")
        assert retrieved is not None
        assert retrieved.daily_limit == 10.0
        assert retrieved.weekly_limit == 50.0
        assert retrieved.monthly_limit == 200.0

    def test_get_nonexistent_budget(self, tracker):
        budget = tracker.get_budget("nonexistent")
        assert budget is None

    def test_budget_update(self, tracker):
        tracker.set_budget(Budget(project="test", daily_limit=10.0))
        tracker.set_budget(Budget(project="test", daily_limit=20.0, monthly_limit=100.0))
        budget = tracker.get_budget("test")
        assert budget.daily_limit == 20.0
        assert budget.monthly_limit == 100.0

    def test_budget_violations(self, tracker):
        tracker.set_budget(Budget(project="test", daily_limit=5.0))
        tracker.record_usage(UsageRecord(project="test", cost_usd=6.0))

        violations, warnings = tracker.check_budget("test")
        assert len(violations) >= 1
        assert "exceeded" in violations[0].lower()

    def test_budget_warnings(self, tracker):
        tracker.set_budget(Budget(project="test", daily_limit=10.0))
        tracker.record_usage(UsageRecord(project="test", cost_usd=8.5))

        violations, warnings = tracker.check_budget("test")
        assert len(warnings) >= 1

    def test_budget_check_against(self):
        budget = Budget(project="test", daily_limit=10.0, monthly_limit=100.0)
        violations = budget.check_against(daily=11.0, weekly=0, monthly=50.0)
        assert len(violations) == 1
        assert "Daily" in violations[0]

    def test_budget_threshold_warning(self):
        budget = Budget(project="test", daily_limit=10.0)
        warnings = budget.check_threshold(daily=9.0, weekly=0, monthly=0, threshold=0.8)
        assert len(warnings) == 1
        assert "90%" in warnings[0]

    def test_no_budget_no_alerts(self, tracker):
        violations, warnings = tracker.check_budget("no-budget-project")
        assert violations == []
        assert warnings == []

    def test_cost_for_period(self, tracker):
        now = datetime.utcnow()
        tracker.record_usage(UsageRecord(
            cost_usd=5.0,
            timestamp=now.isoformat(),
        ))
        tracker.record_usage(UsageRecord(
            cost_usd=3.0,
            timestamp=(now - timedelta(hours=1)).isoformat(),
        ))

        start = now - timedelta(hours=2)
        cost = tracker.get_cost_for_period(start)
        assert cost == 8.0
