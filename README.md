# Flow Demo Pack: 25 flow для Salesforce

5 типов × 5 flow, API 62.0, все в статусе **Active**. Используются только стандартные объекты и поля: нет кастомных полей, объектов, email templates, custom notification types или approval processes.

## Деплой

```bash
sf org login web --alias target
sf project deploy start --manifest manifest/package.xml --target-org target
# сначала только проверка:
sf project deploy start --manifest manifest/package.xml --target-org target --dry-run
```

Все 25 flow деплоятся одним пакетом: subflow-зависимости разрешаются внутри одного деплоя.

**Production.** Активные flow деплоятся активными, только если в Process Automation Settings включено *Deploy processes and flows as active* и деплой запускается с тестами (`--test-level RunLocalTests`), которые дают нужное покрытие flow. Без этого flow придут как неактивные версии.

## Что должно быть в орге (обычно уже есть по умолчанию)

- **Default Workflow User** (Setup → Process Automation Settings): от его имени выполняются schedule-triggered flow и scheduled paths.
- Активный пользователь с профилем **System Administrator**: platform-event flow назначают на него Task и Case. Если его нет, используется fallback-ветка или fault path.
- Email deliverability = *All email*, если нужно, чтобы письма из `Send Email` (emailSimple) реально уходили. Уровень *System only* не мешает деплою.
- Стандартные значения picklist: `Escalated`, `Closed - Not Converted`, `Working - Contacted`, `Open - Not Contacted`, `Customer - Direct`, `Prospecting`, `Qualification`.

## Безопасность данных

Flow работают с реальными данными орга, поэтому их лучше разворачивать в **sandbox или dev org**.

- Все записи, которые создают flow, помечены префиксом `[Flow Demo]`, логи ошибок — `[Flow Error]`.
- `SCH_Weekly_Demo_Task_Cleanup` удаляет **только** закрытые Task с этими префиксами старше 90 дней.
- Изменения стандартных записей: `Account.Rating` (health score), `Account.Type` (при выигранной Opportunity), `Case.Priority/Status/Origin`, `Lead.Rating/Status`, `Opportunity.NextStep`, адрес и телефон Contact (если они пустые).
- Расписания стартуют с 2026-10-12 (UTC): Daily и Weekly.

## Общие паттерны

- **Fault path**: почти каждый DML, Get Records, Action и Wait имеет fault connector на subflow `AUT_Log_Flow_Error` с передачей `$Flow.FaultMessage`. Логгер создаёт Task `[Flow Error] …`, ограничивает число логов (не больше 20 на flow в час) и отправляет письмо при Critical. В screen flow после логирования показывается экран ошибки.
- **Вложенные flow**: `AUT_Account_Health_Calculator`, `AUT_Contact_Data_Normalizer` и `AUT_Log_Flow_Error` вызываются из record-triggered, scheduled, platform-event и screen flow, а также друг из друга (2 уровня вложенности).
- **Wait (Pause)** используется только в autolaunched flow `AUT_Case_Escalation_With_Wait` и `AUT_Opportunity_Followup_Sequence`, потому что другие типы его не поддерживают. Эти два flow не вызываются как subflow; их запускают через REST, Apex или из другого autolaunched flow. В record-triggered flow вместо Wait используются **Scheduled Paths** и **Async Path**.
- Platform-event flow подписаны на стандартные события `BatchApexErrorEvent`, `FlowExecutionErrorEvent` и `PlatformStatusAlertEvent`.

## Состав

### Autolaunched Flow (No Trigger)

