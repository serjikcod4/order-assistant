# Архитектура order_assistant

## Назначение

Проект демонстрирует безопасную обработку заказа на подшипники: из
структурированных данных извлекаются требования, склад проверяется по
детерминированным правилам, а предложение передаётся человеку на
подтверждение. Создание заказа идёт через ERP-порт с fake по умолчанию
и opt-in production-shaped HTTP-адаптером.

## Слои

- `domain` содержит Pydantic-модели, статусы, причины отклонения и
  исключения. Он не импортирует другие слои и не зависит от транспорта,
  сети или SDK.
- `application` реализует use cases: извлечение требований, проверку
  склада, workflow, approval и устойчивую отправку. Внешние зависимости
  описаны через `Protocol` в `application/ports.py`.
- `infrastructure` содержит заменяемые адаптеры: `MockOrderExtractor`,
  persistence, fake ERP, `HTTPERPClient` и Ollama adapter. Сетевые адаптеры
  включаются только явной конфигурацией.
- `api` содержит FastAPI factory, `AppContainer`, DTO и HTTP-роутеры. Он
  преобразует HTTP-ввод в application use cases, но не содержит бизнес-правил.

Направление зависимостей однонаправленное: `api → application → domain` и
`infrastructure → application → domain`. Поэтому domain не знает о
конкретных реализациях, а циклические импорты не возникают.

## Поток обработки

1. `OrderExtractor` выдаёт `ExtractedOrder`. Для локальной LLM это пока
   недоверенный raw candidate.
2. Активный LLM path проходит через application-компонент
   `ExtractionGroundingGuard`, который удаляет неподтверждённые значения и
   формирует вопросы по стабильным кодам. Структурированный endpoint этот этап
   не использует.
3. `build_order_requirements()` проверяет обязательные поля и возвращает
   вопросы для уточнения без угадывания данных.
4. `process_customer_order()` применяет детерминированные правила склада:
   модель, бренд, остаток, цена и deadline. Затем выбирает один SKU с
   приоритетом primary brand.
5. Готовый результат становится `OrderDraft`, но не заказом. Только человек
   вызывает `approve_draft()` или `reject_draft()`.
6. Для approved draft `ResilientOrderService` сначала сохраняет
   `OrderSubmission`, а затем обращается к ERP-порту.
7. После timeout submission получает `UNKNOWN`. Retry использует исходный
   idempotency key, а reconciliation только ищет уже созданный заказ.
8. HTTP ERP коммитит stable correlation ID в Phase A, выполняет
   create/lookup при `active_uow_count == 0` и сохраняет outcome отдельной
   Phase C transaction.

`POST /api/v1/order-requests` принимает уже структурированный
`ExtractedOrder`: HTTP API пока не выполняет AI-извлечение из письма. Для
`DRAFT_READY` он создаёт черновик; для уточнений и отсутствия совпадения
возвращает только processing result. `AppContainer` компонует выбранные
адаптеры: локальный режим может использовать process-local memory repositories,
а Docker Compose — SQLAlchemy repositories поверх PostgreSQL. Memory state
исчезает после перезапуска; multi-replica production deployment не заявлен.

## Development authorization

`Actor`, `ActorRole` и `Permission` находятся в domain, а единая матрица
ролей — в `application/authorization.py`. API получает actor через
`IdentityProvider` port и проверяет права до вызова сервисов. Текущий
`DemoHeaderIdentityProvider` читает `X-Demo-Actor-Id` и
`X-Demo-Actor-Role` только для локальной разработки. Эти заголовки
контролируются клиентом и могут быть подделаны; в production их заменит
JWT/OIDC-проверка от доверенного IdP. Approver/rejector берутся из Actor,
а не из HTTP body.

## Persistence adapters

