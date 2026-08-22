# ADR 001: LLM только для extraction

Status: Accepted for v1 candidate.

## Context

Свободный текст удобнее разбирать language model, но выбор SKU, проверка цены и
создание заказа имеют финансовые последствия и должны быть воспроизводимы.

## Decision

LLM возвращает только `ExtractedOrder`. Она не получает inventory, repositories,
approval API или ERP tools. Все решения после extraction детерминированы.

## Consequences

Граница проще тестируется и объясняется; hallucination не становится заказом
напрямую. При этом часть неоднозначных заявок чаще требует clarification.

## Alternatives considered

Полностью regex-based parser отклонён как слишком хрупкий для языкового
разнообразия. Agent с ERP tools отклонён из-за недетерминизма и blast radius.
