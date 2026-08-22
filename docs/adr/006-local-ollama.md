# ADR 006: Локальная Ollama

Status: Accepted for portfolio v1.

## Context

Проекту нужен реальный structured extraction experiment без cloud API keys и
передачи текста внешнему provider.

## Decision

Использовать локальную Ollama с зафиксированным профилем `qwen3.5:9b`, prompt
`v2`, `think=false`. Backend остаётся opt-in и disabled по умолчанию.

## Consequences

Нет внешней LLM-сети и API billing; окружение воспроизводимо на имеющемся host.
Доступность и throughput зависят от локальной GPU, а Ollama не является
production HA platform.

## Alternatives considered

Cloud LLM отклонена для этого этапа из-за secrets/privacy scope. Полный отказ от
LLM не показал бы structured extraction и grounding boundary.
