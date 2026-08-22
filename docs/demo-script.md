# Demo script: 5–8 минут

Сценарий рассчитан на Windows PowerShell. Все значения секретов — placeholders;
замените их только локальными временными значениями. Не записывайте их в Git.

## Подготовка до встречи

Убедитесь, что локальная Ollama уже содержит `qwen3.5:9b`. Поднимите только ERP
stub; API запустится локально с memory persistence, Ollama review и HTTP ERP:

```powershell
$StubToken = '<temporary-local-stub-token>'
$AuditKey = '<temporary-random-key-at-least-32-characters>'
$env:ERP_STUB_TOKEN = $StubToken
docker compose -f compose.yaml -f compose.erp-stub.yaml up --build --detach --wait erp-stub

$env:ORDER_ASSISTANT_EXTRACTOR_BACKEND = 'ollama'
$env:ORDER_ASSISTANT_LLM_ROLLOUT_MODE = 'review'
$env:ORDER_ASSISTANT_OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
$env:ORDER_ASSISTANT_OLLAMA_MODEL = 'qwen3.5:9b'
$env:ORDER_ASSISTANT_OLLAMA_PROMPT_VERSION = 'v2'
$env:ORDER_ASSISTANT_OLLAMA_THINK = 'false'
$env:ORDER_ASSISTANT_AUDIT_HMAC_KEY = $AuditKey
$env:ORDER_ASSISTANT_ERP_BACKEND = 'http'
$env:ORDER_ASSISTANT_ERP_BASE_URL = 'http://127.0.0.1:18080'
$env:ORDER_ASSISTANT_ERP_TOKEN = $StubToken
$env:ORDER_ASSISTANT_ERP_ALLOW_INSECURE_HTTP = 'true'
$env:ORDER_ASSISTANT_ERP_READ_TIMEOUT_SECONDS = '1'
.\.venv\Scripts\python.exe -m uvicorn order_assistant.api.app:app
```

Во втором PowerShell-окне:

```powershell
$Base = 'http://127.0.0.1:8000'
$Stub = 'http://127.0.0.1:18080'
$StubToken = '<same-temporary-local-stub-token>'
$Manager = @{'X-Demo-Actor-Id'='demo-manager'; 'X-Demo-Actor-Role'='manager'}
$Operator = @{'X-Demo-Actor-Id'='demo-operator'; 'X-Demo-Actor-Role'='operator'}
$Admin = @{'X-Demo-Actor-Id'='demo-admin'; 'X-Demo-Actor-Role'='admin'}
$StubHeaders = @{Authorization="Bearer $StubToken"}
```

## 1. Health и Swagger — 20 секунд

```powershell
Invoke-RestMethod "$Base/health/live"
Invoke-RestMethod "$Base/health/ready"
Start-Process "$Base/docs"
```

Объяснить: liveness не вызывает Ollama/DB, readiness выполняет безопасные probes.

## 2–5. Text → extraction → grounding → matching → draft — 90 секунд

```powershell
$TextBody = @{
  text = 'Нужно 500 подшипников SKF 6204, максимум 250 UAH за штуку. Если SKF нет, можно FAG. Доставка до 2026-08-17 09:00.'
} | ConvertTo-Json
$TextResult = Invoke-RestMethod "$Base/api/v1/order-requests/from-text" `
  -Method Post -ContentType 'application/json' -Body $TextBody

