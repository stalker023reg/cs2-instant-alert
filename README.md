# CS2 Instant Alert

Real-time monitoring system for Counter-Strike 2 updates. Detects new builds within seconds of release and delivers alerts with patch notes via Telegram.

## Features

- **Real-time Steam monitoring** — connects to Steam network via PICS protocol for instant build change detection (every 5s)
- **Multi-source validation** — cross-checks PICS data against Steam Store API and Web API to eliminate false positives
- **Real datamining via GitHub** — tracks `SteamTracking/GameTracking-CS2` to extract exact `PatchVersion` from `steam.inf` and inspect actual file diffs (`convars`, schemas, Panorama UI, localization)
- **AI-powered analysis (Gemini Flash)** — generates structured TL;DR summaries for official patch notes and analyzes silent updates without hallucination
- **Two-stage alert pipeline** — delivers an instant alert at T+0 with clean player depots, then edits the message in-place once datamine or official notes are ready (with a 20m fallback)
- **Clean depot filtering** — strips dedicated server (`732`, `2347773`) and macOS (`735`, `2347779`) noise, collapsing technical depots
- **Critical notification retry** — unacknowledged critical alerts are re-sent on an exponential backoff schedule until the user confirms receipt
- **Self-healing watchdog & auto-reconnect** — monitors all subsystems (DB, Redis, Steam, Telegram, scheduler), auto-reconnects to Steam with exponential backoff, and triggers restart on sustained failure
- **Interactive Telegram bot** — interactive bot with `/status`, `/subscribe`, `/settings` commands and inline buttons

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Application                           │
├──────────┬──────────┬───────────┬───────────┬─────────────┬────────────┤
│  Steam   │ Event    │ Notifi-   │ Scheduler │ Telegram    │ AI / Data- │
│  Client  │ Bus      │ cation    │           │ Bot         │ mine Engine│
│ (gevent) │          │ Engine    │           │             │            │
├──────────┴──────────┴───────────┴───────────┴─────────────┴────────────┤
│                    PostgreSQL (Supabase) + Redis                       │
└────────────────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Description |
|-----------|-------------|
| `AsyncSteamClient` | Persistent connection to Steam network via gevent with in-thread auto-reconnect and PICS product info tracking |
| `MultiSourceMonitor` | Orchestrates PICS, Store, and WebAPI monitors to validate updates |
| `EventBus` | Async pub/sub system decoupling detection from notification delivery |
| `NotificationDispatcher` | Delivers formatted alerts to all subscribers (Telegram, Pushover) |
| `depot_filter` | Filters out dedicated server, macOS, and technical depots for a clean player-facing alert |
| `GitHubDatamineFetcher` | Polls `SteamTracking/GameTracking-CS2` commits for real file changes and `steam.inf` patch version |
| `SteamNewsFetcher` | Queries official Steam News API within a flexible release window |
| `GeminiAnalysisService` | Google Gemini Flash integration with strict anti-hallucination rules for patch notes & silent updates |
| `PatchNotesService` | Orchestrates 2-stage polling (every 45s up to 20m) and in-place alert editing |
| `SilentWatchdogService` | System health monitor checking all components every 60s with automatic self-healing |
| `HealthService` | Readiness and liveness endpoints for all 7 subsystems |

### Update Flow

1. **Detection (T+0):** `AsyncSteamClient` detects a PICS product info change for CS2 (`app_id=730`).
2. **Depot Filtering:** `depot_filter` strips server/macOS depots and formats clean client depot names.
3. **Stage 1 Alert:** Instant Telegram alert sent with build ID and waiting placeholder (`⏳ Анализируем файлы обновления...`).
4. **Datamining & News Polling:** Background worker polls Steam News API and GitHub (`SteamTracking/GameTracking-CS2`) every 45s.
5. **AI Analysis:** If patch notes exist, Gemini Flash summarizes key player changes. If it is a silent update, Gemini analyzes datamined file diffs (`convars`, Panorama, items) under `🕵️ Не вошло в патчноут (Датамайнинг)`.
6. **Stage 2 In-Place Edit:** Original Telegram alert is edited with the exact game patch version and structured analysis.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Runtime | Python 3.11+ |
| Web Framework | FastAPI + Uvicorn |
| Database | PostgreSQL (async via SQLAlchemy + asyncpg / Supabase) |
| Migrations | Alembic |
| Cache | Redis (Upstash) |
| Steam | `steam[client]` library (PICS protocol, gevent) |
| Telegram | `python-telegram-bot` v21 |
| AI Analysis | Google Gemini 2.0 Flash (`google-genai`) |
| Datamining | GitHub REST API (`httpx`) |
| Official News | Steam Web API (`ISteamNews`) |
| DI Container | `dependency-injector` |
| Logging | `structlog` (JSON in production) |
| Hosting | Fly.io (Docker) |

## Project Structure

```
app/
├── api/              # FastAPI routes and dependencies
├── bot/              # Telegram bot handlers and middleware
├── core/             # Config, container, logging, security
├── database/         # Session management, Alembic migrations
├── events/           # Event bus and event type definitions
├── models/           # SQLAlchemy ORM models
├── notifications/    # Multi-channel notification engine & formatters
├── repositories/     # Data access layer (Repository pattern)
├── scheduler/        # Monitoring orchestrator and tasks
├── schemas/          # Pydantic request/response schemas
├── services/         # Business logic services
│   ├── gemini_analysis_service.py # Strict AI analysis & HTML sanitization
│   ├── github_datamine_fetcher.py # SteamTracking datamining & steam.inf parser
│   ├── health_service.py          # 7-component readiness checks
│   ├── patch_notes_service.py     # 2-stage polling & in-place message editing
│   ├── steam_news_fetcher.py      # Steam News API client
│   ├── update_service.py          # Update lifecycle orchestration
│   └── watchdog.py                # System resilience & auto-restart
├── steam/            # Steam client, monitors, types
└── utils/            # Depot filtering, datetime utils, retry helpers
config/
└── games/
    └── cs2.toml      # Game-specific monitoring configuration
```

## Changelog

### v1.1.0
- **Feature (Datamining):** Integrated GitHub API polling (`SteamTracking/GameTracking-CS2`) to inspect real file diffs (convars, schema, Panorama UI, localization) and parse `PatchVersion` directly from `steam.inf`.
- **Feature (AI Analysis):** Integrated Google Gemini Flash with strict anti-hallucination prompt rules to generate structured insights and categorize undocumented datamined changes.
- **Feature (2-Stage Alerts):** Instant T+0 alert with filtered client depots and status placeholder, followed by seamless in-place editing as soon as analysis is complete (or 20-min timeout fallback).
- **Feature (Depot Filtering):** Added intelligent depot filtering that removes dedicated server (`732`, `2347773`) and macOS (`735`, `2347779`) depots, collapsing unmapped technical depots.
- **Improvement (Formatting):** Player-centric layout removing internal criticality labels and server warnings.
- **Fix (Steam Resilience):** Added gevent timeout guards, in-thread exponential backoff, and automatic watchdog reconnection to prevent crash loops during Steam network downtime.

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
