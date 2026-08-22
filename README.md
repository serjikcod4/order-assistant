# B2B Order Assistant

Portfolio-кейс безопасной автоматизации входящих B2B-заявок. Менеджер получает
письмо с моделью, количеством, брендом, ценой и сроком; система превращает его в
проверяемый draft, детерминированно подбирает складской SKU и только после
человеческого подтверждения создаёт заказ через идемпотентный ERP-порт.

## Что делает AI — и где заканчиваются его полномочия

Локальная `qwen3.5:9b` через Ollama используется только для преобразования
свободного текста в `ExtractedOrder`. Grounding guard сверяет поля с исходным
сообщением и удаляет неподтверждённые значения.

AI **не разрешено** выбирать SKU, обходить лимиты цены/остатка/deadline,
подтверждать draft, генерировать ERP idempotency/correlation headers или создавать
заказ. Эти решения принадлежат детерминированному application-слою и человеку.

```mermaid
flowchart LR
    A["Customer text"] --> B["Ollama extraction"]
    B --> C["Grounding guard"]
    C --> D["Deterministic matching"]
    D --> E["Draft"]
    E --> F["Human approval"]
    F --> G["HTTP ERP"]
    G --> H["Retry / reconciliation"]
```

## Основной workflow и гарантии

1. Текст превращается в schema-valid, но пока недоверенный `ExtractedOrder`.
2. Grounding проверяет semantic evidence; missing/ambiguous fields требуют уточнения.
3. Matching проверяет модель, бренд, остаток, цену и delivery deadline.
4. Результат становится `DRAFT_READY`; submit до approve запрещён.
5. Manager подтверждает draft, operator отправляет его через ERP port.
6. Stable server-owned idempotency key предотвращает дубли; uncertain timeout
   восстанавливается lookup/reconciliation.

Безопасность обеспечивают human approval, RBAC, privacy-aware audit без source
text/reasoning, frozen eval holdout, bounded Ollama runtime, circuit breaker,
трёхфазный UoW, строгий ERP contract и fake/stub defaults. LLM и HTTP ERP по
умолчанию выключены (`LLM=disabled`, `ERP=fake`). Development headers не являются
production authentication.

## Подтверждённые результаты v1 candidate

| Проверка | Результат |
| --- | --- |
| Dev, raw → guarded | 86,4% → 100% semantic, 50% → 100% security-safe, 22 cases |
| Synthetic holdout, raw → guarded | 88,9% → 100% semantic, 66,7% → 100% security-safe, 36 cases × 3 runs |
| Runtime benchmark | c1: 8/8; c2: 8/8; c4: 6/8 и 2 controlled queue timeouts |
| ERP timeout-after-creation | reconciliation восстановила заказ без повторного создания |
| Automated regression | Clean Docker Linux: 249 passed, 2 skipped, 1 warning |

Guarded holdout не доказывает абсолютную production accuracy: набор синтетический,
а production backend остаётся выключенным до отдельного rollout-решения. Методика
и полные сводные числа зафиксированы в [case study](docs/case-study.md); локальные
raw eval reports намеренно игнорируются Git.

## Быстрый безопасный demo

Default-конфигурация не вызывает Ollama или HTTP ERP:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn order_assistant.api.app:app --reload
```

Откройте `http://127.0.0.1:8000/docs`, вызовите `/health/ready`, затем отправьте
structured request из [HTTP examples](examples/order-assistant.http). Полный
5–8-минутный сценарий с Ollama, approval, ERP stub и reconciliation описан в
[demo script](docs/demo-script.md).

## Навигация

- [Case study](docs/case-study.md)
- [Architecture](docs/architecture.md) и [ADR index](docs/adr/001-llm-only-for-extraction.md)
- [Threat model](docs/threat-model.md)
- [Interview defense](docs/interview-defense.md)
- [Release readiness](docs/release-readiness.md)

## Архитектура

- `order_assistant/domain` — модели, статусы и исключения без зависимостей от
  HTTP, базы данных или SDK.
- `order_assistant/application` — use cases для извлечения требований,
  подбора SKU, workflow, approval, submission, retry и reconciliation.
- `order_assistant/infrastructure` — `MockOrderExtractor`, persistence-адаптеры,
  fake ERP и opt-in `HTTPERPClient`.
- `order_assistant/api` — тонкий FastAPI-слой. Роутеры делегируют работу
  application-сервисам через контейнер и не содержат бизнес-правил.

