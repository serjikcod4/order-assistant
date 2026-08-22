# ADR 004: Deterministic grounding и versioned evals

Status: Accepted for v1 candidate.

## Context

JSON Schema подтверждает форму ответа, но не доказывает, что значения были во
входном тексте. Оценка только на dev cases переоценивает качество.

## Decision

Grounding сверяет модель, бренды, числа и поддержанные даты с source evidence.
Model и guarded system оцениваются отдельно на dev и frozen synthetic holdout с
manifest и несколькими runs.

## Consequences

Удалённые hallucinations измеримы, а system quality не выдаётся за model quality.
Conservative guard может увеличить clarification rate; synthetic holdout не
равен production evidence.

## Alternatives considered

Только schema validation и ручное spot-checking отклонены. LLM-as-judge не выбран
как единственный evaluator из-за недетерминизма и общего failure mode.
