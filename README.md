```
 _     _     __  __    ____          _     __  __             _ _
| |   | |   |  \/  |  / ___|___  ___| |_  |  \/  | ___  _ __ (_) |_ ___  _ __
| |   | |   | |\/| | | |   / _ \/ __| __| | |\/| |/ _ \| '_ \| | __/ _ \| '__|
| |___| |___| |  | | | |__| (_) \__ \ |_  | |  | | (_) | | | | | || (_) | |
|_____|_____|_|  |_|  \____\___/|___/\__| |_|  |_|\___/|_| |_|_|\__\___/|_|
```

# LLM Cost Monitor

A transparent proxy and real-time dashboard that intercepts LLM API calls, tracks costs,
provides budget alerts, and surfaces optimization recommendations.

Drop it between your application and any LLM provider. No SDK changes required.

---

## Features

- **Transparent Proxy** -- Intercepts calls to OpenAI, Anthropic, Google Gemini, and Mistral
  APIs without any code changes. Point your SDK's base URL at the proxy and everything
  else stays the same.

- **Real-Time Cost Tracking** -- Every request is logged with model name, token counts
  (input, output, cache read, cache write), calculated cost, latency, and project tag.

- **Web Dashboard** -- Dark-mode Chart.js dashboard with cost-by-model doughnut chart,
  daily spend trend line, budget progress bars, recent requests table, and optimization
  recommendation cards. Auto-refreshes every 30 seconds.

- **Budget Alerts** -- Set daily, weekly, or monthly budgets per project or globally.
  Get notified via Slack webhook, Discord webhook, or email (SMTP) when thresholds
  are crossed or anomalous spikes are detected.

- **Optimization Engine** -- Five concrete strategies: model downgrade suggestions,
  caching opportunity detection, batch API usage recommendations, prompt compression
  analysis, and cache prefix optimization. Each strategy reports estimated savings.

- **CLI** -- Full command-line interface via `llm-cost` for starting the proxy, launching
  the dashboard, generating reports, managing budgets and alerts, running the optimizer,
  and exporting data.

- **Multi-Provider Pricing** -- Built-in pricing database covering 30+ models across
  Claude (Opus 4.6, Sonnet 4, Haiku 4.5), GPT (4o, 4.1, o3, o4-mini),
  Gemini (2.5 Pro, 2.5 Flash), Llama 4 (Scout, Maverick), and Mistral Large.

---

## Quick Start

### Installation

```bash
git clone https://github.com/your-org/llm-cost-monitor.git
cd llm-cost-monitor
pip install -e .
```

### Start the proxy

```bash
# Default: listens on port 8080, forwards to real provider endpoints
llm-cost start

# Custom port, custom database path
llm-cost start --port 9090 --db /var/data/costs.db
```

### Point your SDK at the proxy

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8080/openai/v1",
    api_key="sk-..."  # your real key, forwarded transparently
)

# Tag requests by project using the X-Cost-Project header
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
    extra_headers={"X-Cost-Project": "my-project"}
)
```

### Launch the dashboard

```bash
llm-cost dashboard --port 5050
# Open http://localhost:5050 in your browser
```

### Set a budget and add an alert

```bash
llm-cost budget set --name "daily-global" --amount 50.00 --period daily
llm-cost alert add --type slack --webhook-url https://hooks.slack.com/...
```

### Generate a report

```bash
llm-cost report --days 7
llm-cost export --format csv --output costs.csv
```

---

## Architecture

```
+-------------------+       +-------------------+       +-------------------+
|                   |       |                   |       |                   |
|  Your Application +------>+  LLM Cost Monitor +------>+  LLM Provider    |
|                   |       |  (Proxy :8080)    |       |  (OpenAI, etc.)  |
|                   |<------+                   |<------+                   |
+-------------------+       +--------+----------+       +-------------------+
                                     |
                                     | logs every request
                                     v
                            +--------+----------+
                            |                   |
                            |  SQLite Database  |
                            |  (costs.db)       |
                            +--------+----------+
                                     |
                    +----------------+----------------+
                    |                |                 |
                    v                v                 v
            +-------+----+  +-------+------+  +------+-------+
            |            |  |              |  |              |
            | Dashboard  |  |  Alerts      |  |  Optimizer   |
            | (:5050)    |  | (Slack/etc.) |  | (5 strats)   |
            |            |  |              |  |              |
            +------------+  +--------------+  +--------------+
```

### Request Flow

1. Your application sends an API request to the proxy (e.g. `http://localhost:8080/openai/v1/chat/completions`).
2. The proxy extracts the `X-Cost-Project` header (if present), forwards the request
   to the real provider endpoint with the original headers and body.
3. On response, the proxy parses the model name, token usage (input, output, cache tokens),
   and calculates the cost using the built-in pricing database.
4. The request metadata, cost, and latency are written to SQLite.
5. Budget thresholds are checked; if crossed, alerts are dispatched.
6. The response is returned to your application unmodified.

---

## CLI Reference

