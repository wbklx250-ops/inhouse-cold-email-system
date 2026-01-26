# enable_dkim.ps1
# Enables DKIM signing for a domain in Exchange Online
# Outputs JSON with success/failure status

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
    
    # Check current DKIM status
    $dkimConfig = Get-DkimSigningConfig -Identity $Domain -ErrorAction Stop
    
    if ($dkimConfig.Enabled) {
        # Already enabled
        $result = @{
            domain = $Domain
            enabled = $true
            message = "DKIM was already enabled for this domain"
            action = "none"
        }
    } else {
        # Enable DKIM signing
        Set-DkimSigningConfig -Identity $Domain -Enabled $true -ErrorAction Stop
        
        # Verify it was enabled
        $dkimConfig = Get-DkimSigningConfig -Identity $Domain -ErrorAction Stop
        
        $result = @{
            domain = $Domain
            enabled = $dkimConfig.Enabled
            message = "DKIM has been enabled for this domain"
            action = "enabled"
            selector1_cname = $dkimConfig.Selector1CNAME
            selector2_cname = $dkimConfig.Selector2CNAME
        }
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
    
    # Check for common errors
    $errorMessage = $_.Exception.Message
    
    if ($errorMessage -like "*CNAME record*" -or $errorMessage -like "*DNS*") {
        Write-ErrorJson -Message "DKIM cannot be enabled: DNS CNAME records are not properly configured. Please add the selector1._domainkey and selector2._domainkey CNAME records first."
    } elseif ($errorMessage -like "*not found*") {
        Write-ErrorJson -Message "Domain '$Domain' was not found in Exchange Online. Please verify the domain is added to your M365 tenant."
    } else {
        Write-ErrorJson -Message $errorMessage
    }
}