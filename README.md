# Flow Demo Pack: 100 flow для Salesforce

5 типов × 20 flow, API 62.0, все в статусе **Active**. Используются только стандартные объекты и поля: нет кастомных полей, объектов, email templates, custom notification types, очередей, record types или approval processes.

Наборы: 1 и 2 — по 5 flow каждого типа, 3 — по 10 flow каждого типа.

## Деплой

```bash
sf org login web --alias target
# сначала только проверка:
sf project deploy start --manifest manifest/package.xml --target-org target --dry-run
sf project deploy start --manifest manifest/package.xml --target-org target
```

Все flow деплоятся одним пакетом: subflow-зависимости разрешаются внутри одного деплоя.

**Production.** Активные flow деплоятся активными, только если в Process Automation Settings включено *Deploy processes and flows as active* и деплой запускается с тестами (`--test-level RunLocalTests`). Без этого flow придут как неактивные версии.

## Что должно быть в орге (обычно уже есть по умолчанию)

- **Default Workflow User** (Setup → Process Automation Settings): от его имени выполняются schedule-triggered flow и scheduled paths.
- Активный пользователь с профилем **System Administrator**: часть flow назначает на него Task и Case и отправляет ему письма. Используются также профили `System Administrator` и `Standard User`.
- Стандартные объекты: Account, Contact, Lead, Opportunity, OpportunityLineItem, OpportunityContactRole, Case, Task, Event, Contract, Asset, Product2, Pricebook2, PricebookEntry, User и Profile. Все они есть в Developer и Enterprise Edition.
- Email deliverability = *All email*, если нужно, чтобы письма из `Send Email` (emailSimple) реально уходили. Уровень *System only* не мешает деплою.
- Стандартные (дефолтные) значения picklist, например:
  - Case: `New`, `Working`, `Escalated`, `Closed`;
  - Lead: `Open - Not Contacted`, `Working - Contacted`, `Closed - Not Converted`;
  - Account Type: `Prospect`, `Customer - Direct`, `Customer - Channel`;
  - Opportunity Type: `Existing Customer - Upgrade`;
  - Contract: `Draft`, `Activated`;
  - Asset: `Installed`, `Registered`;
  - OpportunityContactRole Role: `Decision Maker`.

## Безопасность данных

Flow работают с реальными данными орга, поэтому их лучше разворачивать в **sandbox или dev org**.

- Все записи, которые создают flow, помечены префиксом `[Flow Demo]`, логи ошибок — `[Flow Error]`.
- Удаляются только Task, созданные самими flow (с этими префиксами).
- Flow меняют стандартные поля существующих записей:
  - **Account:** Rating, Type;
  - **Case:** Priority, Status, Origin, Reason, Description, ContactId, ParentId;
  - **Lead:** Rating, Status, Description;
  - **Opportunity:** NextStep, OwnerId;
  - **Contact:** адрес, телефон, LeadSource, Description, только если поля пустые;
  - **Task:** Priority, OwnerId, Status, ActivityDate, WhatId;
  - **Contract:** Status при активации;
  - **Event:** время при переносе встречи.
- Расписания стартуют с 2026-10-12 (UTC): Daily, Weekly и Once.
- Задачи без явного OwnerId в schedule-triggered и platform-event flow получает пользователь, от имени которого выполняется flow (Default Workflow User или Automated Process). Письма на `$User.Email` уходят ему же.

## Общие паттерны

- **Fault path**: почти каждый DML, Get Records, Action и Wait имеет fault connector на subflow `AUT_Log_Flow_Error` с передачей `$Flow.FaultMessage`. В screen flow после логирования показывается экран ошибки. Before-save flow fault path не нужен.
- **Вложенные flow**: autolaunched-утилиты (health score, pipeline summary, activity snapshot, normalizer, lead scoring, warranty check, duplicate finder, data quality report и др.) вызываются из всех типов flow. Глубина вложенности доходит до 4 уровней.
- **Wait (Pause)** есть только в autolaunched flow: `AUT_Case_Escalation_With_Wait`, `AUT_Opportunity_Followup_Sequence`, `AUT_Lead_Nurture_With_Wait`, `AUT_Contract_Renewal_With_Wait`, `AUT_Event_Followup_With_Wait`, `AUT_Contract_Activation_Checklist_Wait`, `AUT_Case_Deflection_With_Wait`, `AUT_Opportunity_Handoff_With_Wait`. Другие типы его не поддерживают. Эти flow не вызываются как subflow; их запускают через REST, Apex или из другого autolaunched flow.
- В record-triggered flow вместо Wait используются **Scheduled Paths** (в том числе с отрицательным смещением, «за N дней до») и **Async Path**. Есть before-save, after-save и before-delete flow; `$Record__Prior` используется в after-save update flow.
- **Platform-event flow** подписаны на стандартные события `BatchApexErrorEvent`, `FlowExecutionErrorEvent` и `PlatformStatusAlertEvent`.

