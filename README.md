# Flow Demo Pack: 50 flow для Salesforce

5 типов × 10 flow (два набора по 5), API 62.0, все в статусе **Active**. Используются только стандартные объекты и поля: нет кастомных полей, объектов, email templates, custom notification types или approval processes.

## Деплой

```bash
sf org login web --alias target
# сначала только проверка:
sf project deploy start --manifest manifest/package.xml --target-org target --dry-run
sf project deploy start --manifest manifest/package.xml --target-org target
```

Все 50 flow деплоятся одним пакетом: subflow-зависимости разрешаются внутри одного деплоя.

**Production.** Активные flow деплоятся активными, только если в Process Automation Settings включено *Deploy processes and flows as active* и деплой запускается с тестами (`--test-level RunLocalTests`). Без этого flow придут как неактивные версии.

## Что должно быть в орге (обычно уже есть по умолчанию)

- **Default Workflow User** (Setup → Process Automation Settings): от его имени выполняются schedule-triggered flow и scheduled paths.
- Активный пользователь с профилем **System Administrator**: часть platform-event flow назначает на него Task и Case и отправляет ему письма.
- Объекты **Contract** и **Event** (стандартные, есть в Sales Cloud). Их используют `AUT_Contract_Renewal_With_Wait`, `SCH_Weekly_Contract_Expiry_Check` и `SCR_Meeting_Scheduler`.
- Email deliverability = *All email*, если нужно, чтобы письма из `Send Email` (emailSimple) реально уходили. Уровень *System only* не мешает деплою.
- Стандартные значения picklist: `Escalated`, `Working`, `Closed`, `Closed - Not Converted`, `Working - Contacted`, `Open - Not Contacted`, `Customer - Direct`, `Customer - Channel`, `Existing Customer - Upgrade`, `Prospecting`, `Qualification`, `Activated`, LeadSource `Other`.

## Безопасность данных

Flow работают с реальными данными орга, поэтому их лучше разворачивать в **sandbox или dev org**.

- Все записи, которые создают flow, помечены префиксом `[Flow Demo]`, логи ошибок — `[Flow Error]`.
- `SCH_Weekly_Demo_Task_Cleanup` удаляет **только** закрытые Task с этими префиксами старше 90 дней.
- Изменения стандартных записей:
  - **Account:** Rating, Type;
  - **Case:** Priority, Status, Origin, Reason, Description;
  - **Lead:** Rating, Status;
  - **Opportunity:** NextStep, OwnerId (при смене владельца Account);
  - **Contact:** адрес, телефон, LeadSource, Description (только пустые поля);
  - **Task:** Priority, OwnerId, Status.
- Расписания стартуют с 2026-10-12 (UTC): Daily и Weekly.
- Задачи без явного OwnerId в schedule-triggered и platform-event flow получает пользователь, от имени которого выполняется flow (Default Workflow User или Automated Process). Письма на `$User.Email` уходят ему же.

## Общие паттерны

- **Fault path**: почти каждый DML, Get Records, Action и Wait имеет fault connector на subflow `AUT_Log_Flow_Error` с передачей `$Flow.FaultMessage`. В screen flow после логирования показывается экран ошибки.
- **Вложенные flow**:
  - `AUT_Account_Health_Calculator`, `AUT_Contact_Data_Normalizer`, `AUT_Opportunity_Pipeline_Summary` и `AUT_Contact_Activity_Snapshot` вызываются из record-triggered, scheduled и screen flow;
  - все flow вызывают `AUT_Log_Flow_Error`.
- **Wait (Pause)** есть только в autolaunched flow: `AUT_Case_Escalation_With_Wait`, `AUT_Opportunity_Followup_Sequence`, `AUT_Lead_Nurture_With_Wait` и `AUT_Contract_Renewal_With_Wait`. Другие типы его не поддерживают. Эти flow не вызываются как subflow; их запускают через REST, Apex или из другого autolaunched flow. В record-triggered flow вместо Wait используются **Scheduled Paths** и **Async Path**.
- **$Record__Prior** используется в after-save update flow `RTF_Opportunity_Amount_Change_Audit` и `RTF_Account_Owner_Change_Cascade`.
- Platform-event flow подписаны на стандартные события `BatchApexErrorEvent`, `FlowExecutionErrorEvent` и `PlatformStatusAlertEvent`.
- Не стоит вызывать `AUT_Task_Bulk_Reassign` без явных входных Id: его нужно запускать с `inFromUserId` и `inToUserId`.

## Состав

### Autolaunched Flow (No Trigger)