`SqlAlchemyDraftRepository`, `SqlAlchemySubmissionRepository`,
`SqlAlchemyExtractionAuditRepository` и `SqlAlchemyExtractionReviewRepository` реализуют
application repository ports. ORM-модели и mapper’ы остаются в infrastructure;
domain получает только Pydantic объекты. Alembic migrations создают schema
отдельно от runtime — приложение не вызывает `create_all()` или migrations при
импорте. Memory и SQLAlchemy adapters доступны через единый Unit of Work.

## Unit of Work

Memory UoW works on an isolated copy. SQLAlchemy UoW opens one synchronous
Session for a local transaction, commits or rolls back it, and closes it on
exit. ERP calls must stay outside a database transaction; a crash after ERP
creation is recovered through the saved idempotency key and reconciliation.
This is not a distributed transaction or transactional outbox.

## Граница LLM и детерминизм

LLM-граница заканчивается на выдаче schema-valid, но недоверенного
`ExtractedOrder`. JSON Schema проверяет структуру и типы, но не подтверждает,
что модель, бренд, количество, цена или deadline действительно присутствовали
в source text. LLM не выбирает SKU, не подтверждает заявку и не создаёт заказ.
Складская проверка, приоритет
брендов, расчёт цены, переходы статусов и идемпотентность выполняются
детерминированно в application.

Опциональный infrastructure-адаптер `OllamaOrderExtractor` обращается только
к локальному Ollama. Версионированные prompts `v1` и `v2` хранятся отдельно
от адаптера; JSON Schema всегда генерируется из Pydantic-модели
`ExtractedOrder`, а не поддерживается вручную. `v2` получает фиксируемый
`current_datetime`, чтобы относительные даты можно было оценивать
воспроизводимо. Reasoning модели (`message.thinking`) не входит в domain,
логи или eval-отчёты.

Независимый модуль `order_assistant.evaluation` сравнивает ожидаемые и
фактические поля без сети. Только CLI в `scripts/evaluate_ollama_extractor.py`
делает локальные запросы и сохраняет JSON/Markdown A/B-отчёты. Quality gate
требует 100% schema validity и required-field recall, не менее 90% semantic
success и clarification F1, а также безопасное поведение на prompt injection.
Даже после прохождения release gate extractor backend и rollout остаются
выключенными по умолчанию: evaluation не равен разрешению автономной работы.
Автоматического semantic retry нет: отсутствующее поле может действительно
отсутствовать во входном сообщении.

## Grounding guardrails

`GroundedOrderExtractor` — application-декоратор над конкретным
`OllamaOrderExtractor`. Он передаёт raw candidate в
`ExtractionGroundingGuard` вместе с source text и timezone-aware
`received_at`. Guard выполняет консервативную Unicode/token/number/date
проверку, возвращает новый `ExtractedOrder`, структурированные
`GroundingIssue` и evidence и никогда не мутирует исходный объект.

Guard является rejection/validation layer: он может удалить галлюцинацию,
потребовать уточнение и детерминированно обработать только поддержанные точные
форматы deadline. Он не дополняет отсутствующие бизнес-данные, не использует
inventory и не заменяет matching или business validation. Свободные вопросы
LLM считаются недоверенными; клиент получает только application-шаблоны,
связанные со стабильными issue/missing-field codes.

Offline replay читает raw actual outputs из eval JSON без создания Ollama
client. Отчёт показывает model quality и system quality отдельно, чтобы
улучшение guardrails не выдавалось за улучшение LLM. Production path не
сохраняет полный source text, raw candidate или reasoning; они доступны только
в явно запущенном eval/debug отчёте.

## Development evaluation и release holdout

Development dataset используется для настройки prompt, guardrails и
регрессионных проверок. Его метрики не являются независимой оценкой. Holdout
dataset содержит новые синтетические сценарии и защищён SHA-256 manifest;
изменение файла после фиксации обнаруживается до запуска release evaluation.
Для новой итерации создаётся новая версия dataset и manifest вместо правки
существующей.

