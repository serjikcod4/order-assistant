# Release readiness: portfolio v1 candidate

Дата фиксации: 2026-08-22. Это checklist portfolio candidate, а не production
authorization. Статусы разделяют воспроизводимую automation, ручное evidence и
то, что не проверялось в текущем release turn.

## Automated

| Check | Status | Evidence |
| --- | --- | --- |
| Host Windows pytest | BLOCKED | Windows Application Control блокирует импорт `pydantic_core` с WinError 4551; существующий `.venv` не считается успешно проверенным |
| Clean Docker Linux pytest | PASS | `249 passed, 2 skipped, 1 warning in 19.52s`; exit code 0 |
| `pip check` | PASS | `No broken requirements found` |
| Alembic single head | PASS | Expected head `0004_http_erp_metadata`; CI проверяет upgrade/downgrade/upgrade |
| Markdown local links | PASS | Offline validator: 15 Markdown files |
| PowerShell ASCII regression | PASS | Оба smoke scripts содержат только ASCII-текст после допустимого UTF-8 BOM |
| ERP adapter contract | PASS | MockTransport: JSON/headers/status/timeouts/malformed/oversized responses |
| Loopback HTTP ERP | PASS | Independent Uvicorn stub, duplicate prevention, timeout reconciliation |
| Ignored `.env` and DB files | PASS | `.gitignore`: `.env`, `.env.*`, `*.db`, `*.sqlite*` |
| Non-root containers | PASS by static test | API UID/GID 10001, stub UID/GID 10002 |
| Frozen holdout manifest | PASS | Holdout SHA-256 проверяется evaluation/release tests |
| Pytest external network | PASS by design/tests | HTTP tests используют MockTransport/TestClient/loopback; Ollama disabled |

## Manually verified

| Check | Status | Evidence / scope |
| --- | --- | --- |
| Windows PowerShell 5.1 parser | VERIFIED in this turn | Real parser 5.1.26100.9168; both ASCII smoke scripts |
| PowerShell 7 parser | VERIFIED in this turn | Real parser 7.6.4; both scripts |
| Docker Compose config | VERIFIED on user Windows/Docker Desktop machine | `docker compose -f compose.yaml config --quiet`; exit code 0 |
| Full Compose HTTP ERP smoke | VERIFIED, not rerun in lesson 22 | Зафиксировано: два независимых заказа, first duplicate count 1, timeout/reconciliation total 2 |
| Docker build and disabled Compose smoke | VERIFIED in prior packaging work, not rerun here | Production image non-root; PostgreSQL → migrate → API gating |
| Persistence restart | VERIFIED in prior smoke, not rerun here | Draft survived API restart without deleting named volume |
| Ollama shadow | VERIFIED by saved local reports, not rerun | `qwen3.5:9b`, prompt v2, think=false; source/reasoning absent from production audit |
| Frozen holdout release | VERIFIED by saved report | 36 synthetic cases × 3 runs; guarded gate passed; backend stayed disabled |
| Runtime benchmark | VERIFIED by saved reports | c1/c2/c4, eight requests each; c4 produced two controlled queue timeouts |

## Not verified in this turn

- Docker build и Compose smoke не повторялись в этом release turn; отдельно
  подтверждён только `docker compose -f compose.yaml config --quiet` на
  пользовательской Windows/Docker Desktop машине.
- Host Windows pytest остаётся заблокированным Application Control; независимый
  clean Docker Linux pytest прошёл. Причины двух skipped tests здесь не
  интерпретируются.
- Long live Ollama eval и benchmark: намеренно не повторяются без изменения
  model/prompt/guard/runtime.
- Реальная ERP, production TLS/mTLS, certificate rotation и provider SLA.
- Multi-replica behavior, sustained load, chaos, backup/restore и disaster recovery.
- Deployment на публичную инфраструктуру; публикация явно запрещена.

## Security/repository checks

- Git index не содержит `.env`.
- Обнаруженные hardcoded credential-like строки относятся к legacy educational
  placeholders/tests; перед публикацией их всё равно следует маркировать как demo.
- Ignored eval JSON может содержать только синтетические full inputs для локального
  анализа; reasoning/thinking fields не обнаружены.
- Production audit/release report не содержит source text.
- Docker context исключает `.env`, tests, evals/reports, docs, scripts, database
  files и repository metadata.
- Git index пересобран явным portfolio manifest: 143 файла. IDE, legacy HTTP/auth
  lessons, runtime `.env`, database files и generated eval reports в index не
  входят; commit и push остаются отдельным ручным решением владельца.

## Production blockers

- `DemoHeaderIdentityProvider` и unauthenticated structured endpoint.
- Нет production secrets manager, token rotation, trusted TLS/mTLS и egress policy.
- Нет evaluation на репрезентативных размеченных production данных.
- Process-local Ollama limits/circuit и in-memory stub не поддерживают replicas.
- Нет operational SLO, alerts, on-call/runbooks, retention/backup/restore evidence.
- Настоящая ERP integration и совместное contract acceptance не выполнены.
- Privacy/legal review реальных customer messages отсутствует.

## Candidate decision

Подходит для portfolio demonstration и технической защиты: boundaries,
failure handling и evidence воспроизводимы. Не готов к production deployment без
устранения blockers выше. Production defaults должны оставаться
`LLM=disabled`, `ERP=fake`.
