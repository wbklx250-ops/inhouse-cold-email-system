# Cold Email Platform - Deployment Guide

This guide covers deploying the Cold Email Platform to production.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Database Setup (Neon)](#database-setup-neon)
4. [Local Docker Testing](#local-docker-testing)
5. [Deploy to Railway](#deploy-to-railway)
6. [Deploy to Render](#deploy-to-render)
7. [Deploy Frontend to Vercel](#deploy-frontend-to-vercel-alternative)
8. [Post-Deployment](#post-deployment)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Git** - Version control
- **Docker** (optional) - For local testing
- **Node.js 18+** - For frontend development
- **Python 3.11+** - For backend development
- **Accounts needed:**
  - [Neon](https://neon.tech) - Free serverless PostgreSQL
  - [Cloudflare](https://cloudflare.com) - DNS management (you should already have this)
  - [Azure Portal](https://portal.azure.com) - For Microsoft 365 integration
  - Deployment platform: [Railway](https://railway.app), [Render](https://render.com), or [Vercel](https://vercel.com)

---

## Environment Setup

### 1. Copy the Environment Template

```bash
cp .env.production.example .env.production
```

### 2. Generate a Secret Key

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output to `SECRET_KEY` in your `.env.production`.

### 3. Configure All Variables

Edit `.env.production` and fill in all required values (see below for service-specific setup).

---

## Database Setup (Neon)

> **Note:** This project uses Neon cloud database - no local PostgreSQL setup needed!

### 1. Create Neon Account

1. Go to [neon.tech](https://neon.tech) and sign up (free tier available)
2. Create a new project (e.g., "cold-email-platform")
3. Select your preferred region (choose closest to your deployment)

### 2. Get Connection String

1. In your Neon dashboard, go to your project
2. Click "Connection Details"
3. Copy the connection string
4. **Important:** Change the driver prefix for async support:
   - Change `postgresql://` to `postgresql+asyncpg://`

Example:
```
# Neon provides:
postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/dbname?sslmode=require

# Use this format:
postgresql+asyncpg://user:pass@ep-xxx.us-east-2.aws.neon.tech/dbname?sslmode=require
```

### 3. Run Database Migrations

From your local machine (with the backend virtual environment activated):

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
```

---

## Local Docker Testing

Test your production setup locally before deploying.

### 1. Build and Run

```bash
# From the cold-email-platform directory
docker-compose -f docker-compose.prod.yml up --build
```

### 2. Verify Services

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### 3. Stop Services

```bash
docker-compose -f docker-compose.prod.yml down
```

---

## Deploy to Railway

[Railway](https://railway.app) offers easy Docker deployment with a generous free tier.

### 1. Create Railway Account

Sign up at [railway.app](https://railway.app) using GitHub.

### 2. Deploy Backend

1. Click "New Project" → "Deploy from GitHub repo"
2. Select your repository
3. Configure the service:
   - **Root Directory:** `cold-email-platform/backend`
   - **Build Command:** (uses Dockerfile automatically)
4. Add environment variables in Railway dashboard:
   - `DATABASE_URL`
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `AZURE_CLIENT_ID`
   - `SECRET_KEY`
   - `CORS_ORIGINS` (set to your frontend URL)
5. Generate a domain or add custom domain

### 3. Deploy Frontend

1. Add another service to the same project
2. Configure:
   - **Root Directory:** `cold-email-platform/frontend`
   - **Build Command:** (uses Dockerfile automatically)
3. Add environment variables:
   - `NEXT_PUBLIC_API_URL` (your backend Railway URL)
4. Generate domain

### 4. Get Your URLs

Railway provides URLs like:
- Backend: `https://cold-email-backend-production.up.railway.app`
- Frontend: `https://cold-email-frontend-production.up.railway.app`

---

## Deploy to Render

[Render](https://render.com) is another excellent option with Docker support.

### 1. Create Render Account

Sign up at [render.com](https://render.com).

### 2. Deploy Backend

1. Click "New" → "Web Service"
2. Connect your GitHub repository
3. Configure:
   - **Name:** cold-email-backend
   - **Root Directory:** cold-email-platform/backend
   - **Environment:** Docker
   - **Instance Type:** Free (or Starter for production)
4. Add environment variables (same as Railway)
5. Click "Create Web Service"

### 3. Deploy Frontend

1. Click "New" → "Web Service"
2. Configure:
   - **Name:** cold-email-frontend
   - **Root Directory:** cold-email-platform/frontend
   - **Environment:** Docker
3. Add environment variable:
   - `NEXT_PUBLIC_API_URL` (your backend Render URL)

### render.yaml (Optional)

For infrastructure-as-code, create `render.yaml` in root:

```yaml
services:
  - type: web
    name: cold-email-backend
    env: docker
    rootDir: cold-email-platform/backend
    envVars:
      - key: DATABASE_URL
        sync: false
      - key: CLOUDFLARE_API_TOKEN
        sync: false
      - key: SECRET_KEY
        generateValue: true
    healthCheckPath: /health

  - type: web
    name: cold-email-frontend
    env: docker
    rootDir: cold-email-platform/frontend
    envVars:
      - key: NEXT_PUBLIC_API_URL
        sync: false
```

---

## Deploy Frontend to Vercel (Alternative)

[Vercel](https://vercel.com) is optimized for Next.js and offers the best performance.

> **Note:** If using Vercel for frontend, deploy only the backend to Railway/Render.

### 1. Create Vercel Account

Sign up at [vercel.com](https://vercel.com) using GitHub.

### 2. Import Project

1. Click "Add New" → "Project"
2. Import your GitHub repository
3. Configure:
   - **Framework Preset:** Next.js
   - **Root Directory:** `cold-email-platform/frontend`

### 3. Configure Environment Variables

Add in Vercel dashboard:
- `NEXT_PUBLIC_API_URL` = Your backend URL (Railway/Render)

### 4. Deploy

Click "Deploy" - Vercel handles everything automatically!

### Benefits of Vercel for Frontend

- Automatic HTTPS
- Global CDN
- Automatic preview deployments for PRs
- Zero-config for Next.js
- Excellent free tier

---

## Post-Deployment

### 1. Update CORS Origins

After deployment, update your backend's `CORS_ORIGINS` environment variable to include your frontend domain(s):

```
CORS_ORIGINS=https://your-frontend.vercel.app,https://yourdomain.com
```

### 2. Configure Custom Domains (Optional)

Both Railway and Render support custom domains:
1. Add your domain in the dashboard
2. Update DNS records as instructed
3. SSL is automatic

### 3. Run Database Migrations

If not done during build, run migrations:

```bash
# Railway - use Railway CLI
railway run alembic upgrade head

# Render - use Shell tab in dashboard
alembic upgrade head
```

### 4. Verify Health Endpoints

- Backend: `https://your-backend-url/health`
- API Docs: `https://your-backend-url/docs`

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Failed

- Verify `DATABASE_URL` uses `postgresql+asyncpg://` prefix
- Ensure `?sslmode=require` is at the end
- Check Neon dashboard for connection issues

#### 2. CORS Errors

- Update `CORS_ORIGINS` to include your frontend URL
- Don't include trailing slashes
- Restart backend after changes

#### 3. Frontend Can't Reach Backend

- Verify `NEXT_PUBLIC_API_URL` is correct
- Ensure backend is running and healthy
- Check browser console for specific errors

#### 4. PowerShell Scripts Not Working

- The backend Dockerfile includes PowerShell Core
- Ensure M365 credentials are properly configured
- Check logs for specific PowerShell errors

#### 5. Build Failures

**Backend:**
```bash
# Test locally
cd backend
docker build -t test-backend .
```

**Frontend:**
```bash
# Test locally
cd frontend
docker build -t test-frontend --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 .
```

### Viewing Logs

**Railway:**
```bash
railway logs
```

**Render:**
- View in dashboard under "Logs" tab

**Docker (local):**
```bash
docker-compose -f docker-compose.prod.yml logs -f
```

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                     PRODUCTION SETUP                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌──────────────┐       ┌──────────────┐                  │
│   │   Frontend   │       │   Backend    │                  │
│   │   (Next.js)  │──────▶│  (FastAPI)   │                  │
│   │              │       │              │                  │
│   │ Vercel/Rail  │       │ Railway/     │                  │
│   │ way/Render   │       │ Render       │                  │
│   └──────────────┘       └──────┬───────┘                  │
│                                 │                          │
│                    ┌────────────┼────────────┐             │
│                    │            │            │             │
│                    ▼            ▼            ▼             │
│            ┌───────────┐ ┌───────────┐ ┌───────────┐      │
│            │   Neon    │ │ Cloudflare│ │  Azure AD │      │
│            │ PostgreSQL│ │    DNS    │ │    M365   │      │
│            └───────────┘ └───────────┘ └───────────┘      │
│                                                             │
│   No local PostgreSQL needed - Neon handles everything!    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Cost Estimation

| Service | Free Tier | Paid |
|---------|-----------|------|
| **Neon** | 0.5 GB storage, 1 project | From $19/mo |
| **Railway** | $5 credit/month | From $5/mo |
| **Render** | 750 hours/month | From $7/mo |
| **Vercel** | 100 GB bandwidth | From $20/mo |

For small to medium usage, you can run entirely on free tiers!

---

## Security Checklist

- [ ] All secrets stored as environment variables (never in code)
- [ ] `SECRET_KEY` is randomly generated and unique
- [ ] `CORS_ORIGINS` only includes your domains
- [ ] Database connection uses SSL (`sslmode=require`)
- [ ] API endpoints require authentication where needed
- [ ] Regular backups enabled on Neon
- [ ] HTTPS enforced on all endpoints

---

## Need Help?

- **Neon Docs:** https://neon.tech/docs
- **Railway Docs:** https://docs.railway.app
- **Render Docs:** https://render.com/docs
- **Vercel Docs:** https://vercel.com/docs
- **Next.js Deployment:** https://nextjs.org/docs/deployment
- **FastAPI Deployment:** https://fastapi.tiangolo.com/deployment/