# =================================================================
# Backend Dockerfile - Cold Email Platform
# =================================================================
#
# Python 3.11 with PowerShell Core for Microsoft 365 integration
#
# Build:
#   docker build -t cold-email-backend .
#
# Run:
#   docker run -p 8000:8000 --env-file .env cold-email-backend
#
# =================================================================

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies and PowerShell Core
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    apt-transport-https \
    software-properties-common \
    gnupg \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Install PowerShell Core (for Microsoft 365 scripts)
RUN wget -q https://packages.microsoft.com/config/debian/11/packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends powershell \
    && rm -rf /var/lib/apt/lists/*

# Install ExchangeOnlineManagement module for PowerShell
RUN pwsh -Command "Set-PSRepository PSGallery -InstallationPolicy Trusted" \
    && pwsh -Command "Install-Module -Name ExchangeOnlineManagement -Scope AllUsers -Force"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy PowerShell scripts
COPY scripts/ ./scripts/

# Create non-root user for security
RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]