## Состав

### Autolaunched Flow (No Trigger) (20)

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
| 3 | `AUT_Lead_Score_Calculator` | 16 | Assignment×7, Decision×4, Loop×1, Get×2, Update×1, Subflow×1 | Campaign-free lead scoring: scores a Lead 0-100 from profile completeness, company size, lead source and logged activity, and writes Hot/Warm/Cold to Lead.Rating. |
| 3 | `AUT_Lead_Batch_Scoring` | 17 | Action×1, Assignment×7, Collection Filter/Sort×1, Decision×4, Loop×1, Get×1, Subflow×2 | Re-scores a user's recent unconverted Leads (capped at the 25 newest per run) by calling AUT_Lead_Score_Calculator for each, counts Hot/Cold results and optionally e-mails a summary. |
| 3 | `AUT_Asset_Warranty_Check` | 13 | Assignment×4, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×2, Subflow×1 | Classifies an Account's Assets by UsageEndDate (expired / expiring within N days / active), returns counts and the next expiry date, and optionally creates a warranty review Task for the Account owner. |
| 3 | `AUT_Account_Duplicate_Finder` | 15 | Assignment×5, Collection Filter/Sort×1, Decision×3, Loop×2, Get×3, Subflow×1 | Finds potential duplicates of an Account by exact Name and by Phone, returns the count and a readable list of matches. |
| 3 | `AUT_Account_Data_Quality_Report` | 18 | Assignment×7, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×2, Subflow×3 | Builds a data-quality grade (A/B/C) for an Account by combining AUT_Account_Duplicate_Finder, AUT_Asset_Warranty_Check, Contacts without e-mail and missing Account fields; optionally writes a report Task. |
| 3 | `AUT_Event_Followup_Task_Creator` | 18 | Assignment×6, Decision×5, Loop×1, Create×2, Get×3, Subflow×1 | Creates a single follow-up Task for an Event (same Who/What), skipping it when an open follow-up already exists; owner is the Event's active assignee or its creator. WhatId is left blank when the Event's WhoId is a Lead. |
| 3 | `AUT_Event_Followup_With_Wait` | 18 | Action×1, Assignment×5, Decision×3, Loop×1, Get×3, Update×1, Subflow×2, Wait×2 | Waits until 1 hour after an Event ends, creates the follow-up Task via AUT_Event_Followup_Task_Creator, waits 3 days and escalates still-open follow-ups (priority High + e-mail). |
| 3 | `AUT_Contract_Activation_Checklist_Wait` | 19 | Action×1, Assignment×6, Decision×3, Loop×2, Create×1, Get×2, Update×1, Subflow×2, Wait×1 | For a Draft Contract: checks the Account's asset warranties, creates a 3-item activation checklist (bulk Task insert), waits 7 days, then activates the Contract when all items are completed or e-mails a reminder. |
| 3 | `AUT_Case_Deflection_With_Wait` | 19 | Assignment×5, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Delete×1, Get×3, Update×1, Subflow×2, Wait×1 | Case deflection: for a New Case finds the 5 most recent closed Cases of the same Type, records them in a suggestion Task, waits N hours and either moves the Case to Working (not deflected) or removes the suggestion Task (deflected). |
| 3 | `AUT_Opportunity_Handoff_With_Wait` | 19 | Action×1, Assignment×5, Decision×3, Loop×1, Create×1, Get×4, Subflow×2, Wait×2 | Team-less handoff of a Closed Won Opportunity to an account manager: runs the Account data-quality report, waits 1 day, creates an intro Task per contact role (bulk insert), waits 7 days and reminds the new owner about open intros. |