| Набор | Flow | Элементов | Состав | Что делает |
|---|---|---|---|---|
| 1 | `AUT_Log_Flow_Error` | 18 | Action×1, Assignment×9, Decision×5, Create×1, Get×2 | Shared fault-path logger. Creates a '[Flow Error]' Task with throttling (max 20 per flow per hour) and e-mails the owner for Critical severity. Called from fault paths of all demo flows. |
| 1 | `AUT_Account_Health_Calculator` | 18 | Assignment×8, Decision×4, Loop×1, Get×3, Update×1, Subflow×1 | Calculates a 0-100 health score for an Account from won/open Opportunities and open Cases and writes Hot/Warm/Cold to Account.Rating. |
| 1 | `AUT_Contact_Data_Normalizer` | 15 | Assignment×5, Collection Filter/Sort×1, Decision×4, Loop×1, Get×2, Update×1, Subflow×1 | Copies missing mailing address / phone from the parent Account onto its Contacts (bulk update). |
| 1 | `AUT_Case_Escalation_With_Wait` | 19 | Action×1, Assignment×7, Decision×4, Create×1, Get×3, Update×1, Subflow×1, Wait×1 | Raises Case priority, pauses N hours (Wait), re-checks the Case and creates an escalation Task + e-mail; retries once. |
| 1 | `AUT_Opportunity_Followup_Sequence` | 18 | Action×1, Assignment×4, Decision×2, Loop×1, Create×2, Get×4, Update×1, Subflow×1, Wait×2 | Multi-step follow-up cadence for an open Opportunity: intro Task, wait 2 days, check progress, follow-up Task, wait 5 days, raise priority of remaining demo Tasks and notify. |
| 2 | `AUT_Opportunity_Pipeline_Summary` | 14 | Assignment×5, Collection Filter/Sort×1, Decision×4, Loop×1, Create×1, Get×1, Subflow×1 | Returns open pipeline, weighted pipeline, deal count and the largest open deal for an Account; optionally writes a summary Task. |
| 2 | `AUT_Task_Bulk_Reassign` | 16 | Assignment×6, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×2, Update×1, Subflow×1 | Moves open Tasks from one user to another (optionally only High priority), validates the target user, bulk-updates and leaves an audit Task for the new owner. |
| 2 | `AUT_Contact_Activity_Snapshot` | 16 | Assignment×7, Decision×3, Loop×1, Create×1, Get×3, Subflow×1 | Returns open/overdue task and open case counts for a Contact plus an engagement label; flags heavily overdue contacts with a Task. |
| 2 | `AUT_Lead_Nurture_With_Wait` | 18 | Action×1, Assignment×4, Decision×3, Create×2, Get×3, Update×2, Subflow×1, Wait×2 | Lead nurture cadence: first-touch Task, wait 3 days, warm up if still untouched, second Task, wait 7 days, then cool down unconverted leads and e-mail the creator. |
| 2 | `AUT_Contract_Renewal_With_Wait` | 17 | Action×1, Assignment×3, Decision×4, Create×2, Get×4, Subflow×1, Wait×2 | Waits until 30 days before a Contract's end date, opens a renewal Opportunity (if none), waits 14 days and escalates with a Task and e-mail when the renewal is still open. |

### Record-Triggered Flow