| Flow | Элементов | Состав | Что делает |
|---|---|---|---|
| `AUT_Log_Flow_Error` | 18 | Action×1, Assignment×9, Decision×5, Create×1, Get×2 | Shared fault-path logger. Creates a '[Flow Error]' Task with throttling (max 20 per flow per hour) and e-mails the owner for Critical severity. Called from fault paths of all demo flows. |
| `AUT_Account_Health_Calculator` | 18 | Assignment×8, Decision×4, Loop×1, Get×3, Update×1, Subflow×1 | Calculates a 0-100 health score for an Account from won/open Opportunities and open Cases and writes Hot/Warm/Cold to Account.Rating. |
| `AUT_Contact_Data_Normalizer` | 15 | Assignment×5, Collection Filter/Sort×1, Decision×4, Loop×1, Get×2, Update×1, Subflow×1 | Copies missing mailing address / phone from the parent Account onto its Contacts (bulk update). |
| `AUT_Case_Escalation_With_Wait` | 19 | Action×1, Assignment×7, Decision×4, Create×1, Get×3, Update×1, Subflow×1, Wait×1 | Raises Case priority, pauses N hours (Wait), re-checks the Case and creates an escalation Task + e-mail; retries once. |
| `AUT_Opportunity_Followup_Sequence` | 18 | Action×1, Assignment×4, Decision×2, Loop×1, Create×2, Get×4, Update×1, Subflow×1, Wait×2 | Multi-step follow-up cadence for an open Opportunity: intro Task, wait 2 days, check progress, follow-up Task, wait 5 days, raise priority of remaining demo Tasks and notify. |

### Record-Triggered Flow

| Flow | Элементов | Состав | Что делает |
|---|---|---|---|
| `RTF_Account_After_Create_Setup` | 16 | Action×1, Assignment×3, Decision×3, Loop×1, Create×4, Get×1, Subflow×3 | After-save on Account create: segment-specific setup (Task / starter Opportunity), duplicate-name check with alert, contact normalization subflow; scheduled path +1 day runs health scoring subflow. |
| `RTF_Opportunity_Closed_Processing` | 16 | Action×1, Assignment×2, Decision×2, Loop×2, Create×2, Get×3, Update×2, Subflow×2 | After-save when an Opportunity becomes closed. Won: promote Account type, sum line-item quantity, onboarding Task + e-mail. Lost: loss-review Task and close open demo Tasks. Scheduled path CloseDate+7 days recalculates Account health. |
| `RTF_Case_Before_Save_Triage` | 14 | Assignment×6, Decision×5, Loop×1, Get×2 | Before-save (fast field update) on Case create: derives Priority from Account rating/type, the contact's open cases in the last 30 days and Origin; defaults Origin to Web. |
| `RTF_Lead_Intake_Processing` | 17 | Action×1, Assignment×2, Decision×4, Create×5, Get×3, Update×1, Subflow×1 | After-save on Lead create. Immediate: source-based follow-up Task. Async path: duplicate check against Leads and Contacts with alert. Scheduled path +3 days: cools down untouched leads. |
| `RTF_Case_High_Priority_Escalation` | 17 | Action×1, Assignment×2, Collection Filter/Sort×1, Decision×3, Loop×1, Create×3, Get×4, Update×1, Subflow×1 | After-save when a Case becomes High priority: routes a Task to account manager or support, collects other open high-priority cases on the account (sorted) and e-mails a digest. Scheduled path +4h after trigger marks still-open cases Escalated. |

### Schedule-Triggered Flow

| Flow | Элементов | Состав | Что делает |
|---|---|---|---|
| `SCH_Daily_Stale_Opportunity_Review` | 14 | Assignment×4, Decision×4, Loop×1, Create×1, Get×2, Update×1, Subflow×1 | Daily, per open Opportunity: flags past-due or stale (30+ days untouched) deals, de-duplicates reminders, finds the primary contact and creates a reminder Task; large deals get NextStep updated. |
| `SCH_Weekly_Account_Health_Batch` | 13 | Assignment×2, Collection Filter/Sort×1, Decision×3, Create×3, Get×2, Subflow×2 | Weekly, per typed Account: recalculates health via subflow, reacts to rating downgrades (risk Task) and upgrades (de-duplicated upsell Opportunity), and flags accounts with 3+ open cases older than 14 days. |
| `SCH_Nightly_Case_Aging_Report` | 15 | Action×1, Assignment×4, Collection Filter/Sort×1, Decision×4, Loop×1, Create×1, Get×1, Update×1, Subflow×1 | Nightly batch (no object): loads open cases older than 7 days, sorts by age, buckets 7-30 / 30+ days, raises priority of 30+ day cases, then creates a summary Task and e-mails the report. |
| `SCH_Daily_Lead_Followup` | 12 | Assignment×1, Decision×4, Create×2, Get×2, Update×2, Subflow×1 | Daily, per uncontacted Lead: 30+ day leads are closed if a matching Contact exists or set Cold otherwise; 3+ day leads get a follow-up Task unless one is already open. |
| `SCH_Weekly_Demo_Task_Cleanup` | 14 | Action×1, Assignment×2, Collection Filter/Sort×1, Decision×2, Loop×1, Create×1, Delete×2, Get×2, Update×1, Subflow×1 | Weekly housekeeping limited to records created by these demo flows: deletes completed '[Flow Demo]' tasks and '[Flow Error]' logs older than 90 days, raises priority of overdue demo tasks, writes a summary Task and e-mail. |