### Record-Triggered Flow (20)

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
| 3 | `RTF_Contact_Email_Change_Sync` | 12 | Action×1, Assignment×1, Decision×4, Loop×1, Create×1, Get×1, Update×1, Subflow×2 | After-save on Contact update when Email changes ($Record__Prior): moves the contact's open Cases that still carry the old web e-mail to the new address (bulk update), refreshes the activity snapshot subflow and leaves a verification Task + e-mail. |
| 3 | `RTF_Lead_Hot_Rating_Acceleration` | 17 | Action×1, Assignment×1, Decision×6, Loop×1, Create×2, Get×3, Update×1, Subflow×2 | After-save when an unconverted Lead becomes Hot: raises its open demo Tasks to High (bulk update), alerts on a Cold-to-Hot jump ($Record__Prior) and creates a call Task. Scheduled path +2 days: if still untouched, stalled-lead Task and contact snapshot for a matching Contact. |
| 3 | `RTF_Opportunity_Create_Contact_Roles` | 14 | Assignment×2, Collection Filter/Sort×1, Decision×3, Loop×1, Create×3, Get×2, Subflow×2 | After-save on Opportunity create (with Account, no roles yet): adds Decision Maker contact roles for senior contacts of the account (collection filter on Title, bulk create) or a Task to identify them. Async path: pipeline summary subflow and a capacity Task when the account has many open deals. |
| 3 | `RTF_Opportunity_Product_Before_Delete` | 14 | Action×1, Assignment×1, Decision×4, Loop×1, Create×3, Get×2, Subflow×2 | Before-delete on OpportunityLineItem: on closed deals raises an alert Task + e-mail; on open deals totals the remaining product lines and creates a Task when the last product or a large line is removed, then refreshes the pipeline summary. |
| 3 | `RTF_Case_Email_Contact_Matcher` | 13 | Action×1, Assignment×2, Decision×2, Loop×1, Create×3, Get×1, Update×1, Subflow×2 | After-save on Case create without Contact but with a web e-mail: immediate triage Task (and alert for High priority). Async path matches Contacts by SuppliedEmail: one match links the Case and runs the contact snapshot; several matches create a review Task listing candidates; none creates a no-match Task. |
| 3 | `RTF_Task_Before_Save_Workload_Balancer` | 13 | Assignment×5, Decision×5, Loop×1, Get×2 | Before-save on open Task create: defaults a missing due date from Priority, raises Priority for tasks on Opportunities closing within 7 days, and pushes the due date one day out when the owner already has 10+ open tasks that day. |
| 3 | `RTF_Event_Meeting_Preparation` | 13 | Action×1, Assignment×2, Decision×3, Loop×1, Create×1, Get×3, Subflow×2 | After-save on Event create: for meetings with a Contact counts other meetings with that contact within a week and runs the activity snapshot subflow, then creates a preparation Task. Scheduled path 1 day before StartDateTime e-mails the organizer if the preparation Task is still open. |
| 3 | `RTF_Contract_Activation_Checkin` | 14 | Action×1, Assignment×2, Decision×2, Loop×1, Create×4, Get×2, Subflow×2 | After-save when a Contract becomes Activated: totals the account's other active contracts (loop), creates a kickoff or expansion Task and e-mail. Scheduled path 30 days after ActivatedDate: account health subflow + case count since activation decide between an at-risk and a routine check-in Task. |
| 3 | `RTF_Asset_Usage_End_Renewal` | 14 | Assignment×1, Collection Filter/Sort×1, Decision×3, Loop×1, Create×2, Get×4, Subflow×2 | After-save when an Asset gets a UsageEndDate: sums the account's own (non-competitor) assets ending within 90 days (collection filter + loop) and suggests a bundled renewal. Scheduled path 14 days before UsageEndDate creates a renewal Opportunity (if none open) and refreshes the pipeline summary. |
| 3 | `RTF_Account_Became_Customer_Welcome` | 14 | Action×1, Assignment×1, Collection Filter/Sort×1, Decision×3, Loop×1, Create×3, Get×1, Subflow×3 | After-save when an Account's Type changes to a Customer value: if it was a Prospect ($Record__Prior), creates welcome-call Tasks for up to 5 contacts with e-mail (sort + loop + bulk create), otherwise a type-change Task; notifies by e-mail. Async path: contact normalizer + health calculator subflows, low-health Task. |