Подробности описаны в [docs/architecture.md](docs/architecture.md).

## Что работает сейчас

- Проверка модели, бренда, остатка, цены и срока поставки.
- Выбор одного SKU с приоритетом primary brand.
- Обработка структурированного `ExtractedOrder` через `POST /api/v1/order-requests`.
- Ручные approve/reject переходы черновика.
- Общий ERP-порт для идемпотентной fake ERP и `HTTPERPClient`, retry и
  reconciliation после timeout.
- Swagger UI: `/docs`.

`MockOrderExtractor` — это тестовый адаптер с заранее подготовленными данными.
API принимает уже структурированную заявку и **не является настоящим AI-
извлечением** из письма. Внешняя ERP не подключена: HTTP-режим
проверяется только на отдельном локальном stub. Реальных LLM API нет.

## Локальное извлечение через Ollama

Опциональный `OllamaOrderExtractor` обращается только к локальному Ollama и
преобразует текст в `ExtractedOrder`. Он не получает доступ к складу,
repositories, Unit of Work, approval или ERP. Выбор SKU и все бизнес-проверки
по-прежнему выполняются детерминированным application workflow.

```powershell
$env:ORDER_ASSISTANT_EXTRACTOR_BACKEND = 'ollama'
$env:ORDER_ASSISTANT_OLLAMA_BASE_URL = 'http://localhost:11434'
$env:ORDER_ASSISTANT_OLLAMA_MODEL = 'qwen3.5:9b'
$env:ORDER_ASSISTANT_OLLAMA_TIMEOUT_SECONDS = '120'
$env:ORDER_ASSISTANT_OLLAMA_PROMPT_VERSION = 'v2'
$env:ORDER_ASSISTANT_OLLAMA_THINK = 'false'
.\.venv\Scripts\python.exe -m uvicorn order_assistant.api.app:app
```

После этого `POST /api/v1/order-requests/from-text` принимает JSON вида
`{"text":"Нужно 500 подшипников SKF 6204..."}`. Backend по умолчанию —
`disabled`, поэтому импорт и обычные тесты не вызывают Ollama. API-ключи не
используются; полный текст и `message.thinking` не логируются и не сохраняются.

### Оценка качества extractor

Lesson 15 разделяет prompt на неизменяемый baseline `v1` и улучшенный `v2`.
Eval-набор из 22 русских и украинских сценариев находится в
`evals/order_extraction_cases.json`. Scoring работает без Ollama и измеряет
schema/semantic accuracy, accuracy каждого поля, recall обязательных полей,
clarification precision/recall/F1, latency и стабильность повторных запусков.

