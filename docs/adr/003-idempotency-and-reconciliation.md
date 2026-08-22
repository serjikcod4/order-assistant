# ADR 003: Idempotency и reconciliation

Status: Accepted for v1 candidate.

## Context

После HTTP timeout невозможно знать, создала ERP заказ до потери ответа или нет.
Слепой retry с новым ключом создаёт дубликат.

## Decision

Submission получает stable server-owned idempotency key. Retry использует тот
же key; reconciliation выполняет GET lookup и никогда не запускает create.

## Consequences

Timeout-after-creation восстанавливается без дубликата. ERP обязана соблюдать
contract: одинаковый key/payload возвращает тот же заказ, конфликт даёт 409.

## Alternatives considered

At-most-once без retry теряет заказы; blind retry создаёт дубли; distributed
transaction с внешней ERP непрактична для данного контракта.