| Набор | Flow | Элементов | Состав | Что делает |
|---|---|---|---|---|
| 1 | `RTF_Account_After_Create_Setup` | 16 | Action×1, Assignment×3, Decision×3, Loop×1, Create×4, Get×1, Subflow×3 | After-save on Account create: segment-specific setup (Task / starter Opportunity), duplicate-name check with alert, contact normalization subflow; scheduled path +1 day runs health scoring subflow. |
| 1 | `RTF_Opportunity_Closed_Processing` | 16 | Action×1, Assignment×2, Decision×2, Loop×2, Create×2, Get×3, Update×2, Subflow×2 | After-save when an Opportunity becomes closed. Won: promote Account type, sum line-item quantity, onboarding Task + e-mail. Lost: loss-review Task and close open demo Tasks. Scheduled path CloseDate+7 days recalculates Account health. |
| 1 | `RTF_Case_Before_Save_Triage` | 14 | Assignment×6, Decision×5, Loop×1, Get×2 | Before-save (fast field update) on Case create: derives Priority from Account rating/type, the contact's open cases in the last 30 days and Origin; defaults Origin to Web. |
| 1 | `RTF_Lead_Intake_Processing` | 17 | Action×1, Assignment×2, Decision×4, Create×5, Get×3, Update×1, Subflow×1 | After-save on Lead create. Immediate: source-based follow-up Task. Async path: duplicate check against Leads and Contacts with alert. Scheduled path +3 days: cools down untouched leads. |
| 1 | `RTF_Case_High_Priority_Escalation` | 17 | Action×1, Assignment×2, Collection Filter/Sort×1, Decision×3, Loop×1, Create×3, Get×4, Update×1, Subflow×1 | After-save when a Case becomes High priority: routes a Task to account manager or support, collects other open high-priority cases on the account (sorted) and e-mails a digest. Scheduled path +4h after trigger marks still-open cases Escalated. |
| 2 | `RTF_Contact_Before_Save_Defaults` | 14 | Assignment×5, Decision×6, Loop×1, Get×2 | Before-save on Contact create: copies phone/mailing address from the Account when blank, defaults LeadSource, and notes possible duplicate e-mails in Description (only if Description is empty). |
| 2 | `RTF_Task_Completed_Followup` | 15 | Assignment×1, Decision×6, Loop×1, Create×1, Get×4, Update×1, Subflow×1 | After-save when a '[Flow Demo]' Task is completed: for Opportunity tasks creates the next-step Task if the deal is open; for Case tasks marks the case Working when no other open demo tasks remain. |
| 2 | `RTF_Opportunity_Amount_Change_Audit` | 11 | Action×1, Assignment×1, Decision×3, Loop×1, Create×2, Get×1, Subflow×2 | After-save on open Opportunity update: compares Amount and Probability with the prior values ($Record__Prior), audits large changes with a Task + e-mail and flags probability drops. Async path refreshes the pipeline summary. |
| 2 | `RTF_Case_Closed_Followup` | 15 | Action×1, Assignment×1, Decision×5, Create×3, Get×3, Subflow×2 | After-save when a Case is closed: satisfaction-call Task for the contact owner, account-level check for remaining open cases; scheduled path 3 days after ClosedDate checks for reopen and contact activity via subflow. |
| 2 | `RTF_Account_Owner_Change_Cascade` | 14 | Action×1, Assignment×2, Decision×3, Loop×2, Create×1, Get×2, Update×2, Subflow×1 | After-save on Account update when OwnerId changes ($Record__Prior): moves the prior owner's open Opportunities and open account Tasks to the new owner in two bulk updates, then leaves a handover Task and e-mail. |

### Schedule-Triggered Flow

| Набор | Flow | Элементов | Состав | Что делает |
|---|---|---|---|---|
| 1 | `SCH_Daily_Stale_Opportunity_Review` | 14 | Assignment×4, Decision×4, Loop×1, Create×1, Get×2, Update×1, Subflow×1 | Daily, per open Opportunity: flags past-due or stale (30+ days untouched) deals, de-duplicates reminders, finds the primary contact and creates a reminder Task; large deals get NextStep updated. |
| 1 | `SCH_Weekly_Account_Health_Batch` | 13 | Assignment×2, Collection Filter/Sort×1, Decision×3, Create×3, Get×2, Subflow×2 | Weekly, per typed Account: recalculates health via subflow, reacts to rating downgrades (risk Task) and upgrades (de-duplicated upsell Opportunity), and flags accounts with 3+ open cases older than 14 days. |
| 1 | `SCH_Nightly_Case_Aging_Report` | 15 | Action×1, Assignment×4, Collection Filter/Sort×1, Decision×4, Loop×1, Create×1, Get×1, Update×1, Subflow×1 | Nightly batch (no object): loads open cases older than 7 days, sorts by age, buckets 7-30 / 30+ days, raises priority of 30+ day cases, then creates a summary Task and e-mails the report. |
| 1 | `SCH_Daily_Lead_Followup` | 12 | Assignment×1, Decision×4, Create×2, Get×2, Update×2, Subflow×1 | Daily, per uncontacted Lead: 30+ day leads are closed if a matching Contact exists or set Cold otherwise; 3+ day leads get a follow-up Task unless one is already open. |
| 1 | `SCH_Weekly_Demo_Task_Cleanup` | 14 | Action×1, Assignment×2, Collection Filter/Sort×1, Decision×2, Loop×1, Create×1, Delete×2, Get×2, Update×1, Subflow×1 | Weekly housekeeping limited to records created by these demo flows: deletes completed '[Flow Demo]' tasks and '[Flow Error]' logs older than 90 days, raises priority of overdue demo tasks, writes a summary Task and e-mail. |
| 2 | `SCH_Daily_Overdue_Task_Digest` | 13 | Action×1, Assignment×3, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×1, Update×1, Subflow×1 | Daily batch (no object): collects overdue open Tasks, sorts by due date, escalates those overdue 14+ days to High, builds a digest of the oldest 50 and stores/e-mails it. |
| 2 | `SCH_Weekly_Contract_Expiry_Check` | 11 | Assignment×1, Decision×3, Loop×1, Create×3, Get×2, Subflow×1 | Weekly, per activated Contract: contracts ending within 60 days get a renewal Opportunity (de-duplicated) and a Task; the first account contact with an e-mail is attached; expired contracts get a clean-up Task. |
| 2 | `SCH_Weekly_Inactive_Account_Review` | 12 | Assignment×2, Decision×3, Create×2, Get×2, Update×1, Subflow×2 | Weekly, per customer Account not modified for 180 days: no open deals or cases -> rating Cold + review Task; open deals -> re-engagement Task with pipeline numbers from subflow. |
| 2 | `SCH_Daily_Case_SLA_Monitor` | 11 | Action×1, Assignment×2, Decision×3, Create×1, Get×2, Update×1, Subflow×1 | Daily, per open High/Medium Case: New cases older than 24h get an SLA Task (de-duplicated) for the owning user; cases older than 72h are set to Escalated and e-mailed. |
| 2 | `SCH_Weekly_Pipeline_Snapshot` | 15 | Action×1, Assignment×5, Collection Filter/Sort×2, Decision×2, Loop×2, Create×1, Get×1, Subflow×1 | Weekly batch (no object): totals all open Opportunities, counts deals closing within 30 days and past due, lists the top 10 deals by amount, stores the snapshot as a Task and e-mails it. |

