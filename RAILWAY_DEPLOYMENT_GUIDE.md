# Railway Deployment Guide - Cold Email Infrastructure Platform

## Quick Start (5 Minutes)

### 1. Push Your Code to GitHub

```bash
# From your project root
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

### 2. Create Railway Project

1. Go to [railway.app](https://railway.app) and sign in
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Authorize Railway to access your GitHub
5. Select your `cold-email-platform` repository
6. Railway will auto-detect the Dockerfile

### 3. Add PostgreSQL Database

1. In your Railway project, click **"+ New"**
2. Select **"Database"** → **"PostgreSQL"**
3. Railway automatically creates `DATABASE_URL` variable

> **Note:** If you want to keep using Neon, skip this step and manually add your Neon `DATABASE_URL` in variables.

### 4. Add Environment Variables

In Railway dashboard → Your service → **Variables** tab, add:

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | *auto-set by Railway* | Or your Neon URL |
| `CLOUDFLARE_EMAIL` | your-email@example.com | From Cloudflare |
| `CLOUDFLARE_API_KEY` | your-global-api-key | From Cloudflare |
| `CLOUDFLARE_ACCOUNT_ID` | your-account-id | From Cloudflare |
| `MS_CLIENT_ID` | your-azure-app-id | From Azure Portal |
| `ENCRYPTION_KEY` | *generate-fernet-key* | See below |
| `SECRET_KEY` | random-string | Any random string |
| `SCREENSHOT_DIR` | /tmp/screenshots | Keep this value |
| `HEADLESS_MODE` | true | Required for Railway |

**Generate ENCRYPTION_KEY:**
```python
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 5. Deploy!

Railway will automatically build and deploy. Watch the logs for any issues.

---

## File Structure Required

Your repository should look like this:

```
cold-email-platform/
├── Dockerfile              # ← Put the Railway Dockerfile here
├── railway.toml            # ← Railway configuration
├── backend/
│   ├── requirements.txt    # ← Python dependencies
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   └── services/
│   └── alembic/
└── frontend/               # ← Deploy separately or as static export
    ├── package.json
    └── ...
```

---

## Frontend Deployment Options

### Option A: Separate Railway Service (Recommended)

1. Create a second service in Railway
2. Point it to the `frontend/` directory
3. Railway auto-detects Next.js

Add to `frontend/next.config.js`:
```javascript
module.exports = {
  output: 'standalone',
  env: {
    NEXT_PUBLIC_API_URL: process.env.BACKEND_URL || 'http://localhost:8000'
  }
}
```

### Option B: Vercel for Frontend

1. Go to [vercel.com](https://vercel.com)
2. Import your GitHub repo
3. Set root directory to `frontend`
4. Add `NEXT_PUBLIC_API_URL` pointing to your Railway backend

### Option C: Combined Dockerfile (Advanced)

Use a multi-stage Dockerfile that builds both. More complex but single service.

---

## Database Migration

After first deployment, run migrations:

```bash
# Connect to Railway shell
railway run alembic upgrade head

# Or via Railway CLI
railway shell
cd /app
alembic upgrade head
```

---

## Monitoring & Logs

### View Logs
- Railway Dashboard → Your service → **Logs** tab
- Or: `railway logs` via CLI

### Health Check
Your API should respond at:
```
https://your-service.railway.app/health
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Build fails on PowerShell | Check Dockerfile uses Debian 12 packages |
| Chrome crashes | Ensure `HEADLESS_MODE=true` |
| DB connection timeout | Check `DATABASE_URL` format includes `?sslmode=require` for Neon |
| Module not found | Verify `requirements.txt` has all packages |

---

## Scaling (When Ready)

Railway Pro plan allows:
- Multiple replicas
- More memory/CPU
- Custom domains
- Team access

For 300 tenants running in parallel, you may need:
- 2GB+ RAM
- Consider background job queue (Celery + Redis)

---

## Cost Estimate

| Component | Est. Monthly Cost |
|-----------|-------------------|
| Railway Hobby | $5/month + usage |
| Railway Pro | $20/month + usage |
| PostgreSQL | Included in usage |
| Neon (if separate) | Free tier or $19/mo |

---

## Quick Commands

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to existing project
railway link

# Deploy
railway up

# View logs
railway logs

# Open shell
railway shell

# Run command
railway run python manage.py migrate
```

---

## Checklist Before Deploy

- [ ] Dockerfile is in project root
- [ ] railway.toml is in project root
- [ ] requirements.txt has all dependencies
- [ ] Azure App Registration created (MS_CLIENT_ID ready)
- [ ] Cloudflare credentials ready
- [ ] Code pushed to GitHub
- [ ] Health endpoint (`/health`) exists in your FastAPI app

---

## Need Help?

1. Check Railway docs: https://docs.railway.app
2. Railway Discord for community support
3. Review build logs for specific errors
