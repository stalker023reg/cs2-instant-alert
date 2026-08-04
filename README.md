# CS2 Instant Alert

Real-time monitoring system for Counter-Strike 2 updates. Detects new builds within seconds of release and delivers alerts with patch notes via Telegram.

## Features

- **Real-time Steam monitoring** — connects to Steam network via PICS protocol for instant build change detection
- **Multi-source validation** — cross-checks PICS data against Steam Store API and Web API to eliminate false positives
- **Automatic patch notes** — polls Steam News API after update detection, translates via DeepL, and edits the original alert message in-place
- **Critical notification retry** — unacknowledged critical alerts are re-sent on an exponential backoff schedule until the user confirms receipt
- **Race Mode** — automatically increases polling frequency for 30 minutes after an update is detected (configurable)
- **Self-healing watchdog** — monitors all subsystems (DB, Redis, Steam, Telegram, scheduler) and triggers container restart if any component is unresponsive for 5+ minutes
- **Startup recovery** — on boot, resumes patch note polling for any recent updates that were interrupted
- **Telegram bot** — interactive bot with `/status`, `/subscribe`, `/settings` commands and inline acknowledgement buttons

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Application                   │
├──────────┬──────────┬───────────┬───────────┬───────────┤
│  Steam   │ Event    │ Notifi-   │ Scheduler │ Telegram  │
│  Client  │ Bus      │ cation    │           │ Bot       │
│ (gevent) │          │ Engine    │           │           │
├──────────┴──────────┴───────────┴───────────┴───────────┤
│                  PostgreSQL + Redis                     │
└─────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Description |
|-----------|-------------|
| `AsyncSteamClient` | Persistent connection to Steam network via gevent. Handles login, reconnection with exponential backoff, and PICS product info tracking |
| `MultiSourceMonitor` | Orchestrates PICS, Store, and WebAPI monitors. Validates changes through multiple sources before emitting events |
| `EventBus` | Async pub/sub system. Decouples detection from processing — subscribers react to `AppInfoChangedEvent` and `UpdateDetectedEvent` |
| `NotificationDispatcher` | Delivers alerts to all subscribed users. Supports channel escalation (Telegram → Pushover) on failure |
| `RetryEngine` | Background worker that retries failed critical notifications until acknowledged |
| `PatchNotesService` | Polls Steam News API for up to 30 minutes after update detection. Edits delivered messages with formatted, translated patch notes |
| `SilentWatchdogService` | System-wide health monitor. Checks all components every 60s, triggers `os._exit(1)` after 5 min of sustained failure to let the container orchestrator restart the process |
| `HealthService` | Provides health status for all subsystems (DB, Redis, Steam, Telegram, EventBus, Scheduler) |

### Update Flow

1. `AsyncSteamClient` detects a PICS product info change for app 730 (CS2)
2. `MultiSourceMonitor` validates the change against Store/WebAPI
3. `UpdateService` persists the update record with a timeline of processing stages
4. `NotificationDispatcher` sends formatted Telegram alerts to all subscribers
5. `PatchNotesService` begins polling for official patch notes
6. When found, patch notes are translated to Russian and the original message is edited in-place

## Tech Stack

| Layer | Technology |
|-------|------------|
| Runtime | Python 3.12 |
| Web Framework | FastAPI + Uvicorn |
| Database | PostgreSQL (async via SQLAlchemy + asyncpg) |
| Migrations | Alembic |
| Cache | Redis (Upstash) |
| Steam | `steam[client]` library (PICS protocol, gevent) |
| Telegram | `python-telegram-bot` v21 |
| Translation | DeepL API |
| DI Container | `dependency-injector` |
| Logging | `structlog` (JSON in production) |
| Hosting | Fly.io (Docker) |

## Project Structure

