# create_mailboxes.ps1
# Creates shared mailboxes in Exchange Online
# Accepts JSON array of mailbox definitions
# Outputs JSON with results for each mailbox

param(
    [Parameter(Mandatory=$true)]
    [string]$AdminEmail,
    
    [Parameter(Mandatory=$true)]
    [string]$AdminPassword,
    
    [Parameter(Mandatory=$true)]
    [string]$MailboxesJson  # JSON array: [{"email": "...", "display_name": "..."}]
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Function to output error as JSON and exit
function Write-ErrorJson {
    param([string]$Message)
    $errorResult = @{
        success = $false
        error = $Message
        results = @()
    } | ConvertTo-Json -Compress
    Write-Output $errorResult
    exit 1
}

# Function to output results as JSON and exit
function Write-ResultsJson {
    param(
        [array]$Results,
        [int]$SuccessCount,
        [int]$FailCount
    )
    $output = @{
        success = ($FailCount -eq 0)
        total = $Results.Count
        succeeded = $SuccessCount
        failed = $FailCount
        results = $Results
    } | ConvertTo-Json -Depth 3 -Compress
    Write-Output $output
    if ($FailCount -eq 0) {
        exit 0
    } else {
        exit 1
    }
}

try {
    # Parse the mailboxes JSON
    try {
        $mailboxes = $MailboxesJson | ConvertFrom-Json
    } catch {
        Write-ErrorJson -Message "Invalid JSON format for mailboxes: $($_.Exception.Message)"
    }
    
    if ($mailboxes.Count -eq 0) {
        Write-ErrorJson -Message "No mailboxes provided in the JSON array"
    }
    
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
    
    # Process each mailbox
    $results = @()
    $successCount = 0
    $failCount = 0
    
    foreach ($mailbox in $mailboxes) {
        $email = $mailbox.email
        $displayName = $mailbox.display_name
        
        # Derive alias from email (part before @)
        $alias = $email.Split("@")[0]
        
        try {
            # Check if mailbox already exists
            $existingMailbox = Get-Mailbox -Identity $email -ErrorAction SilentlyContinue
            
            if ($existingMailbox) {
                $results += @{
                    email = $email
                    display_name = $displayName
                    success = $false
                    action = "skipped"
                    error = "Mailbox already exists"
                    existing_type = $existingMailbox.RecipientTypeDetails
                }
                $failCount++
            } else {
                # Create the shared mailbox
                $newMailbox = New-Mailbox -Shared -Name $displayName -DisplayName $displayName -Alias $alias -PrimarySmtpAddress $email -ErrorAction Stop
                
                $results += @{
                    email = $email
                    display_name = $displayName
                    success = $true
                    action = "created"
                    mailbox_guid = $newMailbox.ExchangeGuid.ToString()
                    recipient_type = $newMailbox.RecipientTypeDetails
                }
                $successCount++
            }
        } catch {
            $results += @{
                email = $email
                display_name = $displayName
                success = $false
                action = "failed"
                error = $_.Exception.Message
            }
            $failCount++
        }
    }
    
    # Disconnect from Exchange Online
    Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue
    
    # Output results
    Write-ResultsJson -Results $results -SuccessCount $successCount -FailCount $failCount
    
} catch {
    # Make sure to disconnect if connected
    try {
        Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue
    } catch {
        # Ignore disconnect errors
    }
    
    Write-ErrorJson -Message $_.Exception.Message
}