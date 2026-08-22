# Interview defense: вопросы и короткие ответы

Ответы ниже — опорные тезисы. На защите лучше связывать их с конкретным failure
scenario или тестом, а не воспроизводить дословно.

1. **Зачем LLM, если часть полей можно извлечь regex?**  Regex хорошо работает
   на фиксированном формате, но реальные письма меняют порядок, язык и контекст.
   LLM нормализует текст в schema; regex/token/date rules затем используются как
   независимый grounding, а не как единственный parser.

2. **Почему LLM не выбирает SKU?**  SKU зависит от точных остатков, цены,
   deadline и приоритета бренда. Эти правила воспроизводимы обычным кодом, а
   ошибка имеет финансовое последствие. Вероятностный выбор здесь не нужен.

3. **Schema validation и semantic validation — в чём разница?**  Schema говорит:
   «quantity — положительное число». Semantic validation спрашивает: «было ли
   именно это количество в письме и в правильном контексте?».

4. **Что такое grounding в этом проекте?**  Это детерминированная сверка полей
   LLM с evidence исходного текста: токены модели/бренда, числовой контекст и
   поддержанные даты. Неподтверждённое значение удаляется.

5. **Почему grounding не заменяет business validation?**  Grounding доказывает
   связь с текстом, но не знает остатков или коммерческих лимитов. Matching
   отдельно решает, допустим ли grounded request для inventory.

6. **Зачем mock extractor?**  Он отделяет tests workflow от доступности и
   недетерминизма модели. Можно точно проверить missing fields, matching и
   approval без GPU и сети.

7. **Зачем отдельные dev и holdout datasets?**  Dev влияет на prompt/guard и
   поэтому даёт оптимистичную оценку. Frozen holdout проверяет выбранный pipeline
   на новых кейсах и защищён manifest от незаметного редактирования.

8. **Почему synthetic holdout не доказывает production accuracy?**  Он не
   отражает весь язык, ошибки и distribution реальных клиентов. Это независимая
   регрессия для текущего scope, не статистическая гарантия production.

9. **Почему raw accuracy ниже system accuracy?**  Guard может убрать
   hallucination или безопасно запросить clarification. Это улучшение pipeline,
   а не самой модели; отчёт специально показывает обе метрики.

10. **Что такое prompt injection здесь?**  Это инструкция внутри customer text,
    пытающаяся заставить модель выдумать поля или выполнить действие. LLM не имеет
    tools, а guard/matching/approval не доверяют её командам.

11. **Зачем human approval, если guarded holdout показал 100%?**  Holdout
    синтетический и ограниченный. Approval удерживает коммерческую ответственность
    у человека и защищает от неизвестных failure modes.

12. **Почему extraction review и order approval разделены?**  Review отвечает:
    «правильно ли поняли текст?». Approval отвечает: «можно ли совершить business
    action?». Смешивание даёт reviewer лишние полномочия.

13. **Что такое idempotency key?**  Stable server-owned идентификатор business
    attempt. Повторный create с тем же key и payload обязан вернуть тот же order,
    а не создать второй.

14. **Timeout before creation и after creation отличаются?**  Для клиента оба
    выглядят одинаково. До создания заказа ещё нет, после — он есть, но ответ
    потерян. Поэтому timeout всегда `UNKNOWN`, а не «failed».

15. **Зачем reconciliation?**  Она делает lookup по сохранённому key и может
    восстановить `SUCCEEDED/ORDER_CREATED` без нового POST. Это закрывает окно
    неопределённости после timeout или crash.

16. **Почему malformed 2xx означает UNKNOWN?**  HTTP success мог прийти после
    durable create, но тело нельзя безопасно интерпретировать. Объявить failure и
    создать заново опаснее, чем сохранить uncertainty и выполнить lookup.

17. **Почему ERP call вне UoW?**  DB transaction не может откатить внешний HTTP
    side effect. Если держать её во время сети, мы лишь удержим connection/locks,
    но не получим атомарность.

18. **Что гарантирует Unit of Work?**  Согласованный commit/rollback локальных
    repository changes внутри одной короткой transaction. Он не гарантирует
    distributed atomicity с Ollama или ERP.

19. **Как переживается crash после успешного HTTP?**  Phase A уже сохранила
    `PENDING` и key. После restart reconciliation находит внешний order и отдельной
    Phase C завершает submission/draft.

20. **Зачем circuit breaker?**  Он прекращает повторные дорогие обращения к
    явно недоступной Ollama, даёт provider восстановиться и допускает ограниченный
    half-open probe.

21. **Backpressure и rate limiting — не одно и то же?**  Backpressure защищает
    внутреннюю ограниченную capacity: bounded in-flight/queue и wait timeout.
    Rate limit ограничивает клиента по quota/time window. В v1 реализовано первое.

22. **Почему один Uvicorn worker?**  Controller и GPU semaphore process-local.
    Несколько workers независимо загрузили бы одну GPU и обошли общий limit.

23. **Почему source text не сохраняется?**  Для operational audit достаточно
    codes, latency, length и fingerprint. Сохранение писем увеличивает privacy
    scope, retention obligations и последствия утечки.

24. **Зачем HMAC fingerprint, а не обычный hash?**  Простые/типовые сообщения
    можно перебирать по SHA. Secret key делает offline guessing без ключа заметно
    сложнее и позволяет сопоставлять повторения без хранения текста.

25. **Почему shadow раньше review?**  Shadow измеряет extraction/grounding и
    audit outcomes без draft или ERP side effects. Только после наблюдения pipeline
    разрешается создавать drafts, всё ещё с human approval.

26. **Зачем contract tests, если есть OpenAPI?**  Файл контракта сам ничего не
    исполняет. MockTransport и independent stub проверяют реальный JSON, headers,
    timeouts, status mapping и несовместимые responses.

27. **Почему DTO stub и adapter независимы?**  Shared DTO позволили бы обеим
    сторонам ошибаться одинаково, и тест был бы зелёным. Независимые модели делают
    контракт настоящей границей.

28. **Почему FakeERP всё ещё нужен после HTTP adapter?**  Он быстрый и полностью
    offline для application tests. HTTP adapter проверяет transport concerns;
    один test double не должен решать обе задачи.

29. **Как защищён ERP token?**  Он приходит через settings как `SecretStr`,
    используется только для Authorization и не включается в domain, persistence,
    health или error text. Для production всё равно нужен secret manager/rotation.

30. **Почему DemoHeaderIdentityProvider — blocker?**  Клиент сам пишет actor и
    role, то есть может стать manager/admin. Он показывает ports/RBAC, но production
    требует криптографически проверяемую identity.

31. **Почему response ERP не может изменить approved order payload?**  Domain
    `CreatedOrder` берёт SKU/quantity/price из approved draft. ERP response сообщает
    только external ID/status/key/time; неожиданные поля запрещены DTO.

32. **Какие главные ограничения до production?**  Trusted identity, реальные
    domain evals, secret/TLS policy, observability/alerts, backup/restore,
    multi-instance coordination, load/chaos tests, operational ownership и
    contract validation с настоящей ERP.