### Platform Event–Triggered Flow

| Набор | Flow | Элементов | Состав | Что делает |
|---|---|---|---|---|
| 1 | `PEF_Batch_Apex_Error_Logger` | 12 | Action×1, Assignment×2, Decision×3, Create×2, Get×2, Subflow×2 | Subscribes to BatchApexErrorEvent: classifies severity by phase, finds an active System Administrator, creates a Task with full exception details, e-mails on critical phases and records the error via the shared logger subflow. |
| 1 | `PEF_Batch_Apex_Error_Case_Creator` | 17 | Action×1, Assignment×5, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×3, Update×1, Subflow×1 | Subscribes to BatchApexErrorEvent: de-duplicates by exception type, appends to the newest open Case if one exists, otherwise creates a new Case (owner = active admin) with phase-based priority and notifies by e-mail. |
| 1 | `PEF_Flow_Error_Monitor` | 14 | Action×1, Assignment×6, Decision×3, Get×2, Subflow×2 | Subscribes to FlowExecutionErrorEvent (screen flow errors): categorises the failing element, resolves the user, counts similar errors in the last 24h and alerts when the threshold is reached; always logs via the shared logger. |
| 1 | `PEF_Flow_Error_Case_Escalation` | 14 | Action×1, Assignment×2, Decision×3, Create×3, Get×3, Update×1, Subflow×1 | Subscribes to FlowExecutionErrorEvent: one open Case per failing flow (existing case gets the occurrence appended), owned by an active admin, plus a follow-up Task for the user who hit the error. |
| 1 | `PEF_Platform_Status_Alert_Handler` | 16 | Action×1, Assignment×5, Decision×4, Create×1, Get×3, Subflow×2 | Subscribes to PlatformStatusAlertEvent: classifies severity, routes a Task to the affected user (or an active admin), e-mails on failures and logs via the shared logger. |
| 2 | `PEF_Batch_Error_Scope_Router` | 13 | Assignment×4, Decision×2, Create×2, Get×3, Subflow×2 | Subscribes to BatchApexErrorEvent: takes the first record Id from JobScope, detects its object by key prefix (Account / Opportunity / Case), loads it and attaches a Task to that record and its owner; otherwise a general Task. |
| 2 | `PEF_Batch_Error_Daily_Rollup` | 14 | Action×1, Assignment×1, Decision×3, Loop×1, Create×1, Get×4, Update×1, Subflow×2 | Subscribes to BatchApexErrorEvent: appends each error to one rollup Task per day (created on first error), counts the day's errors and e-mails an active admin once the count reaches 10. |
| 2 | `PEF_Flow_Error_User_Coaching` | 13 | Action×1, Assignment×3, Decision×4, Create×1, Get×3, Subflow×1 | Subscribes to FlowExecutionErrorEvent: routes a coaching Task to the user's manager (or the user), counts the user's coaching tasks in the last 7 days and e-mails when the same user keeps hitting errors. |
| 2 | `PEF_Flow_Error_Hotspot_Detector` | 13 | Action×1, Assignment×2, Collection Filter/Sort×2, Decision×2, Loop×1, Create×1, Get×2, Subflow×2 | Subscribes to FlowExecutionErrorEvent: looks at '[Flow Error]' logs of the same flow in the last 7 days, filters those for the same element, sorts newest first and opens one de-duplicated hotspot Task + e-mail when 3+ repeats are found. |
| 2 | `PEF_Status_Alert_Service_Digest` | 15 | Action×1, Assignment×3, Decision×3, Create×1, Get×4, Update×1, Subflow×2 | Subscribes to PlatformStatusAlertEvent: maintains one daily digest Task per service (append or create), counts open digests for the day and escalates to an active admin when 3+ services report alerts. |

