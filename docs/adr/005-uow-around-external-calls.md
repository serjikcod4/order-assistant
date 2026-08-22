# ADR 005: External calls вне Unit of Work

Status: Accepted for v1 candidate.

## Context

Ollama и ERP могут отвечать секунды или завершиться timeout. Открытая DB
transaction на это время удерживает connection/locks и не делает HTTP атомарным.

## Decision

Перед внешним вызовом короткая UoW фиксирует intent; HTTP идёт при
`active_uow_count == 0`; отдельная UoW сохраняет outcome. ERP использует три фазы
`PENDING → external call → final state`.

## Consequences

Transactions короткие и failure boundaries видимы. Возможное падение между HTTP
и Phase C оставляет `PENDING/UNKNOWN` и восстанавливается reconciliation.

## Alternatives considered

Держать transaction вокруг HTTP и пытаться использовать distributed transaction
отклонено. Transactional outbox полезен для будущей async-схемы, но не нужен v1.
