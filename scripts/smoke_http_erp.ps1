param(
    [Parameter(Mandatory = $true)]
    [string]$PostgresPassword,
    [Parameter(Mandatory = $true)]
    [string]$AuditHmacKey,
    [Parameter(Mandatory = $true)]
    [string]$ErpStubToken,
    [switch]$StopAfter
)

$ErrorActionPreference = "Stop"
if ($AuditHmacKey.Length -lt 32) {
    throw "AuditHmacKey must contain at least 32 characters."
}
if ([string]::IsNullOrWhiteSpace($ErpStubToken)) {
    throw "ErpStubToken cannot be empty."
}

$env:POSTGRES_PASSWORD = $PostgresPassword
$env:ORDER_ASSISTANT_AUDIT_HMAC_KEY = $AuditHmacKey
$env:ERP_STUB_TOKEN = $ErpStubToken
$compose = @(
    "compose", "-f", "compose.yaml", "-f", "compose.erp-stub.yaml"
)
$managerHeaders = @{
    "X-Demo-Actor-Id" = "manager@example.com"
    "X-Demo-Actor-Role" = "manager"
}
$operatorHeaders = @{
    "X-Demo-Actor-Id" = "operator@example.com"
    "X-Demo-Actor-Role" = "operator"
}
$stubHeaders = @{Authorization = "Bearer $ErpStubToken"}

function New-ApprovedDraft {
    $body = @{
        model = "6204"
        quantity = 500
        primary_brand = "SKF"
        fallback_brands = @("FAG")
        max_unit_price = "250"
        delivery_deadline = "2026-08-17T09:00:00"
        allow_split_fulfillment = $false
        requires_clarification = $false
        clarification_questions = @()
    } | ConvertTo-Json
    $request = Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/order-requests" `
        -Method Post -ContentType "application/json" -Body $body
    if ($request.processing.status -ne "draft_ready") {
        throw "Expected DRAFT_READY."
    }
    $draft = Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/drafts/$($request.draft_id)/approve" `
        -Method Post -Headers $managerHeaders
    if ($draft.status -ne "approved") {
        throw "Expected APPROVED draft."
    }
    return $draft
}

function Submit-Draft($DraftId) {
    $body = @{} | ConvertTo-Json
    return Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/drafts/$DraftId/submit" `
        -Method Post -ContentType "application/json" `
        -Headers $operatorHeaders -Body $body
}

& docker @compose config --quiet
& docker @compose up --build --detach --wait

try {
    $firstDraft = New-ApprovedDraft
    $first = Submit-Draft $firstDraft.draft_id
    if ($first.status -ne "succeeded") {
        throw "Expected SUCCEEDED submission."
    }
    $restoredDraft = Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/drafts/$($firstDraft.draft_id)" `
        -Headers $managerHeaders
    if ($restoredDraft.status -ne "order_created") {
        throw "Expected ORDER_CREATED draft."
    }
    $duplicate = Submit-Draft $firstDraft.draft_id
    if ($duplicate.created_order_id -ne $first.created_order_id) {
        throw "Idempotent submit returned a different external order ID."
    }
    $stats = Invoke-RestMethod "http://127.0.0.1:18080/__test/stats" `
        -Headers $stubHeaders
    if ($stats.actual_creation_count -ne 1) {
        throw "Expected exactly one external order after duplicate submit."
    }

    $modeBody = @{mode = "TIMEOUT_AFTER_CREATION"} | ConvertTo-Json
    Invoke-RestMethod "http://127.0.0.1:18080/__test/mode" `
        -Method Post -ContentType "application/json" `
        -Headers $stubHeaders -Body $modeBody | Out-Null
    $secondDraft = New-ApprovedDraft
    $unknown = Submit-Draft $secondDraft.draft_id
    if ($unknown.status -ne "unknown") {
        throw "Expected UNKNOWN after timeout-after-creation."
    }
    $modeBody = @{mode = "SUCCESS"} | ConvertTo-Json
    Invoke-RestMethod "http://127.0.0.1:18080/__test/mode" `
        -Method Post -ContentType "application/json" `
        -Headers $stubHeaders -Body $modeBody | Out-Null
    $reconciled = Invoke-RestMethod `
        "http://127.0.0.1:8000/api/v1/submissions/$($unknown.submission_id)/reconcile" `
        -Method Post -Headers $operatorHeaders
    if ($reconciled.status -ne "succeeded") {
        throw "Reconciliation did not recover SUCCEEDED."
    }
    $stats = Invoke-RestMethod "http://127.0.0.1:18080/__test/stats" `
        -Headers $stubHeaders
    if ($stats.actual_creation_count -ne 2) {
        throw "Timeout reconciliation created a duplicate external order."
    }
    Write-Host "success order_id=$($first.created_order_id) actual_creation_count=1"
    Write-Host "timeout_reconciled order_id=$($reconciled.created_order_id) total_creation_count=2"
}
finally {
    if ($StopAfter) {
        & docker @compose down
        Write-Host "Stack stopped; named PostgreSQL volume was preserved."
    }
}
