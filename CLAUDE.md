# CLAUDE.md

## Project Overview

Cold Email Infrastructure Platform - a full-stack application for automating Microsoft 365 tenant setup, domain configuration, and mailbox provisioning. The system orchestrates an 8-step setup wizard that automates Cloudflare DNS, M365 domain verification, Exchange Online mailbox creation, and SMTP authentication configuration.

This is **infrastructure provisioning software** — it prepares email sending infrastructure but does not send emails itself. External sequencer tools (e.g., Lemlist, Apollo) consume the exported mailbox credentials.

## Architecture

**Monorepo with two deployable units:**

```
/
├── backend/          # Python FastAPI API server
├── frontend/         # Next.js React web UI
├── Dockerfile        # Production backend image
├── docker-compose.yml
└── docker-compose.prod.yml
```

- **Backend**: FastAPI (Python 3.11+), async-first, PostgreSQL via SQLAlchemy 2.0 + asyncpg
- **Frontend**: Next.js 16 with App Router, React 19, TypeScript 5, Tailwind CSS 4
- **Database**: Neon Serverless PostgreSQL (cloud-hosted, SSL required)
- **Deployment**: Railway (Docker-based), health check at `/health`

## Tech Stack

### Backend
- FastAPI 0.104+ with Uvicorn
- SQLAlchemy 2.0+ (async ORM with `asyncpg` driver)
- Alembic for database migrations (17 migrations)
- Pydantic 2.5+ / pydantic-settings for config and validation
- Selenium 4.15+ for M365 browser automation
- PowerShell Core for Exchange Online management
- APScheduler for background jobs
- httpx / aiohttp for external HTTP calls
- pyotp + pyzbar for MFA automation

### Frontend
- Next.js 16.1.2 with App Router (`app/` directory)
- React 19.2.3
- TypeScript 5 (strict mode)
- Tailwind CSS 4 with PostCSS
- Custom fetch-based API client (`frontend/lib/api.ts`)

## Development Setup

### Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in required values
alembic upgrade head  # Run migrations
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev  # Starts on localhost:3000
```

### Environment Variables
- Backend: `backend/.env` (loaded by pydantic-settings)
- Frontend: `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`)
- Required secrets: `DATABASE_URL`, `SECRET_KEY`, `CLOUDFLARE_API_KEY`, `CLOUDFLARE_EMAIL`, `CLOUDFLARE_ACCOUNT_ID`, `MS_CLIENT_ID`, `ENCRYPTION_KEY`
- Never commit `.env` files (covered by `.gitignore`)

## Running Tests

```bash
cd backend
pytest                     # Run all tests
pytest -v --tb=short       # Verbose with short tracebacks (default via pytest.ini)
pytest tests/test_wizard_batches.py  # Run specific test file
```

- Tests use **in-memory SQLite** via `aiosqlite` (not PostgreSQL)
- `conftest.py` compiles PostgreSQL types (UUID, JSONB) to SQLite equivalents
- `asyncio_mode = auto` in `pytest.ini` — no need for `@pytest.mark.asyncio`
- Test client uses FastAPI's `TestClient` with dependency overrides for DB session

## Project Structure

### Backend (`backend/app/`)

```
app/
├── main.py              # FastAPI app, lifespan, CORS, router registration
├── core/
│   └── config.py        # Settings via pydantic-settings (env vars)
├── db/
│   └── session.py       # Async/sync engine, session factories, retry logic
├── models/              # SQLAlchemy ORM models
│   ├── base.py          # Base + TimestampUUIDMixin (UUID PK, created/updated_at)
│   ├── domain.py        # Domain (Cloudflare zones, DNS, verification)
│   ├── tenant.py        # Tenant (M365 credentials, step tracking)
│   ├── mailbox.py       # Mailbox (email, passwords, provisioning state)
│   └── batch.py         # SetupBatch (groups domains/tenants/mailboxes)
├── schemas/             # Pydantic request/response schemas
├── api/
│   ├── deps.py          # Dependency injection (get_db_session)
│   └── routes/
│       ├── domains.py   # /api/v1/domains — CRUD, zones, DNS, bulk import
│       ├── tenants.py   # /api/v1/tenants — CRUD, bulk import, domain linking
│       ├── mailboxes.py # /api/v1/mailboxes — CRUD, generation, CSV export
│       ├── wizard.py    # /api/v1/wizard — Multi-step setup orchestration (LARGEST)
│       ├── stats.py     # /api/v1/stats — Aggregated statistics
│       ├── webhooks.py  # /api/v1/webhooks — Azure Automation callbacks
│       └── step8.py     # /api/v1/step8 — Security defaults management
└── services/            # Business logic layer (largest code area)
    ├── cloudflare.py        # Cloudflare API (zones, DNS records, CNAMEs)
    ├── tenant_automation.py # Parallel tenant automation orchestrator (LARGEST)
    ├── azure_step6.py       # M365 mailbox creation via Selenium + PowerShell
    ├── powershell_exchange.py # Exchange Online PowerShell commands
    ├── step8_security_defaults.py # Security defaults disable automation
    ├── m365_setup.py        # M365 domain verification
    ├── mailbox_setup.py     # M365 mailbox provisioning
    ├── orchestrator.py      # Step orchestration logic
    ├── graph_api.py         # Microsoft Graph API wrapper
    ├── graph_auth.py        # OAuth consent automation
    ├── graph_domain.py      # Graph API domain operations
    ├── exchange_api.py      # Exchange Admin REST API
    ├── email_generator.py   # Email address pattern generation
    ├── tenant_import.py     # CSV parsing for tenant import
    ├── background_jobs.py   # APScheduler (DKIM retry jobs)
    └── selenium/            # Browser automation helpers
        ├── admin_portal.py      # M365 Admin Center navigation
        └── step5_standalone.py  # Standalone domain verification
