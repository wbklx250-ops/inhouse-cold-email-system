# Railway Deployment Dockerfile
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chrome/Chromium for Selenium
    chromium \
    chromium-driver \
    # PowerShell dependencies
    wget \
    apt-transport-https \
    software-properties-common \
    gnupg \
    # Build tools
    gcc \
    libpq-dev \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Install PowerShell Core
RUN wget -q https://packages.microsoft.com/config/debian/11/packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && apt-get install -y powershell \
    && rm -rf /var/lib/apt/lists/*

# Install PowerShell modules
RUN pwsh -Command "Set-PSRepository -Name PSGallery -InstallationPolicy Trusted" \
    && pwsh -Command "Install-Module -Name ExchangeOnlineManagement -Force -Scope AllUsers -AcceptLicense"

# Set Chrome paths for Selenium
ENV CHROME_PATH=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV PWSH_PATH=/usr/bin/pwsh

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY backend/ .

# Create directories
RUN mkdir -p /tmp/screenshots

ENV SCREENSHOT_DIR=/tmp/screenshots

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]