Локальный eval требует работающий Ollama. Пример запуска одного профиля:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ollama_extractor.py --prompt-version v2 --think false --runs 1 --model qwen3.5:9b --pipeline both --output eval_reports\ollama_live_grounded.json
```

Скрипт объединяет профили с одинаковым output и создаёт JSON с полными
input/expected/actual/comparison/error данными и краткий Markdown-отчёт.
`message.thinking` не читается, не печатается и не сохраняется.

Измеренный лучший профиль — `qwen3.5:9b`, `v2`, `think=false`; release gate на
зафиксированном holdout v1 пройден. Это подтверждает качество конкретного
профиля на evaluation-наборе, но не разрешает автономное создание заказов.
Backend и rollout mode остаются `disabled` по умолчанию, а ручной approve
черновика обязателен.

### Deterministic grounding

Schema-valid JSON ещё не доказывает, что значение действительно было в письме.
Поэтому production text path оборачивает только `OllamaOrderExtractor` в
`GroundedOrderExtractor`. `ExtractionGroundingGuard` проверяет raw candidate
по исходному тексту до запуска workflow:

- модель и бренды должны встречаться как полные нормализованные токены;
- quantity и unit price должны иметь совместимый числовой контекст;
- точные абсолютные даты и `завтра к HH:MM` обрабатываются
  детерминированно, а `завтра утром` требует уточнения;
- неподтверждённые значения и выдуманные fallback удаляются;
- LLM-generated clarification questions всегда отбрасываются и заменяются
  стабильными application-шаблонами без SKU и пользовательских команд.

Guard ничего не угадывает, не выбирает SKU, не обращается к складу и не
заменяет последующую business validation. Структурированный endpoint guard не
применяет; явно внедрённые extractors в активном rollout проходят тот же guard.

## Staged rollout и privacy-aware audit

`ORDER_ASSISTANT_LLM_ROLLOUT_MODE` имеет три значения:

- `disabled` (default) — text path возвращает controlled 503 и не вызывает LLM;
- `shadow` — Ollama и GroundingGuard создают только безопасный audit, без draft,
  submission, approve или ERP action;
- `review` — guarded result проходит обычный workflow и может создать только
  `DRAFT_READY`, который по-прежнему требует отдельного ручного approve.

Для локального controlled shadow запуска:

```powershell
$env:ORDER_ASSISTANT_EXTRACTOR_BACKEND = 'ollama'
$env:ORDER_ASSISTANT_LLM_ROLLOUT_MODE = 'shadow'
$env:ORDER_ASSISTANT_AUDIT_HMAC_KEY = '<random-local-secret>'
.\.venv\Scripts\python.exe -m uvicorn order_assistant.api.app:app
```

Для review замените `shadow` на `review`. Extraction review оценивает качество
структурированных полей и не изменяет статус draft; order approval — отдельное
действие с отдельным permission. Manager может оставить review, admin — читать
audit и summary, operator/viewer прав не получают.

Audit хранит только версии компонентов, outcome/codes, latency, длину текста и
HMAC-SHA256 fingerprint. Source text, raw candidate, prompt, reasoning и
произвольные вопросы LLM не сохраняются; HMAC key не возвращается API.
Исправленные review экспортируются отдельно:

```powershell
.\.venv\Scripts\python.exe scripts\export_extraction_feedback.py feedback.jsonl
```

Экспорт не изменяет frozen dev/holdout datasets или manifest и не обновляет
prompt/guard автоматически.

## Runtime resilience для локального Ollama

Настоящий `OllamaOrderExtractor` обёрнут process-local
`LLMRuntimeController`. При настройках по умолчанию одновременно выполняется
одна inference, ещё четыре запроса могут ждать не более пяти секунд. Полная
очередь возвращает `503 llm_capacity_exceeded`, timeout очереди —
`503 llm_queue_timeout`, а открытый circuit — `503 llm_circuit_open`;
ответы содержат `Retry-After`. Эти исходы получают один безопасный audit и не
создают draft, submission или ERP order.

```powershell
$env:ORDER_ASSISTANT_LLM_MAX_CONCURRENCY = '1'
$env:ORDER_ASSISTANT_LLM_QUEUE_CAPACITY = '4'
$env:ORDER_ASSISTANT_LLM_QUEUE_WAIT_TIMEOUT_SECONDS = '5'
$env:ORDER_ASSISTANT_LLM_CIRCUIT_FAILURE_THRESHOLD = '3'
$env:ORDER_ASSISTANT_LLM_CIRCUIT_OPEN_SECONDS = '30'
$env:ORDER_ASSISTANT_LLM_CIRCUIT_HALF_OPEN_MAX_CALLS = '1'
$env:ORDER_ASSISTANT_LLM_TRANSPORT_MAX_ATTEMPTS = '1'
```

Circuit проходит `CLOSED → OPEN → HALF_OPEN → CLOSED`; неуспешный probe
возвращает его в `OPEN`. Connection/timeout/HTTP 5xx/malformed upstream
считаются provider failures. Missing fields, clarification, grounding issues,
schema-invalid output и human review circuit не открывают. Transport retry
ограничен отдельной настройкой и по умолчанию выключен (`1` attempt);
semantic retry отсутствует.

`GET /health/live` никогда не проверяет БД/Ollama. `GET /health/ready`
проверяет конфигурацию, SQL connectivity и cached `/api/tags` Ollama без
generation, audit или draft. `OPEN` circuit делает readiness отрицательной,
но liveness остаётся `200`. Исторические latency/rejection метрики доступны
только admin через `GET /api/v1/extraction-runtime/summary`.

Queue wait, Ollama call и circuit probe выполняются до открытия короткого UoW;
database transaction не удерживается вокруг LLM. Semaphore, очередь, gauges и
circuit находятся только в памяти процесса. Для одной RTX 5070 12 GB
рекомендуется один Uvicorn worker и начальные значения `max_concurrency=1`,
`queue_capacity=4`. Несколько workers создадут независимые controllers и могут
одновременно нагрузить одну GPU; для такой схемы позднее нужен внешний
координатор, но Redis/Celery в этом lesson не добавлялись.

Безопасный benchmark принимает только `shadow` mode и использует синтетическую
заявку:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_ollama_concurrency.py `
  --requests 8 --concurrency 1 --base-url http://127.0.0.1:8000 `
  --timeout 180 --output eval_reports\runtime-c1.json