### Schedule-Triggered Flow (20)

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
| 3 | `SCH_Weekly_Asset_Usage_End_Review` | 13 | Assignment×2, Decision×4, Loop×1, Create×2, Get×2, Subflow×2 | Weekly, per installed/registered Asset with a usage end date: expired assets get a clean-up Task; assets ending within 30 days get a de-duplicated renewal Task whose priority depends on open High cases on the asset and the account health. |
| 3 | `SCH_Daily_Customer_Meeting_Prep` | 17 | Action×1, Assignment×3, Collection Filter/Sort×2, Decision×5, Loop×1, Create×1, Get×2, Subflow×2 | Daily batch (no object): loads Events with a Who starting within 24 hours (soonest 30), skips those already prepared (one Get of recent prep Tasks + collection filter), bulk-creates prep Tasks, then takes an activity snapshot of the soonest meeting's contact and e-mails a warning if that contact has overdue tasks. |
| 3 | `SCH_Daily_Contact_Birthday_Outreach` | 12 | Action×1, Assignment×1, Decision×4, Loop×1, Create×2, Get×1, Subflow×2 | Daily, per Contact with a birthdate: on the birthday, checks (via loop) that no greeting Task was created in the last 300 days, takes an activity snapshot and creates either a greeting Task or a 'resolve open issues first' Task, then e-mails the owner. |
| 3 | `SCH_Weekly_Opportunity_Product_Check` | 16 | Assignment×3, Collection Filter/Sort×1, Decision×4, Loop×1, Create×2, Get×2, Update×1, Subflow×2 | Weekly, per Qualification/Needs Analysis Opportunity: deals without products get a de-duplicated Task; otherwise line items are totalled, discounts over 20% trigger a review Task, and NextStep is updated with product and account pipeline totals. |
| 3 | `SCH_Daily_Idle_Working_Case_Followup` | 14 | Assignment×2, Decision×5, Loop×1, Create×1, Get×1, Update×2, Subflow×2 | Daily, per Case in status Working untouched for 5 days: without open tasks a follow-up Task is created (with contact snapshot); with open tasks, overdue ones are bulk-raised to High and the case priority is raised. |
| 3 | `SCH_Weekly_Inactive_User_Handover` | 15 | Action×1, Assignment×2, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×3, Update×1, Subflow×2 | Weekly batch (no object): finds Standard Users deactivated (modified) in the last 7 days (max 20 per run), moves each user's open Tasks to the first System Administrator via subflow, reassigns their open Opportunities, and records/e-mails a summary. |
| 3 | `SCH_Weekly_Product_Catalog_Audit` | 13 | Action×1, Assignment×4, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×1, Subflow×1 | Weekly batch (no object): checks all active Products for missing product code or family, counts products added in the last 30 days, stores an audit Task (High if gaps found) and e-mails the report. |
| 3 | `SCH_Weekly_New_Lead_Source_Report` | 17 | Action×1, Assignment×6, Collection Filter/Sort×1, Decision×3, Loop×2, Create×2, Get×1, Subflow×1 | Weekly batch (no object): counts unconverted leads created in the last 7 days per lead source, bulk-creates call Tasks for hot, not-yet-contacted leads, stores the report as a Task and e-mails it. |
| 3 | `SCH_Once_Stale_Draft_Contract_Review` | 12 | Action×1, Assignment×3, Decision×3, Loop×1, Create×2, Get×1, Subflow×1 | One-time batch (no object): finds Draft contracts older than 60 days, bulk-creates review Tasks for those whose start date has already passed, counts the rest as pending, and stores/e-mails a summary. |
| 3 | `SCH_Daily_Orphan_Task_Account_Linker` | 14 | Action×1, Assignment×3, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×2, Update×1, Subflow×1 | Daily batch (no object): takes up to 50 newest open Tasks that have a Who but no What, looks up the Contact and links the task to the contact's Account in one bulk update; leads/contacts without account are skipped; summary is e-mailed. |