$TextResult.guarded_result | ConvertTo-Json -Depth 5
$TextResult.grounding_issues | ConvertTo-Json -Depth 5
$TextResult.processing.selected_item | ConvertTo-Json -Depth 5
$DraftId = $TextResult.draft_id
$DraftId
```

Показать границы: LLM дала поля, guard проверил evidence, SKU выбрал обычный код,
результат пока только `DRAFT_READY`.

## 6. Submit без approve — 20 секунд

```powershell
try {
  Invoke-RestMethod "$Base/api/v1/drafts/$DraftId/submit" `
    -Method Post -ContentType 'application/json' -Headers $Operator -Body '{}'
  throw 'Submit unexpectedly succeeded.'
} catch {
  $_.ErrorDetails.Message
}
```

Ожидается HTTP 409 `invalid_status_transition`; ERP не вызывается.

## 7–9. Approve, submit, duplicate prevention — 60 секунд

```powershell
$Approved = Invoke-RestMethod "$Base/api/v1/drafts/$DraftId/approve" `
  -Method Post -Headers $Manager
$First = Invoke-RestMethod "$Base/api/v1/drafts/$DraftId/submit" `
  -Method Post -ContentType 'application/json' -Headers $Operator -Body '{}'
$Repeated = Invoke-RestMethod "$Base/api/v1/drafts/$DraftId/submit" `
  -Method Post -ContentType 'application/json' -Headers $Operator -Body '{}'
$Stats = Invoke-RestMethod "$Stub/__test/stats" -Headers $StubHeaders

$Approved.status
$First.status
$First.created_order_id -eq $Repeated.created_order_id
$Stats.actual_creation_count
```

Ожидается `approved`, затем `succeeded`, одинаковый external order ID и
`actual_creation_count=1`.

## 10–11. Timeout-after-creation и reconciliation — 90 секунд

Создайте второй deterministic draft без второго LLM-вызова:

```powershell
$Structured = @{
  model='6204'; quantity=500; primary_brand='SKF'; fallback_brands=@('FAG')
  max_unit_price='250'; delivery_deadline='2026-08-17T09:00:00'
} | ConvertTo-Json
$SecondRequest = Invoke-RestMethod "$Base/api/v1/order-requests" `
  -Method Post -ContentType 'application/json' -Body $Structured
$SecondDraftId = $SecondRequest.draft_id
Invoke-RestMethod "$Base/api/v1/drafts/$SecondDraftId/approve" `
  -Method Post -Headers $Manager | Out-Null

@{mode='TIMEOUT_AFTER_CREATION'} | ConvertTo-Json | ForEach-Object {
  Invoke-RestMethod "$Stub/__test/mode" -Method Post `
    -ContentType 'application/json' -Headers $StubHeaders -Body $_
} | Out-Null
$Unknown = Invoke-RestMethod "$Base/api/v1/drafts/$SecondDraftId/submit" `
  -Method Post -ContentType 'application/json' -Headers $Operator -Body '{}'
$Unknown.status

@{mode='SUCCESS'} | ConvertTo-Json | ForEach-Object {
  Invoke-RestMethod "$Stub/__test/mode" -Method Post `
    -ContentType 'application/json' -Headers $StubHeaders -Body $_
} | Out-Null
$Reconciled = Invoke-RestMethod `
  "$Base/api/v1/submissions/$($Unknown.submission_id)/reconcile" `
  -Method Post -Headers $Operator
$Stats = Invoke-RestMethod "$Stub/__test/stats" -Headers $StubHeaders
$Reconciled.status
$Stats.actual_creation_count
```

Ожидается `unknown → succeeded`. Total count равен 2: один первый заказ и один
timeout-order, без третьего дубликата.

## 12. Privacy-aware audit — 40 секунд

```powershell
$Audit = Invoke-RestMethod `
  "$Base/api/v1/extraction-audits/$($TextResult.audit_id)" -Headers $Admin
$Audit | ConvertTo-Json -Depth 8
Invoke-RestMethod "$Base/api/v1/extraction-audits/summary" -Headers $Admin
Invoke-RestMethod "$Base/api/v1/extraction-runtime/summary" -Headers $Admin
```

Показать, что audit содержит версии, codes, outcome, latency, длину и IDs, но не
customer source text, raw candidate, prompt, reasoning или HMAC key.

## Завершение

```powershell
docker compose -f compose.yaml -f compose.erp-stub.yaml down
```

Команда не использует `--volumes`. Если live Ollama недоступна во время встречи,
не имитируйте результат: покажите сохранённые подтверждённые метрики из case study
и выполните structured + ERP часть demo.
