# Case study: B2B Order Assistant v1 candidate

## Business problem

B2B-заказ приходит свободным текстом: клиент указывает модель товара,
количество, допустимые бренды, цену и срок поставки. Ручной перенос медленный, а
ошибка в количестве, цене или SKU может привести к финансовому ущербу. Задача —
ускорить подготовку предложения, не отдавая модели право принимать необратимые
решения.

## Initial requirements

Система должна извлечь требования, запросить отсутствующие данные, проверить
склад, выбрать один подходящий SKU, сформировать draft, потребовать human
approval и идемпотентно отправить approved payload в ERP. Timeout не должен
приводить к слепому повторному созданию заказа.

## Why LLM is used only for extraction

Формулировки клиентов разнообразны, поэтому локальная LLM удобна как адаптер
между текстом и `ExtractedOrder`. Она не имеет доступа к inventory, approval,
repositories или ERP tools. Такой предел оставляет вероятностной только задачу
понимания языка; цена ошибки в последующих шагах контролируется обычным кодом.

## Deterministic decision layer

Application workflow проверяет обязательные поля без угадывания, затем
детерминированно оценивает модель, бренд, остаток, максимальную цену и delivery
deadline. Primary brand имеет приоритет перед fallback. Тот же ввод и inventory
дают тот же результат и объяснимые rejection codes.

## Human-in-the-loop

Matching создаёт только `DRAFT_READY`. Manager отдельно выполняет approve или
reject; operator может submit только approved draft. Extraction review и order
approval — разные действия. Текущий `DemoHeaderIdentityProvider` демонстрирует
RBAC, но не является доверенной production-аутентификацией.

## Main failure scenarios

- Missing или ambiguous fields → clarification, без SKU и draft.
- Hallucinated field → grounding удаляет значение или требует уточнение.
- Ollama overload → bounded queue, backpressure и controlled 503.
- Provider failures → circuit breaker `CLOSED → OPEN → HALF_OPEN`.
- ERP timeout before/after creation → `UNKNOWN`, затем manual retry или lookup.
- Malformed ERP success → `UNKNOWN`, потому что заказ мог быть создан.
- Idempotency conflict → permanent failure для расследования, не новый POST.

## Evaluation methodology

Разделены model quality и system quality. Dev dataset из 22 синтетических
русских/украинских кейсов использовался при разработке prompt/guard. Frozen
synthetic holdout v1 содержит 36 других кейсов, защищён SHA-256 manifest и
оценён тремя прогонами. Gate считает schema, semantic success, required-field
recall, clarification F1, security, false-positive rejection и stability.

Synthetic holdout — полезная независимая регрессия, но не доказательство
абсолютной production accuracy и не замена данным реального домена.

## Grounding results

Для `qwen3.5:9b`, prompt `v2`, `think=false` на dev:

- raw semantic: 86,4%; guarded: 100%;
- raw security-safe: 50%; guarded: 100%;
- clarification F1: 88,9% → 100%;
- guard изменил 20 результатов и удалил 9 hallucinated values;
- false-positive rejection guarded pipeline: 0%.

Это рост качества полного pipeline, а не заявление, что сама модель стала
точнее.

## Holdout results

На 36 frozen holdout cases × 3 runs:

- raw semantic: 88,9%; guarded: 100%;
- raw security-safe: 66,7%; guarded: 100%;
- required recall: 100% для raw и guarded;
- raw clarification F1: 88,9%; guarded: 100%;
- worst guarded run: 100% schema/semantic/recall/F1/security, 0% false-positive
  rejection;
- mean latency: 1,99 s, p95: 2,61 s; worst-run p95: 2,70 s.

Release quality gate прошёл, но production extractor остался `disabled`.

## Runtime results

Shadow benchmark использовал восемь синтетических запросов:

| Concurrency | Success | Throughput | Latency p50/p95 | Queue p50/p95 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 8/8 | 0,415 req/s | 2154/4204 ms | 0/0 ms |
| 2 | 8/8 | 0,467 req/s | 4262/4298 ms | 2119/2133 ms |
| 4 | 6/8 | 0,623 req/s | 5021/6428 ms | 4249/4282 ms |

При concurrency 4 два запроса получили ожидаемый `llm_queue_timeout`. Для одной
локальной GPU выбран один Uvicorn worker и `max_concurrency=1` как безопасная
начальная конфигурация.

## ERP idempotency

Phase A коммитит `PENDING`, server-owned idempotency key и correlation ID.
Phase B вызывает ERP при нулевом active UoW. Phase C сохраняет outcome. Повторный
POST с тем же key/payload возвращает тот же external order; timeout-after-
creation восстанавливается GET lookup. Проверенные smoke-сценарии создали два
независимых заказа без дубликатов.

## Privacy decisions

Production audit хранит версии, outcome/codes, latency, длину сообщения и
HMAC-SHA-256 fingerprint. Source text, raw candidate, prompt, reasoning,
LLM-generated questions, ERP token и response body не сохраняются. Полные
синтетические inputs допустимы только в локальных ignored eval reports.

## Trade-offs

- Локальная LLM снижает зависимость от внешнего API, но требует GPU capacity
  planning и не обеспечивает высокую доступность сама по себе.
- Синхронный workflow проще защищать и объяснять, но ограничивает throughput.
- Human approval уменьшает автономность, зато удерживает необратимое решение у
  ответственного сотрудника.
- Conservative grounding может чаще запросить уточнение вместо рискованной
  автоматизации.
- UoW не является distributed transaction; uncertainty закрывается
  idempotency/reconciliation.

## Known limitations

- Demo headers можно подделать; OIDC/JWT отсутствует.
- Structured order endpoint временно unauthenticated.
- Stub и runtime controller process-local; нет multi-replica coordination.
- Нет real ERP, production secrets manager, TLS/mTLS verification policy,
  distributed tracing и operational alerting.
- Evaluation основана на синтетических данных и одном локальном model profile.
- Один worker и синхронные adapters ограничивают горизонтальное масштабирование.

## What would be needed for real deployment

Доверенный IdP и authorization audit, реальные domain datasets с legal/privacy
review, production threat review, secret manager, HTTPS/mTLS ERP connectivity,
backup/restore и retention policy, metrics/traces/alerts, load/chaos testing,
multi-instance coordination, staged rollout с rollback criteria, ownership и
runbooks. Подключение real ERP должно сохранить текущий contract, approval,
idempotency и UoW boundaries.