### Platform Event–Triggered Flow (20)

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
| 3 | `PEF_Batch_Phase_Retry_Planner` | 14 | Assignment×4, Decision×2, Loop×1, Create×2, Get×3, Subflow×2 | Subscribes to BatchApexErrorEvent: picks a phase-specific retry strategy (START / EXECUTE / FINISH), counts earlier retry attempts for the same async job and creates a dated retry Task for an active admin, or an escalated Case once 3 attempts failed. |
| 3 | `PEF_Batch_Error_Request_Correlator` | 13 | Action×1, Assignment×2, Collection Filter/Sort×1, Decision×2, Loop×1, Create×1, Get×3, Subflow×2 | Subscribes to BatchApexErrorEvent: correlates the event's RequestId / AsyncApexJobId with '[Flow Error]' log Tasks of the last hour (collection filter on Description) and, when related logs exist, creates one correlation Task for an admin and e-mails it. |
| 3 | `PEF_Batch_Error_Weekly_Counter` | 15 | Action×1, Assignment×2, Decision×2, Loop×1, Create×1, Delete×1, Get×4, Update×1, Subflow×2 | Subscribes to BatchApexErrorEvent: keeps one counter Task per week and exception type (count in CallDurationInSeconds), deletes counter Tasks older than 8 weeks when a new week starts and e-mails an admin when a type reaches 25 errors in a week. |
| 3 | `PEF_Batch_Error_Keyword_Classifier` | 19 | Assignment×7, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×3, Update×1, Subflow×2 | Subscribes to BatchApexErrorEvent: classifies the error message by keyword (row lock, governor limits, CPU/heap, data validation), closes category Tasks older than 7 days and opens a fresh category Task with remediation advice when none is current. |
| 3 | `PEF_Flow_Error_Namespace_Stats` | 15 | Action×1, Assignment×2, Decision×3, Loop×1, Create×1, Get×4, Update×1, Subflow×2 | Subscribes to FlowExecutionErrorEvent: maintains one open statistics Task per flow namespace (count in CallDurationInSeconds, newest errors first), sums all namespace counters and e-mails an admin every 10 errors while one namespace causes 50%+ of them. |
| 3 | `PEF_Flow_Error_Process_Type_Router` | 18 | Assignment×6, Decision×3, Loop×1, Create×2, Get×3, Update×1, Subflow×2 | Subscribes to FlowExecutionErrorEvent: routes by ProcessType - screen flow errors become a Task for the user who ran the interview, autolaunched / Process Builder errors become one admin-owned Case per flow (recurrences raise all open Cases to High). |
| 3 | `PEF_Flow_Error_Interview_User_Workload` | 16 | Assignment×4, Decision×3, Loop×1, Create×2, Get×4, Subflow×2 | Subscribes to FlowExecutionErrorEvent: checks the user who started the interview - if deactivated, hands their open Tasks to an admin via the bulk-reassign subflow; if active, measures open/overdue Task workload and gives the fix Task to the user or, when overloaded, to an admin. |
| 3 | `PEF_Status_Alert_Admin_Rotation` | 14 | Action×1, Assignment×2, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×3, Subflow×2 | Subscribes to PlatformStatusAlertEvent: load-balances alert Tasks across all active System Administrators - counts each admin's alert Tasks created today (collection filter per admin) and assigns the new Task to the least-loaded one; e-mails on failures. |
| 3 | `PEF_Status_Alert_Deactivated_User_Check` | 15 | Action×1, Assignment×3, Decision×2, Loop×1, Create×2, Get×4, Subflow×2 | Subscribes to PlatformStatusAlertEvent: checks the affected user - active users get a Task to check their integration; for inactive or unknown users it totals the open Opportunities they still own and opens an admin Case (High when pipeline is orphaned). |
| 3 | `PEF_Status_Alert_Component_Recovery` | 13 | Action×1, Assignment×2, Decision×2, Loop×1, Create×1, Get×3, Update×1, Subflow×2 | Subscribes to PlatformStatusAlertEvent: tracks degraded components with one open Task per component/sub-component; a resolved/recovered/success status bulk-completes the open tracking Tasks, a new degradation opens one and e-mails an admin. |

