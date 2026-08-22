# Threat model: portfolio v1 candidate

## Scope and trust boundaries

В scope входят FastAPI, local Ollama extraction, application workflow,
PostgreSQL persistence и HTTP ERP contract/stub. Customer text, HTTP clients,
LLM output и ERP responses считаются недоверенными. Human manager, database,
Ollama host и ERP становятся доверенными только после production controls,
которых demo полностью не реализует.

| Threat | Existing control | Residual risk | Production recommendation |
| --- | --- | --- | --- |
| Prompt injection в customer text | LLM только извлекает поля; grounding отбрасывает commands/unsupported values; нет ERP tools | Новая формулировка может вызвать false extraction или лишнее clarification | Расширять adversarial datasets, мониторить drift, red-team prompt/guard, сохранять human approval |
| Hallucinated fields | Schema + deterministic grounding + missing-field clarification + deterministic matching | Guard покрывает только поддержанные evidence patterns | Domain-labelled production eval, conservative fallback, versioned guard rollout |
| Client-supplied identity | RBAC и единый `IdentityProvider` port | `DemoHeaderIdentityProvider` полностью подделываем; его нельзя использовать в production | OIDC/JWT validation, issuer/audience/signature checks, short-lived tokens, trusted gateway |
| Forged approval | Approver берётся из resolved Actor, не body; state transition требует manager permission | Скомпрометированные demo headers позволяют forged approval | Production IdP, MFA для privileged role, immutable approval audit, separation of duties |
| Leaked ERP token | `SecretStr`, bearer header формирует adapter; token не сохраняется и не возвращается в health/errors | Environment/process/container compromise раскрывает secret | Secrets manager, rotation, scoped credential, mTLS, egress policy, log redaction tests |
| Replayed HTTP create | Server-owned stable idempotency key; ERP одинаковый key/payload не создаёт дубль | Украденный token позволяет replay; retention idempotency store ограничена ERP | Authenticated caller, bounded replay window, durable ERP idempotency store, key lifecycle policy |
| Idempotency conflict | 409 классифицируется как permanent conflict; автоматического нового POST нет | Требуется ручное расследование; poisoned key может блокировать draft | Alert/runbook, payload fingerprint comparison, protected unique constraints |
| Malicious ERP response | Strict DTO, Content-Type/size/schema/status/key/timezone checks; approved payload не берётся из response | Валидный, но ложный `order_id` всё ещё возможен при compromised ERP | TLS/mTLS, trusted CA, signed/audited responses, reconciliation monitoring |
| Oversized ERP response | Жёсткий лимит 64 KiB до DTO parsing | HTTP library уже получила bytes до application check | Streaming response limit/reverse proxy limit, upstream quotas |
| Timeout uncertainty | `UNKNOWN`, no nested retry, same-key retry и lookup-only reconciliation | Долгий outage оставляет manual queue неопределённых заявок | Scheduled reconciler, alert/SLO, max-age policy и operator runbook |
| DoS против Ollama | Bounded concurrency/queue, queue timeout, circuit breaker, one worker recommendation | Process-local limits не координируют replicas; API всё ещё потребляет resources | Gateway rate limit, auth/quotas, external admission control, capacity/load tests |
| Sensitive source text в logs/audit | Production audit хранит длину и HMAC fingerprint, не source/raw/reasoning; errors нормализованы | Infrastructure/access logs и explicit eval reports требуют отдельного контроля | Structured log allowlist, DLP scan, retention/access policy, encrypted debug workflow |
| Compromised development headers | Документация явно запрещает production use; permission matrix централизована | Любой client может выбрать actor/role в demo | Не собирать production image/config с demo provider; startup fail-fast для trusted identity |
| Database exposure | ORM отделён от API; secrets не входят в responses; containers non-root | DB содержит business drafts, approvals, reviews и submission metadata | Network isolation, TLS, least privilege, encryption/backup, audit logs, retention and restore tests |

## Important non-guarantees

- Grounding не является универсальной защитой от всех prompt injections.
- Synthetic holdout не измеряет абсолютную production accuracy.
- HMAC fingerprint скрывает source только пока key секретен и достаточно силён.
- Idempotency предотвращает дубликат по contract, но не заменяет reconciliation,
  monitoring или business compensation.
- Demo identity и unauthenticated structured endpoint — production blockers.
