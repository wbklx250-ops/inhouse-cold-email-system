# Cold Email Platform - Backend

FastAPI backend for managing cold email infrastructure: domains, tenants, and mailboxes.

## Setup

### Prerequisites
- Python 3.11+
- Neon account (free tier works): https://neon.tech

> **Note**: This project uses **Neon Serverless PostgreSQL** - no local database setup required!

### Installation

1. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy environment file:
```bash
cp .env.example .env
```

4. Configure Neon database:
   - Create a free account at https://neon.tech
   - Create a new project
   - Copy the connection string from the Neon dashboard
   - Update `DATABASE_URL` in `.env`:
   ```bash
   DATABASE_URL=postgresql+asyncpg://username:password@ep-xxxxx.us-east-2.aws.neon.tech/dbname?sslmode=require
   ```
   
   > **Important**: Use `postgresql+asyncpg://` prefix (not `postgresql://`)

## Database Migrations

This project uses **Alembic** for database migrations with async PostgreSQL support.

### Migration Commands

#### Apply all migrations (upgrade to latest):
```bash
cd backend
alembic upgrade head
```

#### Rollback one migration:
```bash
alembic downgrade -1
```

#### Rollback to specific revision:
```bash
alembic downgrade <revision_id>
```

#### Rollback all migrations:
```bash
alembic downgrade base
```

#### View current migration status:
```bash
alembic current
```

#### View migration history:
```bash
alembic history
```

#### Create new migration (after modifying models):
```bash
alembic revision --autogenerate -m "Description of changes"
```

#### Create empty migration (for manual SQL):
```bash
alembic revision -m "Description of changes"
```

### Initial Setup

Run the initial migration to create all tables:
```bash
alembic upgrade head
```

This creates:
- `tenants` table - Microsoft 365 tenant information
- `domains` table - Domain management with Cloudflare integration
- `mailboxes` table - Mailbox credentials and status

## Running the API

### Development:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Documentation

Once running, access:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

## API Endpoints

### Domains (`/api/v1/domains`)
- `GET /` - List all domains
- `POST /` - Add new domain (creates Cloudflare zone)
- `GET /{id}` - Get single domain
- `PATCH /{id}` - Update domain
- `DELETE /{id}` - Soft delete (retire)
- `POST /{id}/confirm-ns` - Confirm nameserver update
- `POST /{id}/create-dns` - Create DNS records
- `GET /{id}/status` - Check domain status

### Tenants (`/api/v1/tenants`)
- `GET /` - List all tenants
- `POST /` - Create/import tenant
- `GET /{id}` - Get single tenant
- `PATCH /{id}` - Update tenant
- `DELETE /{id}` - Soft delete (retire)
- `POST /bulk-import` - Bulk import tenants
- `POST /{id}/link-domain/{domain_id}` - Link domain to tenant

### Mailboxes (`/api/v1/mailboxes`)
- `GET /` - List all mailboxes
- `POST /` - Create single mailbox
- `GET /{id}` - Get single mailbox
- `PATCH /{id}` - Update mailbox
- `DELETE /{id}` - Soft delete (suspend)
- `POST /generate/{tenant_id}` - Generate 50 mailboxes
- `GET /export` - Export credentials as CSV

## Project Structure

```
backend/
├── alembic/              # Database migrations
│   ├── versions/         # Migration files
│   └── env.py           # Alembic configuration
├── app/
│   ├── api/
│   │   ├── deps.py      # Dependencies
│   │   └── routes/      # API endpoints
│   ├── core/
│   │   └── config.py    # Settings
│   ├── db/
│   │   └── session.py   # Database session (Neon-optimized)
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── services/        # External services
│   └── main.py          # FastAPI app
├── alembic.ini
├── requirements.txt
└── .env.example
```

## Neon Database Notes

This project uses **Neon Serverless PostgreSQL** with these optimizations:

- **SSL Required**: Connection string includes `?sslmode=require`
- **Connection Pooling**: Configured for Neon's connection limits
  - `pool_pre_ping=True` - Validates connections before use
  - `pool_size=5` - Base connections (free tier friendly)
  - `max_overflow=10` - Extra connections when needed
  - `pool_recycle=300` - Recycles connections after 5 minutes

### Free Tier Limits
- 0.5 GB storage
- 3,000 compute hours/month
- 10 concurrent connections

For production, consider upgrading to a paid Neon plan.