### Screen Flow (20)

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
| 3 | `SCR_Asset_Registration_Wizard` | 16 | Assignment×2, Collection Filter/Sort×1, Decision×2, Loop×1, Create×2, Get×2, Screen×5, Subflow×1 | Register a customer Asset: pick Account and (optional) Contact, enter serial/price/dates, warn about duplicate serial numbers, create the Asset (+ optional install Task) and show the account's installed base sorted by value. |
| 3 | `SCR_Contract_Creation_Wizard` | 17 | Assignment×1, Decision×4, Loop×1, Create×2, Get×1, Update×1, Screen×6, Subflow×1 | Create a Contract for an Account: checks overlapping activated contracts, lets the user proceed or cancel, creates a Draft contract, optionally activates it and creates a countersignature Task. |
| 3 | `SCR_Event_Rescheduler` | 19 | Action×1, Assignment×1, Decision×4, Loop×1, Create×1, Get×2, Update×1, Screen×7, Subflow×1 | Pick one of my upcoming Events, choose a new start/duration and reason, detect calendar conflicts, update the Event, optionally e-mail the attendee and log a completed Task. |
| 3 | `SCR_Lead_BANT_Qualification` | 18 | Assignment×4, Decision×3, Loop×1, Create×1, Get×2, Update×2, Screen×4, Subflow×1 | BANT survey for an open Lead: Budget/Authority/Need/Timeline answers produce a 0-100 score, set Rating/Status and a summary on the Lead, optionally copy the rating to other open leads of the same company, create a call Task for hot leads. |
| 3 | `SCR_Opportunity_Contact_Role_Assignment` | 18 | Assignment×2, Decision×3, Loop×1, Create×2, Get×3, Update×1, Screen×4, Subflow×2 | Pick an open Opportunity, review its current contact roles, then add or update a role (OpportunityContactRole) for a Contact of the account, show the contact's engagement and optionally create a kickoff Task. |
| 3 | `SCR_Account_Health_Check_Console` | 18 | Action×1, Assignment×2, Decision×2, Loop×1, Create×1, Delete×1, Get×3, Screen×4, Subflow×3 | Pick an Account: shows the health score (subflow), pipeline summary (subflow) and open/high-priority case counts, then lets the user create an action-plan Task (replacing earlier open plans), e-mail the account owner, or do nothing. |
| 3 | `SCR_Task_Bulk_Reassign_Console` | 18 | Action×1, Assignment×2, Decision×3, Loop×1, Create×1, Get×2, Screen×6, Subflow×2 | UI for AUT_Task_Bulk_Reassign: pick source and target users, preview open/overdue/high-priority task counts, confirm, run the reassignment subflow, e-mail the new owner and log an audit Task. |
| 3 | `SCR_Opportunity_Clone_Lite` | 19 | Assignment×2, Decision×3, Loop×2, Create×3, Get×3, Screen×4, Subflow×2 | Clone an Opportunity with a new name/stage/close date/amount and optionally copy its product lines and contact roles (bulk creates), then show the account's refreshed pipeline. |
| 3 | `SCR_Case_Duplicate_Review` | 18 | Assignment×2, Collection Filter/Sort×1, Decision×3, Loop×1, Create×1, Get×2, Update×2, Screen×5, Subflow×1 | Pick an open Case, find likely duplicates on the same Account (same contact or same subject) with a collection filter, then close one as duplicate or link it as a child case (no real merge) and log a review Task. |
| 3 | `SCR_Opportunity_Product_Adder` | 20 | Assignment×3, Decision×4, Loop×1, Create×1, Get×4, Update×1, Screen×5, Subflow×1 | Pick an open Opportunity and a Product2; resolves the price book (opportunity's or the standard one) and its PricebookEntry, then increases the quantity of an existing line or creates a new OpportunityLineItem. |

## Генератор

XML собран генератором (`flowgen/`, Python). Модули по типам: `autolaunched*.py`, `record_triggered*.py`, `scheduled*.py`, `platform_event*.py`, `screen*.py`. Цифра в имени — номер набора. Генератор находит модули сам.

```bash
python3 flowgen/build.py --check -v          # только проверка
python3 flowgen/build.py /tmp/out            # сборка в пустую папку (не в корень репозитория)
python3 flowgen/make_readme.py .             # обновить README и package.xml
```

Генератор проверяет:
- связи коннекторов и достижимость элементов;
- ссылки на ресурсы и `$Record__Prior`;
- входы и выходы subflow;
- число элементов (10–20);
- picklist в формулах и условиях, `BR()`, ссылки на loop-элементы в формулах;
- Wait вне autolaunched flow.
