"""Cost tracking engine with SQLite persistence.

Provides per-project budgets, daily/weekly/monthly aggregation,
budget alerts, anomaly detection, and cost-per-model breakdown.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """A single LLM API usage record."""

    model: str = "unknown"
    provider: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    project: str = "default"
    task: str = ""
    latency_ms: int = 0
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens


@dataclass
class Budget:
    """Budget configuration for a project.

    Supports per-period limits (daily, weekly, monthly).
    """

    project: str
    daily_limit: Optional[float] = None
    weekly_limit: Optional[float] = None
    monthly_limit: Optional[float] = None

    def check_against(self, daily: float, weekly: float, monthly: float) -> list[str]:
        """Check current spending against budget limits. Returns list of violations."""
        violations = []
        if self.daily_limit and daily >= self.daily_limit:
            violations.append(
                f"Daily budget exceeded: ${daily:.2f} >= ${self.daily_limit:.2f}"
            )
        if self.weekly_limit and weekly >= self.weekly_limit:
            violations.append(
                f"Weekly budget exceeded: ${weekly:.2f} >= ${self.weekly_limit:.2f}"
            )
        if self.monthly_limit and monthly >= self.monthly_limit:
            violations.append(
                f"Monthly budget exceeded: ${monthly:.2f} >= ${self.monthly_limit:.2f}"
            )
        return violations

    def check_threshold(
        self, daily: float, weekly: float, monthly: float, threshold: float = 0.8
    ) -> list[str]:
        """Check if spending is approaching budget limits. Returns warnings."""
        warnings = []
        if self.daily_limit and daily >= self.daily_limit * threshold:
            pct = (daily / self.daily_limit) * 100
            warnings.append(
                f"Daily budget at {pct:.0f}%: ${daily:.2f} / ${self.daily_limit:.2f}"
            )
        if self.weekly_limit and weekly >= self.weekly_limit * threshold:
            pct = (weekly / self.weekly_limit) * 100
            warnings.append(
                f"Weekly budget at {pct:.0f}%: ${weekly:.2f} / ${self.weekly_limit:.2f}"
            )
        if self.monthly_limit and monthly >= self.monthly_limit * threshold:
            pct = (monthly / self.monthly_limit) * 100
            warnings.append(
                f"Monthly budget at {pct:.0f}%: ${monthly:.2f} / ${self.monthly_limit:.2f}"
            )
        return warnings


class CostTracker:
    """SQLite-backed cost tracking engine."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            if self.db_path != ":memory:":
                db_file = Path(self.db_path).expanduser()
                db_file.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(str(db_file))
            else:
                self._conn = sqlite3.connect(":memory:")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        """Create tables if they do not exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                project TEXT NOT NULL DEFAULT 'default',
                task TEXT DEFAULT '',
                latency_ms INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS budgets (
                project TEXT PRIMARY KEY,
                daily_limit REAL,
                weekly_limit REAL,
                monthly_limit REAL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                config TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage(timestamp);
            CREATE INDEX IF NOT EXISTS idx_usage_project ON usage(project);
            CREATE INDEX IF NOT EXISTS idx_usage_model ON usage(model);
        """)
        conn.commit()

    def record_usage(self, record: UsageRecord) -> int:
        """Record a usage event. Returns the row ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO usage
               (timestamp, model, provider, input_tokens, output_tokens,
                cached_input_tokens, total_tokens, cost_usd, project, task, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.timestamp,
                record.model,
                record.provider,
                record.input_tokens,
                record.output_tokens,
                record.cached_input_tokens,
                record.total_tokens,
                record.cost_usd,
                record.project,
                record.task,
                record.latency_ms,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    def get_cost_for_period(
        self,
        start: datetime,
        end: Optional[datetime] = None,
        project: Optional[str] = None,
    ) -> float:
        """Get total cost for a time period, optionally filtered by project."""
        if end is None:
            end = datetime.utcnow()
        conn = self._get_conn()
        query = "SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE timestamp >= ? AND timestamp <= ?"
        params: list = [start.isoformat(), end.isoformat()]
        if project:
            query += " AND project = ?"
            params.append(project)
        result = conn.execute(query, params).fetchone()
        return result[0]

    def get_daily_cost(self, project: Optional[str] = None) -> float:
        """Get today's total cost."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.get_cost_for_period(today, project=project)

    def get_weekly_cost(self, project: Optional[str] = None) -> float:
        """Get this week's total cost (Monday start)."""
        now = datetime.utcnow()
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.get_cost_for_period(monday, project=project)

    def get_monthly_cost(self, project: Optional[str] = None) -> float:
        """Get this month's total cost."""
        now = datetime.utcnow()
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.get_cost_for_period(first_of_month, project=project)

    def get_cost_by_model(
        self,
        start: Optional[datetime] = None,
        project: Optional[str] = None,
    ) -> list[dict]:
        """Get cost breakdown by model."""
        conn = self._get_conn()
        query = """
            SELECT model, provider,
                   COUNT(*) as request_count,
                   SUM(input_tokens) as total_input_tokens,
                   SUM(output_tokens) as total_output_tokens,
                   SUM(cost_usd) as total_cost,
                   AVG(latency_ms) as avg_latency_ms
            FROM usage WHERE 1=1
        """
        params: list = []
        if start:
            query += " AND timestamp >= ?"
            params.append(start.isoformat())
        if project:
            query += " AND project = ?"
            params.append(project)
        query += " GROUP BY model, provider ORDER BY total_cost DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_cost_by_project(self, start: Optional[datetime] = None) -> list[dict]:
        """Get cost breakdown by project."""
        conn = self._get_conn()
        query = """
            SELECT project,
                   COUNT(*) as request_count,
                   SUM(cost_usd) as total_cost,
                   SUM(input_tokens) as total_input_tokens,
                   SUM(output_tokens) as total_output_tokens
            FROM usage WHERE 1=1
        """
        params: list = []
        if start:
            query += " AND timestamp >= ?"
            params.append(start.isoformat())
        query += " GROUP BY project ORDER BY total_cost DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_daily_trend(self, days: int = 30, project: Optional[str] = None) -> list[dict]:
        """Get daily cost trend for the last N days."""
        conn = self._get_conn()
        start = (datetime.utcnow() - timedelta(days=days)).isoformat()
        query = """
            SELECT DATE(timestamp) as date,
                   SUM(cost_usd) as total_cost,
                   COUNT(*) as request_count,
                   SUM(input_tokens + output_tokens) as total_tokens
            FROM usage WHERE timestamp >= ?
        """
        params: list = [start]
        if project:
            query += " AND project = ?"
            params.append(project)
        query += " GROUP BY DATE(timestamp) ORDER BY date"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_summary(self, project: Optional[str] = None) -> dict:
        """Get an overall summary of costs."""
        conn = self._get_conn()
        query = """
            SELECT COUNT(*) as total_requests,
                   COALESCE(SUM(cost_usd), 0) as total_cost,
                   COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                   COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                   COALESCE(AVG(latency_ms), 0) as avg_latency_ms
            FROM usage
        """
        params: list = []
        if project:
            query += " WHERE project = ?"
            params.append(project)
        row = conn.execute(query, params).fetchone()
        return {
            "total_requests": row["total_requests"],
            "total_cost_usd": round(row["total_cost"], 6),
            "total_input_tokens": row["total_input_tokens"],
            "total_output_tokens": row["total_output_tokens"],
            "avg_latency_ms": round(row["avg_latency_ms"], 1),
            "daily_cost": round(self.get_daily_cost(project), 6),
            "weekly_cost": round(self.get_weekly_cost(project), 6),
            "monthly_cost": round(self.get_monthly_cost(project), 6),
        }

    def set_budget(self, budget: Budget) -> None:
        """Set or update a project budget."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO budgets (project, daily_limit, weekly_limit, monthly_limit)
               VALUES (?, ?, ?, ?)""",
            (budget.project, budget.daily_limit, budget.weekly_limit, budget.monthly_limit),
        )
        conn.commit()

    def get_budget(self, project: str) -> Optional[Budget]:
        """Get the budget for a project."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM budgets WHERE project = ?", (project,)
        ).fetchone()
        if row is None:
            return None
        return Budget(
            project=row["project"],
            daily_limit=row["daily_limit"],
            weekly_limit=row["weekly_limit"],
            monthly_limit=row["monthly_limit"],
        )

    def list_budgets(self) -> list[Budget]:
        """List all configured budgets."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM budgets ORDER BY project").fetchall()
        return [
            Budget(
                project=r["project"],
                daily_limit=r["daily_limit"],
                weekly_limit=r["weekly_limit"],
                monthly_limit=r["monthly_limit"],
            )
            for r in rows
        ]

    def check_budget(self, project: str) -> tuple[list[str], list[str]]:
        """Check budget for a project. Returns (violations, warnings)."""
        budget = self.get_budget(project)
        if budget is None:
            return [], []
        daily = self.get_daily_cost(project)
        weekly = self.get_weekly_cost(project)
        monthly = self.get_monthly_cost(project)
        violations = budget.check_against(daily, weekly, monthly)
        warnings = budget.check_threshold(daily, weekly, monthly)
        return violations, warnings

    def detect_anomaly(
        self, project: Optional[str] = None, multiplier: float = 2.0
    ) -> Optional[str]:
        """Detect cost anomalies: today's cost > multiplier * 7-day average.

        Returns a warning string if anomaly detected, None otherwise.
        """
        daily = self.get_daily_cost(project)
        if daily == 0:
            return None

        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        weekly_cost = self.get_cost_for_period(week_ago, today_start, project)
        avg_daily = weekly_cost / 7.0 if weekly_cost > 0 else 0

        if avg_daily > 0 and daily > avg_daily * multiplier:
            scope = f"project '{project}'" if project else "global"
            return (
                f"Cost anomaly detected for {scope}: today ${daily:.2f} is "
                f"{daily / avg_daily:.1f}x the 7-day average of ${avg_daily:.2f}/day"
            )
        return None

    def get_recent_records(
        self, limit: int = 50, project: Optional[str] = None
    ) -> list[dict]:
        """Get the most recent usage records."""
        conn = self._get_conn()
        query = "SELECT * FROM usage"
        params: list = []
        if project:
            query += " WHERE project = ?"
            params.append(project)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
