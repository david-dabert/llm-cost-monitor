"""Alert system for budget thresholds and anomaly detection.

Supports console output, Slack webhooks, and email notifications.
"""

from __future__ import annotations

import json
import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from enum import Enum
from typing import Callable, Optional

import requests

from llm_cost_monitor.tracker import CostTracker

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Severity level for alerts."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """A single alert event."""

    level: AlertLevel
    message: str
    project: str = "default"
    timestamp: str = ""
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "message": self.message,
            "project": self.project,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class AlertManager:
    """Manages alert channels and anomaly detection."""

    def __init__(
        self,
        tracker: CostTracker,
        slack_webhook: Optional[str] = None,
        email_to: Optional[str] = None,
        email_from: Optional[str] = None,
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        budget_threshold: float = 0.8,
    ):
        self.tracker = tracker
        self.slack_webhook = slack_webhook
        self.email_to = email_to
        self.email_from = email_from or "llm-cost-monitor@localhost"
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.budget_threshold = budget_threshold
        self._handlers: list[Callable[[Alert], None]] = []
        self._alert_history: list[Alert] = []

    def add_handler(self, handler: Callable[[Alert], None]) -> None:
        """Register a custom alert handler."""
        self._handlers.append(handler)

    def _send_console(self, alert: Alert) -> None:
        """Print alert to console."""
        prefix = {
            AlertLevel.INFO: "[INFO]",
            AlertLevel.WARNING: "[WARNING]",
            AlertLevel.CRITICAL: "[CRITICAL]",
        }
        print(f"{prefix[alert.level]} {alert.message} (project: {alert.project})")

    def _send_slack(self, alert: Alert) -> None:
        """Send alert to Slack via webhook."""
        if not self.slack_webhook:
            return
        emoji = {
            AlertLevel.INFO: ":information_source:",
            AlertLevel.WARNING: ":warning:",
            AlertLevel.CRITICAL: ":rotating_light:",
        }
        payload = {
            "text": f"{emoji[alert.level]} *LLM Cost Alert*\n{alert.message}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{emoji[alert.level]} *LLM Cost Alert*\n"
                            f"*Level:* {alert.level.value}\n"
                            f"*Project:* {alert.project}\n"
                            f"*Message:* {alert.message}\n"
                            f"*Time:* {alert.timestamp}"
                        ),
                    },
                }
            ],
        }
        try:
            resp = requests.post(
                self.slack_webhook,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Failed to send Slack alert: %s", exc)

    def _send_email(self, alert: Alert) -> None:
        """Send alert via email."""
        if not self.email_to:
            return
        subject = f"[LLM Cost {alert.level.value.upper()}] {alert.message[:60]}"
        body = (
            f"Level: {alert.level.value}\n"
            f"Project: {alert.project}\n"
            f"Time: {alert.timestamp}\n\n"
            f"{alert.message}\n\n"
            f"Details: {json.dumps(alert.details, indent=2)}"
        )
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.sendmail(self.email_from, [self.email_to], msg.as_string())
        except (smtplib.SMTPException, ConnectionError) as exc:
            logger.error("Failed to send email alert: %s", exc)

    def dispatch(self, alert: Alert) -> None:
        """Dispatch an alert to all configured channels."""
        self._alert_history.append(alert)
        self._send_console(alert)
        if self.slack_webhook:
            self._send_slack(alert)
        if self.email_to:
            self._send_email(alert)
        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as exc:
                logger.error("Custom alert handler failed: %s", exc)

    def check_budgets(self, project: str = "default") -> list[Alert]:
        """Check budget status and fire alerts if needed."""
        violations, warnings = self.tracker.check_budget(project)
        alerts = []
        for v in violations:
            alert = Alert(
                level=AlertLevel.CRITICAL,
                message=v,
                project=project,
            )
            alerts.append(alert)
            self.dispatch(alert)
        for w in warnings:
            alert = Alert(
                level=AlertLevel.WARNING,
                message=w,
                project=project,
            )
            alerts.append(alert)
            self.dispatch(alert)
        return alerts

    def check_anomaly(self, project: str = "default", threshold_multiplier: float = 3.0) -> Optional[Alert]:
        """Detect spend spikes by comparing today vs. 7-day average."""
        trend = self.tracker.get_daily_trend(days=7, project=project)
        if len(trend) < 2:
            return None
        historical = trend[:-1]
        avg_cost = sum(t["total_cost"] for t in historical) / len(historical) if historical else 0
        today_cost = self.tracker.get_daily_cost(project)
        if avg_cost > 0 and today_cost > avg_cost * threshold_multiplier:
            alert = Alert(
                level=AlertLevel.WARNING,
                message=(
                    f"Spend spike detected: today ${today_cost:.2f} vs "
                    f"7-day avg ${avg_cost:.2f} ({today_cost/avg_cost:.1f}x)"
                ),
                project=project,
                details={"today": today_cost, "avg_7d": avg_cost},
            )
            self.dispatch(alert)
            return alert
        return None

    def get_history(self) -> list[Alert]:
        """Return all alerts fired in this session."""
        return list(self._alert_history)
