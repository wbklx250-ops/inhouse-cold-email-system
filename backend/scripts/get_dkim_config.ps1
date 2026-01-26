# get_dkim_config.ps1
# Retrieves DKIM signing configuration for a domain from Exchange Online
# Outputs JSON with selector CNAME values

param(
    [Parameter(Mandatory=$true)]
    [string]$AdminEmail,
    
    [Parameter(Mandatory=$true)]
    [string]$AdminPassword,
    
    [Parameter(Mandatory=$true)]
    [string]$Domain
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Function to output error as JSON and exit
function Write-ErrorJson {
    param([string]$Message)
    $errorResult = @{
        success = $false
        error = $Message
    } | ConvertTo-Json -Compress
    Write-Output $errorResult
    exit 1
}

# Function to output success as JSON and exit
function Write-SuccessJson {
    param([hashtable]$Data)
    $Data.success = $true
    $result = $Data | ConvertTo-Json -Compress
    Write-Output $result
    exit 0
}

try {
    # Create credential object
    $securePassword = ConvertTo-SecureString $AdminPassword -AsPlainText -Force
    $credential = New-Object System.Management.Automation.PSCredential($AdminEmail, $securePassword)
    
    # Check if ExchangeOnlineManagement module is available
    if (-not (Get-Module -ListAvailable -Name ExchangeOnlineManagement)) {
        Write-ErrorJson -Message "ExchangeOnlineManagement module is not installed. Please run: Install-Module -Name ExchangeOnlineManagement -Force"
    }
    
    # Import the module
    Import-Module ExchangeOnlineManagement -ErrorAction Stop
    
    # Connect to Exchange Online
    Connect-ExchangeOnline -Credential $credential -ShowBanner:$false -ErrorAction Stop
    
    # Get DKIM signing config for the domain
    $dkimConfig = Get-DkimSigningConfig -Identity $Domain -ErrorAction Stop
    
    # Extract the relevant information
    $result = @{
        domain = $Domain
        enabled = $dkimConfig.Enabled
        selector1_host = "selector1._domainkey"
        selector2_host = "selector2._domainkey"
        selector1_cname = $dkimConfig.Selector1CNAME
        selector2_cname = $dkimConfig.Selector2CNAME
        selector1_public_key = $dkimConfig.Selector1PublicKey
        selector2_public_key = $dkimConfig.Selector2PublicKey
        last_checked = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    }
    
    # Disconnect from Exchange Online
    Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue
    
    # Output result
    Write-SuccessJson -Data $result
    
} catch {
    # Make sure to disconnect if connected
    try {
        Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue
    } catch {
        # Ignore disconnect errors
    }
    
    Write-ErrorJson -Message $_.Exception.Message
}