```
app/
├── api/              # FastAPI routes and dependencies
│   ├── app.py        # Application factory with lifespan
│   └── routes/       # Health, ready endpoints
├── bot/              # Telegram bot handlers and middleware
├── core/             # Config, container, logging, security
├── database/         # Session management, Alembic migrations
├── events/           # Event bus and event type definitions
├── models/           # SQLAlchemy ORM models
├── notifications/    # Multi-channel notification engine
│   ├── channels/     # Telegram, Pushover channel implementations
│   ├── dispatcher.py # Notification routing and delivery
│   └── retry_engine.py
├── repositories/     # Data access layer (Repository pattern)
├── scheduler/        # Monitoring orchestrator and tasks
├── schemas/          # Pydantic request/response schemas
├── services/         # Business logic services
│   ├── health_service.py
│   ├── patch_notes_service.py
│   ├── update_service.py
│   └── watchdog.py
├── steam/            # Steam client, monitors, types
│   ├── client.py     # AsyncSteamClient (gevent bridge)
│   ├── pics_monitor.py
│   ├── store_monitor.py
│   ├── webapi_monitor.py
│   └── multi_source_monitor.py
└── utils/            # Formatting, retry helpers, datetime utils
config/
├── games/
│   └── cs2.toml      # Game-specific monitoring configuration
```

## Changelog

### v1.0.3
- **Fix:** Rewrote DeepL post-translation cleanup with regex to aggressively remove stray newlines before/after parentheses and inside `<a>` link tags. This fully resolves the issue where translated patch note links had misplaced line breaks around brackets.
- **Fix:** Bot no longer sends any unsolicited replies to unknown messages. Previously it would respond with a hint text and admin dashboard on every unrecognized message — now it stays completely silent and only reacts to `/start` and inline button callbacks.

### v1.0.2
- **Fix:** Restricted catch-all message handlers (which reply with standard text) to private chats only. This prevents the bot from spamming responses to every user message in group chats.

### v1.0.1
- **Fix:** Fixed an issue where patch note subheadings (e.g. Map names) would incorrectly merge into the same line as the following list item.
- **Fix:** Added a cleanup step to the translation service to fix a bug where DeepL's HTML tag handling would inappropriately inject newlines before closing parentheses in patch note links.

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis (optional, used for caching)

### Local Development

1. Clone the repository:
   ```bash
   git clone https://github.com/stalker023reg/cs2-instant-alert.git
   cd cs2-instant-alert
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate     # Windows
   ```

3. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

4. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. Run database migrations:
   ```bash
   python -m alembic upgrade head
   ```

6. Start the application:
   ```bash
   python -m app.main
   ```

### Docker

```bash
docker build -t cs2-instant-alert .
docker run --env-file .env -p 8000:8000 cs2-instant-alert
```

### Fly.io Deployment

```bash
fly launch
fly secrets set DATABASE_URL="..." TELEGRAM_BOT_TOKEN="..." STEAM_API_KEY="..."
fly deploy
```

## Configuration

All configuration is done via environment variables. See [`.env.example`](.env.example) for the full list.

### Key Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_HOST` / `DATABASE_URL` | PostgreSQL connection |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `TELEGRAM_ADMIN_IDS` | JSON array of admin Telegram user IDs |
| `STEAM_API_KEY` | Steam Web API key |
| `DEEPL_API_KEY` | DeepL API key for patch note translation |
| `STEAM_CHECK_INTERVAL_SECONDS` | Base polling interval (default: 5s) |
| `STEAM_RACE_MODE_INTERVAL_SECONDS` | Polling interval during Race Mode (default: 2s) |
| `ENCRYPTION_KEY` | Fernet key for encrypting stored credentials |

### Game Configuration

Games are configured via TOML files in `config/games/`. See [`config/games/cs2.toml`](config/games/cs2.toml) for the CS2 configuration including monitored branches, depot IDs, and patch note sources.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Liveness probe (always returns 200) |
| `/api/ready` | GET | Readiness probe with per-component status |

## License

MIT
