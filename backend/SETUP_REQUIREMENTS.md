# System Setup Requirements

Before running automated browser prompts or QR code scanning features, ensure your server has the required system dependencies installed.

## Windows Setup

### 1. Install Chrome Browser
ChromeDriver requires Chrome browser to be installed. Download and install from:
- https://www.google.com/chrome/

Note: The `webdriver-manager` package will automatically download the matching ChromeDriver version.

### 2. Install ZBar Library (for QR code scanning)
For `pyzbar` to work on Windows, you need the Visual C++ Redistributable:

```powershell
# Option 1: Using winget (Windows Package Manager)
winget install Microsoft.VCRedist.2015+.x64

# Option 2: Manual download
# Download from: https://aka.ms/vs/17/release/vc_redist.x64.exe
```

The pyzbar wheel for Windows includes the zbar DLL, so no additional zbar installation is needed.

### 3. Install Python Packages
```powershell
cd cold-email-platform\backend
pip install -r requirements.txt
```

---

## Ubuntu/Debian Setup

### 1. Install System Dependencies
```bash
sudo apt-get update
sudo apt-get install -y chromium-browser chromium-chromedriver libzbar0
```

### 2. Install Python Packages
```bash
cd cold-email-platform/backend
pip install -r requirements.txt
```

---

## Docker Setup

If running in Docker, add to your Dockerfile:

```dockerfile
# Install Chrome and ChromeDriver
RUN apt-get update && apt-get install -y \
    chromium-browser \
    chromium-chromedriver \
    libzbar0 \
    && rm -rf /var/lib/apt/lists/*

# Set Chrome binary path for Selenium
ENV CHROME_BIN=/usr/bin/chromium-browser
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
```

---

## Package Descriptions

| Package | Version | Purpose |
|---------|---------|---------|
| selenium | >=4.15.0 | Browser automation for automated logins |
| webdriver-manager | >=4.0.0 | Automatic ChromeDriver management |
| pyotp | >=2.9.0 | TOTP/MFA code generation |
| Pillow | >=10.0.0 | Image processing for QR codes |
| pyzbar | >=0.1.9 | QR code reading for MFA setup |

---

## Verification

To verify the installation is working:

```python
# Test Selenium/Chrome
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

options = webdriver.ChromeOptions()
options.add_argument('--headless')
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
print("Chrome version:", driver.capabilities['browserVersion'])
driver.quit()

# Test pyzbar
from pyzbar.pyzbar import decode
print("pyzbar imported successfully")

# Test pyotp
import pyotp
totp = pyotp.TOTP('JBSWY3DPEHPK3PXP')
print("TOTP test code:", totp.now())
```

---

## Troubleshooting

### Chrome/ChromeDriver Issues
- **"ChromeDriver not found"**: Ensure Chrome browser is installed; webdriver-manager should handle the rest
- **Version mismatch**: Delete the cached ChromeDriver at `~/.wdm/` and let webdriver-manager download a fresh copy

### pyzbar Issues
- **Windows DLL error**: Install Visual C++ Redistributable as noted above
- **Linux "libzbar.so" not found**: Run `sudo apt-get install libzbar0`

### Headless Mode in Docker/CI
Always use headless mode when running in containers:
```python
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
```