```
Usage: llm-cost [OPTIONS] COMMAND [ARGS]...

Commands:
  start      Start the transparent proxy server
  dashboard  Launch the web dashboard
  report     Print a cost summary report to the terminal
  budget     Manage budgets (set, list)
  alert      Manage alerts (add, list)
  optimize   Run the optimization engine and print recommendations
  export     Export request logs to CSV, JSON, or Markdown

Options:
  --db PATH   Path to SQLite database [default: costs.db]
  --version   Show version and exit
  --help      Show this message and exit
```

### `llm-cost start`

```
Options:
  --port INTEGER       Port to listen on [default: 8080]
  --host TEXT          Host to bind to [default: 0.0.0.0]
  --db PATH            SQLite database path [default: costs.db]
  --log-level TEXT     Logging level [default: INFO]
```

### `llm-cost dashboard`

```
Options:
  --port INTEGER       Port for the dashboard [default: 5050]
  --db PATH            SQLite database path [default: costs.db]
```

### `llm-cost report`

```
Options:
  --days INTEGER       Number of days to include [default: 7]
  --project TEXT       Filter by project name
  --model TEXT         Filter by model name
```

### `llm-cost budget set`

```
Options:
  --name TEXT          Budget name [required]
  --amount FLOAT       Budget amount in USD [required]
  --period TEXT        Budget period: daily, weekly, monthly [required]
  --project TEXT       Scope to a specific project [optional]
```

### `llm-cost budget list`

Lists all configured budgets with current spend and remaining amount.

### `llm-cost alert add`

```
Options:
  --type TEXT          Alert channel: slack, discord, email [required]
  --webhook-url TEXT   Webhook URL (for slack/discord)
  --email TEXT         Email address (for email alerts)
  --smtp-host TEXT     SMTP host [default: smtp.gmail.com]
  --smtp-port INTEGER  SMTP port [default: 587]
```

### `llm-cost alert list`

Lists all configured alert channels.

### `llm-cost optimize`

Runs five optimization strategies against recent usage data and prints
recommendations with estimated savings.

### `llm-cost export`

```
Options:
  --format TEXT        Output format: csv, json, markdown [default: csv]
  --output PATH        Output file path [default: stdout]
  --days INTEGER       Number of days to include [default: 30]
  --project TEXT       Filter by project name
```

---

## Configuration

All configuration is done via CLI flags or environment variables.

| Environment Variable       | Description                              | Default         |
|---------------------------|------------------------------------------|-----------------|
| `LLM_COST_DB`            | Path to SQLite database                  | `costs.db`      |
| `LLM_COST_PROXY_PORT`    | Proxy server port                        | `8080`          |
| `LLM_COST_DASH_PORT`     | Dashboard port                           | `5050`          |
| `LLM_COST_LOG_LEVEL`     | Logging level                            | `INFO`          |
| `OPENAI_API_BASE`        | Real OpenAI base URL                     | `https://api.openai.com` |
| `ANTHROPIC_API_BASE`     | Real Anthropic base URL                  | `https://api.anthropic.com` |
| `GOOGLE_API_BASE`        | Real Google Gemini base URL              | `https://generativelanguage.googleapis.com` |
| `MISTRAL_API_BASE`       | Real Mistral base URL                    | `https://api.mistral.ai` |
| `SLACK_WEBHOOK_URL`      | Default Slack webhook for alerts         | (none)          |
| `DISCORD_WEBHOOK_URL`    | Default Discord webhook for alerts       | (none)          |
| `SMTP_HOST`              | SMTP host for email alerts               | `smtp.gmail.com`|
| `SMTP_PORT`              | SMTP port                                | `587`           |
| `SMTP_USER`              | SMTP username                            | (none)          |
| `SMTP_PASSWORD`          | SMTP password                            | (none)          |

---

## Supported Models (pricing as of 2026)

| Provider   | Model               | Input ($/1M tokens) | Output ($/1M tokens) |
|-----------|---------------------|---------------------|----------------------|
| Anthropic | Claude Opus 4.6     | 15.00               | 75.00                |
| Anthropic | Claude Sonnet 4     | 3.00                | 15.00                |
| Anthropic | Claude Haiku 4.5    | 0.80                | 4.00                 |
| OpenAI    | GPT-4o              | 2.50                | 10.00                |
| OpenAI    | GPT-4.1             | 2.00                | 8.00                 |
| OpenAI    | o3                  | 10.00               | 40.00                |
| OpenAI    | o4-mini             | 1.10                | 4.40                 |
| Google    | Gemini 2.5 Pro      | 1.25                | 5.00                 |
| Google    | Gemini 2.5 Flash    | 0.15                | 0.60                 |
| Mistral   | Mistral Large       | 2.00                | 6.00                 |
| Meta      | Llama 4 Scout       | 0.17                | 0.36                 |
| Meta      | Llama 4 Maverick    | 0.27                | 0.85                 |

Full pricing table with cache read/write rates available in `src/llm_cost_monitor/pricing.py`.

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Run linter
flake8 src/ tests/
```

---

## License

MIT License. Copyright 2026 David Dabert. See [LICENSE](LICENSE) for details.