```

### Frontend (`frontend/`)

```
frontend/
├── app/                    # Next.js App Router pages
│   ├── page.tsx           # Dashboard
│   ├── layout.tsx         # Root layout
│   ├── setup/             # Setup wizard routes
│   │   ├── page.tsx       # Batch list/create
│   │   └── [batchId]/page.tsx  # Batch detail with step progress
│   ├── tenants/           # Tenant CRUD pages
│   ├── domains/           # Domain CRUD pages
│   └── mailboxes/         # Mailbox list/detail pages
├── components/
│   ├── layout/            # AppLayout, Header, Sidebar
│   ├── ui/                # Card, Toast, Badge, Modal
│   ├── wizard/            # Step 1-8 wizard components
│   ├── tenants/           # TenantTable, BulkImportModal
│   ├── domains/           # Domain components
│   └── mailboxes/         # Mailbox components
└── lib/
    └── api.ts             # Typed API client (all types + fetch functions)
```

## Key Concepts

### Setup Wizard (8 Steps)
1. **Domain Import** — CSV import, Cloudflare zone creation
2. **Zone Activation** — Cloudflare zone provisioning, Phase 1 DNS (CNAME + DMARC)
3. **NS Propagation & Redirects** — DNS propagation checks, redirect rules
4. **Tenant Linking** — Link M365 tenants to domains, import via CSV
5. **M365 Verification & DKIM** — Browser automation for domain verification, DKIM enable
6. **Mailbox Creation** — Generate mailboxes, create in Exchange, configure accounts
7. **Sequencer Prep (SMTP Auth)** — Enable SMTP client authentication
8. **Security Defaults** — Disable Azure AD security defaults

### Database Models
All models inherit `TimestampUUIDMixin` (UUID primary key, `created_at`, `updated_at`).

Core entities:
- **SetupBatch** → groups domains, tenants, and mailboxes into a setup session
- **Domain** → tracks Cloudflare zone, DNS records, verification, DKIM
- **Tenant** → M365 tenant with admin credentials, step completion tracking
- **Mailbox** → email account with provisioning state and warmup tracking

Status enums are PostgreSQL native types (`DomainStatus`, `TenantStatus`, `MailboxStatus`, `WarmupStage`, `BatchStatus`).

### Database Connection
- Neon Serverless PostgreSQL with SSL required
- `asyncpg` driver (async), `psycopg2` for sync operations (Selenium workers)
- `RetryableSession` wrapper for auto-retry on transient connection drops
- Pool: `pool_size=20`, `max_overflow=30`, `pool_recycle=1800`

## Code Conventions

### Backend (Python)
- **Async-first**: All route handlers and DB operations use `async/await`
- **Type hints**: Use Python 3.10+ syntax (`str | None`, `list[str]`)
- **Config**: Environment variables via `pydantic-settings`, accessed through `get_settings()`
- **DB sessions**: Injected via `Depends(get_db_session)` in route handlers
- **Models**: SQLAlchemy 2.0 mapped columns style (`Mapped[str]`, `mapped_column()`)
- **Schemas**: Pydantic v2 models for request/response validation
- **Logging**: `logging.getLogger(__name__)` — logs to both file and stdout
- **Error handling**: FastAPI `HTTPException` with appropriate status codes
- **Imports**: Standard library, then third-party, then local (`app.xxx`)

### Frontend (TypeScript)
- **App Router**: Pages in `app/`, components in `components/`
- **API calls**: Use typed functions from `lib/api.ts` (never raw `fetch` in components)
- **Types**: All API types defined in `lib/api.ts` alongside their fetch functions
- **State**: React hooks (`useState`, `useEffect`) — no external state management
- **Styling**: Tailwind CSS utility classes
- **Path aliases**: `@/*` maps to project root in `tsconfig.json`

### General
- **No linter configured** (no ESLint, Ruff, or similar)
- **No formatter configured** (no Prettier or Black)
- **No CI/CD pipeline** — deployment is manual via Railway
- **Soft deletes**: Entities set status to `retired`/`error` rather than DB deletion
- **Batch-oriented**: Most operations work on groups via `SetupBatch`

## API Routes Summary

| Prefix | Router | Purpose |
|--------|--------|---------|
| `/api/v1/domains` | `domains.py` | Domain CRUD, Cloudflare zone/DNS management |
| `/api/v1/tenants` | `tenants.py` | Tenant CRUD, bulk import, domain linking |
| `/api/v1/mailboxes` | `mailboxes.py` | Mailbox CRUD, generation, CSV export |
| `/api/v1/wizard` | `wizard.py` | Setup wizard orchestration (steps 1-8) |
| `/api/v1/stats` | `stats.py` | Dashboard statistics |
| `/api/v1/webhooks` | `webhooks.py` | Azure Automation callbacks |
| `/api/v1/step8` | `step8.py` | Security defaults management |
| `/health` | `main.py` | Health check (used by Railway) |
| `/health/db` | `main.py` | DB connectivity + record counts |
| `/docs` | FastAPI | Swagger UI |

## Database Migrations

```bash
cd backend
alembic upgrade head          # Apply all migrations
alembic revision -m "desc"    # Create new migration (manual)
alembic revision --autogenerate -m "desc"  # Auto-detect model changes
alembic downgrade -1           # Rollback one migration
alembic history                # Show migration history
```

Migrations are in `backend/alembic/versions/` (001 through 017).

## External Service Integrations

- **Cloudflare**: Zone creation, DNS record management (MX, SPF, DMARC, DKIM CNAMEs, redirects)
- **Microsoft Graph API**: Domain operations, user management, device code auth flow
- **Exchange Online**: Mailbox creation, SMTP auth, delegation (via PowerShell and REST API)
- **Azure AD**: OAuth consent, security defaults, tenant management
- **Azure Automation**: Webhook-triggered PowerShell runbooks

## Deployment

- **Platform**: Railway (primary), Render/Vercel (alternatives)
- **Backend**: Docker image (Python 3.11-slim-bookworm + Chromium + PowerShell Core)
- **Frontend**: Next.js build, deployable to Vercel or as Docker container
- **Database**: Neon PostgreSQL (cloud, no local container needed)
- **Config**: `railway.toml` — health check at `/health`, 300s timeout, restart on failure

## Important Notes

- `wizard.py` is the largest route file (~180KB) — contains the full step orchestration logic
- `tenant_automation.py` is the largest service (~117KB) — handles parallel tenant operations
- Browser automation (Selenium) is RAM-intensive: `max_parallel_browsers=2` (~600MB for 2 Chrome instances)
- Headless mode (`step5_headless`, `step6_headless`) must be `true` in production (no display server)
- The `encryption_key` setting uses Fernet symmetric encryption for sensitive credential storage
- Tests use SQLite in-memory — some PostgreSQL-specific behaviors may not be caught in tests
