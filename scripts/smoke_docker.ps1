param(
    [ValidateSet("Disabled", "Shadow")]
    [string]$Mode = "Disabled",
    [Parameter(Mandatory = $true)]
    [string]$PostgresPassword,
    [Parameter(Mandatory = $true)]
    [string]$AuditHmacKey,
    [switch]$VerifyPersistence,
    [switch]$StopAfter
)

$ErrorActionPreference = "Stop"
if ($AuditHmacKey.Length -lt 32) {
    throw "AuditHmacKey must contain at least 32 characters."
}

$env:POSTGRES_PASSWORD = $PostgresPassword
$env:ORDER_ASSISTANT_AUDIT_HMAC_KEY = $AuditHmacKey
$composeArguments = @("compose")
if ($Mode -eq "Shadow") {
    $composeArguments += @(
        "-f", "compose.yaml",
        "-f", "compose.ollama-shadow.yaml"
    )
}

& docker @composeArguments config --quiet
& docker @composeArguments up --build --detach --wait

$live = Invoke-RestMethod "http://127.0.0.1:8000/health/live"
$ready = Invoke-RestMethod "http://127.0.0.1:8000/health/ready"
Write-Host "live=$($live.status) ready=$($ready.status)"

if ($Mode -eq "Shadow") {
    $body = @{
        text = "Need 500 SKF 6204 bearings at no more than 250 UAH per unit. If SKF is unavailable, FAG is allowed. Delivery deadline is 2026-08-17 09:00."
    } | ConvertTo-Json
    $result = Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/order-requests/from-text" `
        -Method Post -ContentType "application/json" -Body $body
    if ($result.status -ne "shadow_processed" -or $null -ne $result.draft_id) {
        throw "Unsafe shadow result: expected shadow_processed and draft_id=null."
    }
    Write-Host "shadow_processed audit_id=$($result.audit_id) draft_id=null"
}

if ($VerifyPersistence) {
    if ($Mode -ne "Disabled") {
        throw "Persistence restart check is only available in Disabled mode."
    }
    $structured = @{
        model = "6204"
        quantity = 500
        primary_brand = "SKF"
        fallback_brands = @("FAG")
        max_unit_price = "250"
        delivery_deadline = "2026-08-17T09:00:00"
    } | ConvertTo-Json
    $draft = Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/order-requests" `
        -Method Post -ContentType "application/json" -Body $structured
    & docker @composeArguments restart api
    $ready = $null
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $ready = Invoke-RestMethod "http://127.0.0.1:8000/health/ready"
            if ($ready.status -eq "ready") {
                break
            }
        } catch {
            $ready = $null
        }
    }
    if ($null -eq $ready -or $ready.status -ne "ready") {
        throw "API did not become ready within 60 seconds after restart."
    }
    $headers = @{
        "X-Demo-Actor-Id" = "persistence-smoke"
        "X-Demo-Actor-Role" = "viewer"
    }
    $restored = Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/drafts/$($draft.draft_id)" `
        -Headers $headers
    Write-Host "persisted draft_id=$($restored.draft_id) status=$($restored.status)"
}

if ($StopAfter) {
    & docker @composeArguments down
    Write-Host "Stack stopped; named PostgreSQL volume was preserved."
}