### Platform Event–Triggered Flow

| Flow | Элементов | Состав | Что делает |
|---|---|---|---|
| `PEF_Batch_Apex_Error_Logger` | 12 | Action×1, Assignment×2, Decision×3, Create×2, Get×2, Subflow×2 | Subscribes to BatchApexErrorEvent: classifies severity by phase, finds an active System Administrator, creates a Task with full exception details, e-mails on critical phases and records the error via the shared logger subflow. |
| `PEF_Batch_Apex_Error_Case_Creator` | 17 | Action×1, Assignment×5, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×3, Update×1, Subflow×1 | Subscribes to BatchApexErrorEvent: de-duplicates by exception type, appends to the newest open Case if one exists, otherwise creates a new Case (owner = active admin) with phase-based priority and notifies by e-mail. |
| `PEF_Flow_Error_Monitor` | 14 | Action×1, Assignment×6, Decision×3, Get×2, Subflow×2 | Subscribes to FlowExecutionErrorEvent (screen flow errors): categorises the failing element, resolves the user, counts similar errors in the last 24h and alerts when the threshold is reached; always logs via the shared logger. |
| `PEF_Flow_Error_Case_Escalation` | 14 | Action×1, Assignment×2, Decision×3, Create×3, Get×3, Update×1, Subflow×1 | Subscribes to FlowExecutionErrorEvent: one open Case per failing flow (existing case gets the occurrence appended), owned by an active admin, plus a follow-up Task for the user who hit the error. |
| `PEF_Platform_Status_Alert_Handler` | 16 | Action×1, Assignment×5, Decision×4, Create×1, Get×3, Subflow×2 | Subscribes to PlatformStatusAlertEvent: classifies severity, routes a Task to the affected user (or an active admin), e-mails on failures and logs via the shared logger. |

### Screen Flow

| Flow | Элементов | Состав | Что делает |
|---|---|---|---|
| `SCR_New_Customer_Onboarding` | 16 | Assignment×1, Decision×3, Create×3, Get×1, Screen×6, Subflow×2 | Wizard: capture Account details, warn about duplicate names, create Account + primary Contact (+ optional Opportunity) and show the calculated health score. |
| `SCR_Case_Intake_Wizard` | 17 | Assignment×4, Decision×2, Create×3, Get×2, Screen×5, Subflow×1 | Support intake: find contact by e-mail (or create one), capture case details with picklist choices, bump priority for repeat customers, create Case and a follow-up Task. |
| `SCR_Opportunity_Bulk_Stage_Update` | 15 | Assignment×2, Decision×3, Loop×1, Create×1, Get×1, Update×1, Screen×5, Subflow×1 | Pick an Account, then move all of its open Opportunities to a chosen stage/close date in one bulk update with an audit Task. |
| `SCR_Lead_To_Account_Builder` | 17 | Assignment×1, Decision×3, Create×3, Get×2, Update×1, Screen×5, Subflow×2 | Turns an unconverted Lead into Account (reused if the company already exists) + Contact (+ optional Opportunity), marks the Lead as working and normalizes contact data via subflow. Does not use Lead Convert. |
| `SCR_Account_Task_Planner` | 17 | Assignment×4, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×1, Screen×5, Subflow×1 | Pick an Account and plan a Task for each of its contacts (optionally only those with an e-mail), built in a loop and inserted in one bulk create. |

## Генератор

XML собран генератором (`flowgen/`, Python). Чтобы поменять flow, правьте нужный `*.py` и запускайте `python3 build.py <out_dir>`. Генератор проверяет связи коннекторов, ссылки на ресурсы, входы и выходы subflow и число элементов (10–20).