Release report по-прежнему разделяет raw LLM quality и guarded system quality,
но quality gate рассчитывается исключительно по holdout. Gate использует
каждый run, worst-run, critical cases, false-positive rejection и stability.
Провал одного critical security case в одном run блокирует рекомендацию вне
зависимости от dev-метрик. Pytest проверяет dataset, manifest, scoring и gate
offline; только явно запущенный CLI выполняет запросы к локальному Ollama.

## Staged rollout, audit и human feedback

Rollout mode отделён от выбора backend:

- `disabled` не вызывает extractor;
- `shadow` выполняет extraction и grounding, но сохраняет только audit metadata;
- `review` запускает прежний детерминированный workflow и может создать только
  черновик, ожидающий ручного approval.

Режима active/autonomous нет. `ExtractionAuditService` координирует text path
и хранит `ExtractionAuditRecord`: request/audit IDs, версии backend/model/
prompt/guard, latency, outcome, стабильные issue codes, длину source и keyed
HMAC-SHA256 fingerprint. Сам source, raw candidate, prompt, reasoning и
LLM-generated questions не попадают в repository или API audit view. HMAC key
задаётся отдельной secret-настройкой и не выводится.

`ExtractionReview` — отдельная оценка качества extraction. Accepted/rejected
review не содержит corrected values; corrected review содержит только
schema-valid `ExtractedOrder` и correction codes. Review не вызывает методы
approval/submission и не меняет draft status. Manager может создать review,
admin читает audit/summary и также может review; viewer/operator доступа не
имеют. Это не заменяет order approval.

Summary агрегирует режимы, outcomes, grounding/LLM errors, review decisions,
correction rate и p50/p95 без чувствительных данных. Feedback exporter берёт
только corrected reviews и пишет отдельный JSONL/JSON. Frozen dev/holdout и
manifest никогда не дополняются автоматически; человек отдельно решает, что
станет новым versioned eval case и нужно ли менять prompt/guard.

## Approval, idempotency и замена адаптеров

Human approval обязателен перед созданием заказа. Idempotency предотвращает
дубли при неопределённом результате timeout; reconciliation обнаруживает
заказ, который ERP могла создать до обрыва ответа. Порты позволяют переключать
`MockOrderExtractor` на Ollama, memory repositories на SQLAlchemy/PostgreSQL, а
fake ERP на HTTP ERP adapter, не меняя domain-модели и application workflow.

### HTTP ERP boundary

Канонический `docs/contracts/erp-v1.openapi.yaml` описывает create, lookup и
health. Infrastructure-only Pydantic DTO строго проверяет HTTP status,
Content-Type, лимит размера, JSON/schema, `created`, timezone-aware
`created_at` и совпадение idempotency key. DTO не выходит из
infrastructure. Approved SKU, quantity и price в `CreatedOrder` берутся из
исходного draft, поэтому ERP response не может подменить approved payload.

Adapter не повторяет POST. Timeout/network/429/5xx и invalid 2xx дают
uncertain outcome; 400/422/auth/conflict — permanent outcome с safe code. Lookup 404 и
transient failure не меняют submission; malformed lookup success остаётся contract
error и не запускает create. Token, Authorization и response body не попадают
в domain, persistence, API и errors. Хранятся только correlation ID,
backend/provider/version, HTTP status, normalized code, duration и external order ID.
Idempotency key и correlation ID генерируются на сервере; public request не
может подменить ERP headers.

`erp_stub` — независимое test/development приложение с собственными DTO,
bearer auth, memory idempotency, `actual_creation_count` и управляемыми failure
modes. Оно не копируется в API image и подключается только
`compose.erp-stub.yaml`.

## Runtime bulkhead, backpressure и circuit breaker

Production wiring имеет порядок
`GroundedOrderExtractor(LLMRuntimeController(OllamaOrderExtractor))`.
Controller охватывает только admission, bounded queue, transport attempts и
inference. Mock adapter не оборачивается им в container. Thread-safe condition
ограничивает одновременно выполняемые вызовы и число ожидающих; permits и
queue slots освобождаются в `finally` после success, exception, timeout и
отмены потока.

