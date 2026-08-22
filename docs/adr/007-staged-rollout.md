# ADR 007: Staged rollout disabled → shadow → review

Status: Accepted for v1 candidate.

## Context

Успешный offline eval не разрешает сразу влиять на workflow. Нужен способ
наблюдать extractor без создания business state.

## Decision

`disabled` не вызывает LLM; `shadow` создаёт только privacy-aware audit; `review`
может создать draft, всё ещё требующий approval. Autonomous mode отсутствует.

## Consequences

Риск растёт постепенно, а rollout можно остановить конфигурацией. Shadow не
проверяет весь human workflow и требует осмысленных критериев продвижения.

## Alternatives considered

Немедленный review/autonomous rollout и feature flag только на уровне endpoint
отклонены как недостаточно безопасные и наблюдаемые.
