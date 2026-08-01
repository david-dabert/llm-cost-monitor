"""Web dashboard for LLM cost monitoring.

Flask-based dashboard with Chart.js visualizations:
- Cost by model (doughnut chart)
- Daily cost trend (line chart)
- Budget progress bars
- Recent requests table
- Optimization recommendation cards
Dark mode, auto-refresh every 30 seconds.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from flask import Flask, jsonify

from llm_cost_monitor.tracker import CostTracker
from llm_cost_monitor.optimizer import CostOptimizer
from llm_cost_monitor.pricing import PricingDatabase

logger = logging.getLogger(__name__)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM Cost Monitor Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 8px; font-size: 1.8em; }
  .subtitle { color: #8b949e; margin-bottom: 20px; font-size: 0.9em; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
          gap: 16px; margin-bottom: 16px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 20px; }
  .card h2 { color: #58a6ff; font-size: 1.1em; margin-bottom: 12px; }
  .stat-row { display: flex; justify-content: space-between; padding: 6px 0;
              border-bottom: 1px solid #21262d; }
  .stat-label { color: #8b949e; }
  .stat-value { color: #f0f6fc; font-weight: 600; }
  .stat-value.cost { color: #3fb950; }
  .stat-value.warn { color: #d29922; }
  .stat-value.danger { color: #f85149; }
  .budget-bar { background: #21262d; border-radius: 4px; height: 24px;
                margin: 8px 0; position: relative; overflow: hidden; }
  .budget-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
  .budget-fill.ok { background: #238636; }
  .budget-fill.warn { background: #9e6a03; }
  .budget-fill.over { background: #da3633; }
  .budget-text { position: absolute; right: 8px; top: 3px; font-size: 0.8em;
                 color: #f0f6fc; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
  th { text-align: left; color: #8b949e; padding: 8px 6px;
       border-bottom: 2px solid #30363d; }
  td { padding: 6px; border-bottom: 1px solid #21262d; }
  .opt-card { background: #1c2128; border: 1px solid #30363d; border-radius: 6px;
              padding: 12px; margin-bottom: 8px; }
  .opt-title { color: #d29922; font-weight: 600; margin-bottom: 4px; }
  .opt-savings { color: #3fb950; font-size: 0.9em; }
  .chart-container { position: relative; height: 250px; }
  .refresh-note { text-align: center; color: #484f58; font-size: 0.8em;
                  margin-top: 16px; }
</style>
</head>
<body>
<h1>LLM Cost Monitor</h1>
<p class="subtitle" id="last-update">Loading...</p>

<div class="grid">
  <div class="card">
    <h2>Cost Summary</h2>
    <div id="summary-content">Loading...</div>
  </div>
  <div class="card">
    <h2>Budget Status</h2>
    <div id="budget-content">Loading...</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Cost by Model</h2>
    <div class="chart-container"><canvas id="modelChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Daily Cost Trend</h2>
    <div class="chart-container"><canvas id="trendChart"></canvas></div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Recent Requests</h2>
    <div id="recent-content" style="max-height:300px;overflow-y:auto;">Loading...</div>
  </div>
  <div class="card">
    <h2>Optimization Recommendations</h2>
    <div id="opt-content">Loading...</div>
  </div>
</div>

<p class="refresh-note">Auto-refreshes every 30 seconds</p>

<script>
let modelChart = null;
let trendChart = null;

const COLORS = [
  '#58a6ff','#3fb950','#d29922','#f85149','#bc8cff',
  '#39d2c0','#ff7b72','#79c0ff','#d2a8ff','#ffa657'
];

function formatCost(v) {
  if (v < 0.01) return '$' + v.toFixed(6);
  if (v < 1) return '$' + v.toFixed(4);
  return '$' + v.toFixed(2);
}

function formatTokens(t) {
  if (t < 1000) return t.toString();
  if (t < 1e6) return (t/1000).toFixed(1) + 'K';
  return (t/1e6).toFixed(2) + 'M';
}

async function fetchData(endpoint) {
  const r = await fetch('/api/' + endpoint);
  return r.json();
}

async function refresh() {
  try {
    const [summary, models, trend, recent, budgets, opts] = await Promise.all([
      fetchData('summary'), fetchData('models'), fetchData('trend'),
      fetchData('recent'), fetchData('budgets'), fetchData('optimize')
    ]);

    // Summary
    let html = '';
    const s = summary;
    html += `<div class="stat-row"><span class="stat-label">Total Requests</span>
             <span class="stat-value">${s.total_requests.toLocaleString()}</span></div>`;
    html += `<div class="stat-row"><span class="stat-label">Total Cost</span>
             <span class="stat-value cost">${formatCost(s.total_cost_usd)}</span></div>`;
    html += `<div class="stat-row"><span class="stat-label">Today</span>
             <span class="stat-value cost">${formatCost(s.daily_cost)}</span></div>`;
    html += `<div class="stat-row"><span class="stat-label">This Week</span>
             <span class="stat-value cost">${formatCost(s.weekly_cost)}</span></div>`;
    html += `<div class="stat-row"><span class="stat-label">This Month</span>
             <span class="stat-value cost">${formatCost(s.monthly_cost)}</span></div>`;
    html += `<div class="stat-row"><span class="stat-label">Avg Latency</span>
             <span class="stat-value">${s.avg_latency_ms.toFixed(0)}ms</span></div>`;
    document.getElementById('summary-content').innerHTML = html;

    // Budget
    let bhtml = '';
    if (budgets.length === 0) {
      bhtml = '<p style="color:#8b949e">No budgets configured. Use: llm-cost budget set</p>';
    }
    for (const b of budgets) {
      const pct = b.amount > 0 ? Math.min((b.current_spend / b.amount) * 100, 100) : 0;
      const cls = pct >= 100 ? 'over' : pct >= 80 ? 'warn' : 'ok';
      bhtml += `<div><strong>${b.name}</strong> (${b.period})
                <div class="budget-bar"><div class="budget-fill ${cls}" style="width:${pct}%"></div>
                <span class="budget-text">${formatCost(b.current_spend)} / ${formatCost(b.amount)}</span>
                </div></div>`;
    }
    document.getElementById('budget-content').innerHTML = bhtml;

    // Model doughnut chart
    if (modelChart) modelChart.destroy();
    const mLabels = models.map(m => m.model);
    const mData = models.map(m => m.total_cost);
    modelChart = new Chart(document.getElementById('modelChart'), {
      type: 'doughnut',
      data: { labels: mLabels, datasets: [{
        data: mData, backgroundColor: COLORS.slice(0, mLabels.length),
        borderWidth: 0
      }]},
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'right', labels: { color: '#c9d1d9', font: {size:11} } } }
      }
    });

    // Trend line chart
    if (trendChart) trendChart.destroy();
    const tLabels = trend.map(t => t.date);
    const tData = trend.map(t => t.total_cost);
    trendChart = new Chart(document.getElementById('trendChart'), {
      type: 'line',
      data: { labels: tLabels, datasets: [{
        label: 'Daily Cost ($)', data: tData,
        borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.1)',
        fill: true, tension: 0.3, pointRadius: 3
      }]},
      options: { responsive: true, maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } },
          y: { ticks: { color: '#8b949e', callback: v => '$'+v.toFixed(2) },
               grid: { color: '#21262d' } }
        },
        plugins: { legend: { labels: { color: '#c9d1d9' } } }
      }
    });

    // Recent requests
    let rhtml = '<table><tr><th>Time</th><th>Model</th><th>Tokens</th><th>Cost</th><th>Project</th></tr>';
    for (const r of recent.slice(0, 20)) {
      const ts = r.timestamp ? r.timestamp.substring(0, 19) : '';
      const tokens = (r.input_tokens || 0) + (r.output_tokens || 0);
      rhtml += `<tr><td>${ts}</td><td>${r.model}</td><td>${formatTokens(tokens)}</td>
                <td style="color:#3fb950">${formatCost(r.cost_usd || 0)}</td>
                <td>${r.project}</td></tr>`;
    }
    rhtml += '</table>';
    if (recent.length === 0) rhtml = '<p style="color:#8b949e">No requests yet</p>';
    document.getElementById('recent-content').innerHTML = rhtml;

    // Optimization
    let ohtml = '';
    for (const o of opts) {
      ohtml += `<div class="opt-card"><div class="opt-title">${o.strategy}</div>
                <p>${o.description}</p>
                <span class="opt-savings">Estimated savings: ${formatCost(o.estimated_savings)}/month</span></div>`;
    }
    if (opts.length === 0) ohtml = '<p style="color:#8b949e">No optimization recommendations yet</p>';
    document.getElementById('opt-content').innerHTML = ohtml;

    document.getElementById('last-update').textContent =
      'Last updated: ' + new Date().toLocaleString();
  } catch (e) {
    console.error('Dashboard refresh error:', e);
  }
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""


def create_dashboard_app(
    tracker: CostTracker,
    pricing: PricingDatabase,
) -> Flask:
    """Create the Flask dashboard application."""
    app = Flask(__name__)
    optimizer = CostOptimizer(tracker, pricing)

    @app.route("/")
    def index():
        return DASHBOARD_HTML

    @app.route("/api/summary")
    def api_summary():
        return jsonify(tracker.get_summary())

    @app.route("/api/models")
    def api_models():
        start = datetime.utcnow() - timedelta(days=30)
        return jsonify(tracker.get_cost_by_model(start=start))

    @app.route("/api/trend")
    def api_trend():
        return jsonify(tracker.get_daily_trend(days=30))

    @app.route("/api/recent")
    def api_recent():
        return jsonify(tracker.get_recent_records(limit=50))

    @app.route("/api/projects")
    def api_projects():
        return jsonify(tracker.get_cost_by_project())

    @app.route("/api/budgets")
    def api_budgets():
        budgets = tracker.list_budgets()
        result = []
        for b in budgets:
            daily = tracker.get_daily_cost(b.project)
            weekly = tracker.get_weekly_cost(b.project)
            monthly = tracker.get_monthly_cost(b.project)
            if b.daily_limit:
                result.append({
                    "name": f"{b.project} (daily)",
                    "amount": b.daily_limit,
                    "period": "daily",
                    "project": b.project,
                    "current_spend": round(daily, 6),
                })
            if b.weekly_limit:
                result.append({
                    "name": f"{b.project} (weekly)",
                    "amount": b.weekly_limit,
                    "period": "weekly",
                    "project": b.project,
                    "current_spend": round(weekly, 6),
                })
            if b.monthly_limit:
                result.append({
                    "name": f"{b.project} (monthly)",
                    "amount": b.monthly_limit,
                    "period": "monthly",
                    "project": b.project,
                    "current_spend": round(monthly, 6),
                })
        return jsonify(result)

    @app.route("/api/optimize")
    def api_optimize():
        recommendations = optimizer.run_all()
        return jsonify([
            {
                "strategy": r["strategy"],
                "description": r["description"],
                "estimated_savings": r["estimated_savings"],
            }
            for r in recommendations
        ])

    return app


def start_dashboard(
    db_path: str = "costs.db",
    host: str = "0.0.0.0",
    port: int = 5050,
) -> None:
    """Start the dashboard web server."""
    logging.basicConfig(level=logging.INFO)

    tracker = CostTracker(db_path)
    pricing = PricingDatabase()
    app = create_dashboard_app(tracker, pricing)

    logger.info("LLM Cost Monitor dashboard starting on %s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)