Circuit breaker process-local и имеет состояния `CLOSED`, `OPEN`, `HALF_OPEN`.
Последовательные connection/reset, transport timeout, HTTP 5xx и malformed
upstream responses открывают circuit. После cooldown разрешается ограниченное
число probe calls. Validation/clarification/grounding/human feedback не
являются отказами provider. Повторяются только явно retryable transport
ошибки; schema-invalid output и semantic uncertainty не повторяются.

Вызов `ExtractionAuditService.process_text()` сначала полностью завершает
runtime/grounding phase, затем открывает короткий UoW для workflow/draft и
отдельно сохраняет audit. Поэтому одна заявка не держит SQL transaction во
время ожидания GPU или HTTP-вызова. Audit хранит числовые queue/inference/total
latencies, attempts, circuit state и rejection flags, но не source/raw output/
prompt/reasoning. Current gauges берутся из памяти controller, исторические
percentiles и counts — из audit repository.

`/health/live` проверяет только event loop/process. `/health/ready` использует
коротко кешируемые проверки SQL и Ollama `/api/tags`, никогда не выполняет
generation и не создаёт audit. OPEN circuit отражается в readiness, не в
liveness.

Semaphore и circuit не координируются между Uvicorn workers. Одна локальная
GPU должна обслуживаться одним worker; у нескольких процессов будут отдельные
limits и probes. Multi-process deployment потребует внешней очереди или
координатора в отдельном будущем этапе.

## Container topology и migration strategy

Production-like image собирается multi-stage Dockerfile на фиксированном
Python 3.14 slim. Builder устанавливает только runtime requirements в отдельный
venv и выполняет dependency compatibility check; final stage копирует venv,
package и Alembic files, работает от UID/GID 10001 и запускает Uvicorn exec-form
командой с одним worker. SIGTERM поэтому поступает непосредственно Uvicorn.
Secrets, `.env`, repository metadata, caches и evaluation artifacts не входят
в build context или layers.

Base Compose разделяет три ответственности и оставляет ERP backend `fake`:

```text
postgres:17 (healthy, persistent volume)
    ↓
migrate (same image, alembic upgrade head, exits successfully)
    ↓
api (SQLAlchemy/psycopg, one worker, disabled LLM default)
```

ERP override добавляет healthy `erp-stub:8080` и включает HTTP backend с
explicit local-only insecure flag. PostgreSQL/migrate gating и disabled LLM сохраняются.

API зависит от `service_completed_successfully` migration job и сама не
вызывает Alembic. Это исключает конкурирующие migrations при старте workers.
Повторный migrate безопасно проверяет текущий head. Downgrade остаётся явной
ручной административной операцией, а destructive volume reset никогда не
запускается автоматически.

Base Compose требует PostgreSQL password и production-grade audit HMAC из
environment, но не Ollama. `Settings` fail-fast проверяет SQL URL, согласованную
пару active rollout/Ollama и отсутствие placeholder HMAC. Ни URL, ни passwords,
ни HMAC не входят в health/API responses. `/health/live` используется Docker
healthcheck для процесса; FastAPI `/health/ready` дополнительно проверяет SQL и,
только в shadow, cached host Ollama probe. Эти проверки имеют разную семантику.

Ollama остаётся на Windows host. Отдельный override использует
`host.docker.internal`, включает только shadow и сохраняет один worker. На Linux
добавлен `host-gateway`; это process/network routing, а не контейнеризация GPU
runtime.

CI воспроизводит пять независимых границ: offline unit/integration tests,
PostgreSQL migration chain, secret-free image build и disabled Compose smoke.
Пятая — MockTransport contract tests и loopback PostgreSQL + independent ERP stub
end-to-end с duplicate prevention и timeout reconciliation.
Ни один job не загружает модель, не требует API key и не публикует image.