```

Повторите с `--concurrency 2` и `4`. В `review` benchmark завершится до
отправки заявок, поэтому он не может создать черновики или заказы.

## ERP contract v1 и HTTP-адаптер

`ORDER_ASSISTANT_ERP_BACKEND=fake` остаётся default и не выполняет HTTP.
Opt-in `http` реализует тот же application `ERPClient` и передаёт только
данные approved draft по [ERP v1](docs/contracts/erp-v1.openapi.yaml): draft
reference, SKU, quantity, decimal-string price, UAH, delivery deadline и approver.
Source text, prompt, reasoning, audit secret и repository state в ERP не передаются.

HTTP backend требует token и HTTPS. Plain HTTP разрешён только для
`localhost`, loopback и Compose host `erp-stub` при явном
`ORDER_ASSISTANT_ERP_ALLOW_INSECURE_HTTP=true`. Token, Authorization и полные
ответы не сохраняются. Submission хранит только stable correlation ID,
backend/provider/version, HTTP status, normalized error code, duration и external order ID.
Public API генерирует stable idempotency key и correlation ID сам; поля клиента
не могут подменить ERP headers.

Create не имеет внутреннего retry. Timeout, network error, 429, 5xx и malformed
2xx дают `UNKNOWN`; 400/422, 401/403 и 409 дают `PERMANENTLY_FAILED`.
Reconciliation 200 восстанавливает `SUCCEEDED/ORDER_CREATED`; 404 и transient
failure не подменяют статус. Трёхфазная схема сохранена: committed
`PENDING` → HTTP при нулевом active UoW → отдельная final UoW.

Локальный independent stub не входит в production API image и запускается
только отдельным override:

```powershell
$env:POSTGRES_PASSWORD = '<local-password>'
$env:ORDER_ASSISTANT_AUDIT_HMAC_KEY = '<random-key-at-least-32-characters>'
$env:ERP_STUB_TOKEN = '<local-stub-token>'
docker compose -f compose.yaml -f compose.erp-stub.yaml up --build --detach --wait

.\scripts\smoke_http_erp.ps1 `
  -PostgresPassword $env:POSTGRES_PASSWORD `
  -AuditHmacKey $env:ORDER_ASSISTANT_AUDIT_HMAC_KEY `
  -ErpStubToken $env:ERP_STUB_TOKEN -StopAfter
```

`smoke_http_erp.ps1` ASCII-only и поддерживает Windows PowerShell 5.1 и
PowerShell 7. Он проверяет approved create, дубль, `actual_creation_count`,
timeout-after-creation и reconciliation. `down` не удаляет PostgreSQL volume.

## Docker Compose: API + PostgreSQL + migrations

Контейнерный профиль использует `python:3.14.7-slim-bookworm`, PostgreSQL 17,
не-root пользователя и ровно один Uvicorn worker. В image входят только
runtime dependencies и application/Alembic files; `.env`, `.git`, `.venv`,
caches, tests, eval datasets/reports и credentials исключены. Build не
устанавливает Ollama model и заканчивается `pip check`.

Порядок старта зафиксирован в [compose.yaml](compose.yaml):

```text
PostgreSQL healthy → migrate: alembic upgrade head → API start → readiness
```

Миграции не выполняются API worker-ом. Повторный `upgrade head` идемпотентен,
а named volume `postgres-data` переживает restart API и обычный `compose down`.
Базовый stack всегда использует `extractor_backend=disabled` и
`rollout_mode=disabled`, поэтому Ollama ему не нужен.

Скопируйте [.env.docker.example](.env.docker.example) в локальный `.env` и
обязательно замените оба placeholder-секрета. `.env` игнорируется Docker build
context и не должен попадать в Git. Production-like settings требуют SQL URL и
HMAC не короче 32 символов; очевидные placeholder значения завершают startup с
ошибкой. `demo_headers` identity остаётся только учебным провайдером и не
является production authentication.

Основные команды PowerShell:

```powershell
# Build и безопасный disabled startup
docker compose config
docker compose build
docker compose up --detach --wait

# Health и logs
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
docker compose logs --follow api migrate postgres

# Migration status / повторный idempotent upgrade
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic upgrade head

# Downgrade — только ручная административная операция
docker compose run --rm migrate alembic downgrade -1

# Stop с сохранением PostgreSQL volume
docker compose down

# ОПАСНО: полное удаление локальной БД, только по явному решению
docker compose down --volumes
```

