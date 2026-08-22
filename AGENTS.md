# Repository instructions

## Architecture

- `domain` owns business models, enums and exceptions; it imports neither
  `application` nor `infrastructure`.
- `application` owns workflows/use cases and depends on domain plus Protocol
  ports.
- `infrastructure` implements ports for Ollama, persistence and ERP.
- `api` is a thin transport/composition layer; lesson files are thin demos/re-exports.
- Dependency direction is inward. Do not introduce circular imports or duplicate
  domain models across layers.

## Safety invariants

- LLM is extraction-only: no SKU choice, approval, repository or ERP tools.
- Deterministic matching and human approval remain mandatory before order create.
- Ollama/ERP/external calls run outside Unit of Work/DB transactions.
- ERP create uses stable idempotency and reconciliation; do not add nested POST retry.
- Pytest must not access the internet. Use MockTransport, test clients or loopback.
- Never add real secrets, `.env`, customer text, reasoning or tokens to Git/logs/tests.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m alembic heads
```

Run Docker/Compose checks only when Docker is available. Do not rerun long live
Ollama evals unless model, prompt, guard or evaluation scope changed.

## Migrations

Create one new sequential Alembic revision for an intentional schema change.
Preserve one head, supply upgrade/downgrade, update ORM/mappers/tests and verify
upgrade → downgrade → upgrade. Do not run migrations automatically in API startup.

## Final Codex report

List changed files, behavior/security impact, exact pytest result, migration head,
checks actually executed versus unavailable, known limitations, secret/network
status and confirmation that nothing was published. Never claim Docker,
PowerShell, Ollama or external service verification unless it was really run.
