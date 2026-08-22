# ADR 002: Human approval перед ERP

Status: Accepted for v1 candidate.

## Context

Даже schema-valid и grounded заявка может быть коммерчески неверной или
требовать ответственности конкретного сотрудника.

## Decision

Workflow создаёт `DRAFT_READY`. Только manager может approve/reject; только
approved draft доступен operator для submission.

## Consequences

Необратимое действие остаётся у человека и появляется audit identity. Цена —
дополнительная задержка и необходимость production-grade identity provider.

## Alternatives considered

Автоматический approve по confidence и approval самой LLM отклонены. Approval
по суммовому порогу оставлен возможной будущей policy, но не частью v1.