Проверить persistence после restart API можно готовым скриптом, который создаёт
только draft и никогда не вызывает approve/submission/ERP:

`smoke_docker.ps1` поддерживает Windows PowerShell 5.1 (`powershell.exe`) и
PowerShell 7 (`pwsh`). Исходный код и встроенный shadow request используют
только ASCII, поэтому корректный parsing не зависит от наличия UTF-8 BOM.
Offline regression дополнительно передаёт BOM-less копию реальному Windows
PowerShell parser, когда `powershell.exe` доступен. Это parser-проверка, а не
замена реального Docker smoke.

```powershell
.\scripts\smoke_docker.ps1 -Mode Disabled `
  -PostgresPassword '<local-random-password>' `
  -AuditHmacKey '<local-random-key-at-least-32-characters>' `
  -VerifyPersistence -StopAfter
```

### Shadow с Ollama на Windows host

Ollama не контейнеризируется. Override
[compose.ollama-shadow.yaml](compose.ollama-shadow.yaml) подключает только API к
`http://host.docker.internal:11434`, фиксирует `qwen3.5:9b`, prompt `v2`,
`think=false` и включает только `shadow`. `review` автоматически не включается.

```powershell
docker compose -f compose.yaml -f compose.ollama-shadow.yaml config
docker compose -f compose.yaml -f compose.ollama-shadow.yaml up --build --detach --wait

.\scripts\smoke_docker.ps1 -Mode Shadow `
  -PostgresPassword '<local-random-password>' `
  -AuditHmacKey '<local-random-key-at-least-32-characters>'
```

Shadow script требует `shadow_processed` и `draft_id=null`. На Linux mapping
`host.docker.internal:host-gateway` уже указан в override; Docker Engine должен
поддерживать `host-gateway`. На Windows Docker Desktop дополнительная настройка
обычно не нужна.

### Offline CI

[CI workflow](.github/workflows/ci.yml) ничего не публикует и содержит пять
job-а:

- `offline-tests` — полный pytest с disabled extractor без Ollama/API keys;
- `postgres-migrations` — PostgreSQL 17, upgrade/current, downgrade base и
  повторный upgrade;
- `docker-build` — build без secrets и disabled image smoke;
- `compose-smoke` — PostgreSQL + migrate + API, `/health/live` и
  `/health/ready`, без Ollama.
- `erp-contract-tests` — MockTransport, PostgreSQL migration, loopback ERP
  stub, approved submission, duplicate prevention и timeout reconciliation.

Локальная проверка зависимостей:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Существующий A/B-отчёт можно повторно проверить полностью offline:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ollama_extractor.py --pipeline both --replay eval_reports\ollama_ab.json --output eval_reports\ollama_grounded.json
```

Replay не создаёт Ollama client и не выполняет HTTP-запросы. Отчёт явно
разделяет raw model quality и guarded system quality, считает удалённые
галлюцинации и false-positive rejections. На сохранённом профиле
`v2 + think=false` guarded system проходит текущий gate, однако backend всё
равно остаётся `disabled` по умолчанию до отдельного решения о включении.

### Development dataset и release holdout

Dev-набор, на котором создавались prompt и grounding rules, зафиксирован как
`evals/datasets/rfq_dev_v1.json` (22 cases). Он предназначен для разработки и
регрессии; даже 100% на dev не означает production readiness.

Независимый синтетический holdout находится в
`evals/datasets/rfq_holdout_v1.json` (36 новых cases). Его SHA-256 записан в
`evals/manifests/rfq_holdout_v1.sha256`. Holdout не используется для
изменения prompt или guard в рамках release-итерации. Любая будущая редакция
должна получить новое имя и manifest, например `rfq_holdout_v2.json`.

Release evaluation проверяет manifest, выполняет минимум три запуска
локального `qwen3.5:9b` с `v2`, `think=false` и применяет gate только к
holdout. Отчёт сохраняет dev/holdout, raw/guarded, per-run, worst-run,
latency, stability и tag breakdown отдельно:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ollama_extractor.py --release --verify-manifest --dataset all --prompt-version v2 --think false --runs 3 --model qwen3.5:9b --pipeline guarded --output eval_reports\rfq_release_v1.json
```

Один critical security failure в любом run блокирует release gate. Даже при
успешном gate backend не включается автоматически: результат означает только
аргументированную рекомендацию для отдельного production-решения.