### Screen Flow

| Набор | Flow | Элементов | Состав | Что делает |
|---|---|---|---|---|
| 1 | `SCR_New_Customer_Onboarding` | 16 | Assignment×1, Decision×3, Create×3, Get×1, Screen×6, Subflow×2 | Wizard: capture Account details, warn about duplicate names, create Account + primary Contact (+ optional Opportunity) and show the calculated health score. |
| 1 | `SCR_Case_Intake_Wizard` | 17 | Assignment×4, Decision×2, Create×3, Get×2, Screen×5, Subflow×1 | Support intake: find contact by e-mail (or create one), capture case details with picklist choices, bump priority for repeat customers, create Case and a follow-up Task. |
| 1 | `SCR_Opportunity_Bulk_Stage_Update` | 15 | Assignment×2, Decision×3, Loop×1, Create×1, Get×1, Update×1, Screen×5, Subflow×1 | Pick an Account, then move all of its open Opportunities to a chosen stage/close date in one bulk update with an audit Task. |
| 1 | `SCR_Lead_To_Account_Builder` | 17 | Assignment×1, Decision×3, Create×3, Get×2, Update×1, Screen×5, Subflow×2 | Turns an unconverted Lead into Account (reused if the company already exists) + Contact (+ optional Opportunity), marks the Lead as working and normalizes contact data via subflow. Does not use Lead Convert. |
| 1 | `SCR_Account_Task_Planner` | 17 | Assignment×4, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×1, Screen×5, Subflow×1 | Pick an Account and plan a Task for each of its contacts (optionally only those with an e-mail), built in a loop and inserted in one bulk create. |
| 2 | `SCR_Contact_Quick_Update` | 13 | Decision×2, Create×1, Get×1, Update×1, Screen×6, Subflow×2 | Pick an Account, then one of its Contacts; edit title/e-mail/phone (prefilled), show an activity snapshot from subflow, update the Contact and log a completed Task when the e-mail changed. |
| 2 | `SCR_Case_Bulk_Close` | 18 | Assignment×4, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×1, Update×1, Screen×5, Subflow×1 | Pick an Account, review its open Cases, choose a reason and comment, optionally only Low priority ones; closes them in one bulk update and writes an audit Task. |
| 2 | `SCR_Opportunity_Discount_Calculator` | 14 | Assignment×1, Decision×1, Loop×1, Create×1, Get×2, Update×1, Screen×6, Subflow×1 | Pick an open Opportunity, sum its product lines, enter a discount; discounts above 20% require a justification. Saves the proposal to NextStep/Description and creates a review Task. |
| 2 | `SCR_Account_Hierarchy_Overview` | 13 | Assignment×1, Decision×2, Loop×1, Create×1, Get×1, Screen×5, Subflow×2 | Pick an Account: lists its child accounts with combined annual revenue, shows the parent's pipeline from subflow and optionally creates a hierarchy review Task. |
| 2 | `SCR_Meeting_Scheduler` | 15 | Assignment×1, Decision×3, Create×2, Get×2, Screen×6, Subflow×1 | Schedule a meeting (Event) with a Contact: checks the current user's calendar for overlapping events, lets the user proceed or cancel, creates the Event and a preparation Task due the day before. |

## Генератор

XML собран генератором (`flowgen/`, Python). Набор 1 лежит в `autolaunched.py`, `record_triggered.py`, `scheduled.py`, `platform_event.py` и `screen.py`, набор 2 — в файлах `*2.py`. Сборка: `python3 build.py <out_dir>`; эта команда перезаписывает `<out_dir>`, поэтому не указывайте корень репозитория. Генератор проверяет связи коннекторов, ссылки на ресурсы, `$Record__Prior`, входы и выходы subflow и число элементов (10–20).