Первый frozen holdout release для `qwen3.5:9b`, `v2`, `think=false` прошёл
gate на трёх runs: guarded semantic/required recall/clarification F1/security
и stability равны 100%, false-positive rejection — 0%. Raw LLM на том же
holdout получила 88,9% semantic, 88,9% clarification F1 и 66,7%
security-safe. Это подтверждает ценность guard, но не делает raw model
самостоятельно production-ready. Backend остаётся `disabled`.

## Development identity и роли

Защищённые endpoints получают actor только из заголовков
`X-Demo-Actor-Id` и `X-Demo-Actor-Role`. Этот `DemoHeaderIdentityProvider`
предназначен исключительно для локальной разработки: клиент может подделать
оба заголовка, поэтому им **нельзя доверять в production**. В production он
будет заменён проверкой JWT/OIDC от доверенного identity provider.

`POST /api/v1/order-requests` пока временно остаётся без аутентификации.
Все операции с draft и submission требуют development identity. Значения
`approved_by` и `rejected_by` не принимаются из JSON — они всегда берутся из
`X-Demo-Actor-Id`.

| Роль | Разрешения |
| --- | --- |
| `viewer` | чтение drafts и submissions |
| `manager` | чтение, approve и reject drafts |
| `operator` | чтение, submit, retry и reconcile submissions |
| `admin` | все разрешения |

## Установка и запуск

Проект использует уже созданное виртуальное окружение `.venv`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn order_assistant.api.app:app --reload
```

После запуска откройте [Swagger UI](http://127.0.0.1:8000/docs).

## Пример HTTP-сценария

```powershell
$body = @{
  model = "6204"; quantity = 500; primary_brand = "SKF"
  fallback_brands = @("FAG"); max_unit_price = "250"
  delivery_deadline = "2026-08-15T09:00:00"
  allow_split_fulfillment = $false
  requires_clarification = $false
  clarification_questions = @()
} | ConvertTo-Json

$request = Invoke-RestMethod http://127.0.0.1:8000/api/v1/order-requests `
  -Method Post -ContentType 'application/json' -Body $body

Invoke-RestMethod "http://127.0.0.1:8000/api/v1/drafts/$($request.draft_id)/approve" `
  -Method Post -Headers @{
    'X-Demo-Actor-Id' = 'manager@example.com'
    'X-Demo-Actor-Role' = 'manager'
  }

Invoke-RestMethod "http://127.0.0.1:8000/api/v1/drafts/$($request.draft_id)/submit" `
  -Method Post -ContentType 'application/json' -Headers @{
    'X-Demo-Actor-Id' = 'operator@example.com'
    'X-Demo-Actor-Role' = 'operator'
  } `
  -Body '{}'
```

```bash
curl -X POST \
  -H "X-Demo-Actor-Id: manager@example.com" \
  -H "X-Demo-Actor-Role: manager" \
  http://127.0.0.1:8000/api/v1/drafts/{draft_id}/approve
```

## Ограничения и следующие шаги

API предназначен только для demo/development. По умолчанию локальная композиция
может использовать in-memory адаптеры, данные которых исчезают после
перезапуска. Docker Compose использует PostgreSQL и SQLAlchemy persistence, но
multi-replica эксплуатация, production authentication и операционная готовность
не заявлены. Fake ERP и `MockOrderExtractor` можно заменить HTTP ERP и Ollama
адаптерами, не меняя domain и application.

## Persistence

По умолчанию используется `memory`: он быстрый и удобен для разработки, но
данные исчезают после перезапуска. Для persistence доступен синхронный
SQLAlchemy backend; перед его запуском примените миграцию:

```powershell
$env:ORDER_ASSISTANT_PERSISTENCE_BACKEND = 'sqlalchemy'
$env:ORDER_ASSISTANT_DATABASE_URL = 'sqlite:///./order_assistant.db'
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe downgrade base
```

PostgreSQL URL задаётся в формате
`postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE`; runtime dependency
`psycopg[binary]` уже зафиксирована в `requirements.txt`.
Ни URL, ни пароли не логируются. Runtime не запускает миграции автоматически.

SQLAlchemy repositories — infrastructure adapters за repository ports;
ORM-модели не выходят в domain, application или API. Draft, submission,
extraction audit и extraction review доступны через общий Unit of Work; ERP
вызовы намеренно выполняются вне транзакции.

## License

MIT — see [LICENSE](LICENSE).
