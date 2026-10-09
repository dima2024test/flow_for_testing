"""Regenerates README.md and manifest/package.xml in a pack directory: python3 make_readme.py <pack_dir>"""
import os, sys, json

PACK = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "summary.json")))

names = sorted(f[:-len(".flow-meta.xml")] for f in os.listdir(os.path.join(PACK, "force-app/main/default/flows")))
os.makedirs(os.path.join(PACK, "manifest"), exist_ok=True)
members = "\n".join(f"        <members>{n}</members>" for n in names)
open(os.path.join(PACK, "manifest/package.xml"), "w").write(f'''<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
{members}
        <name>Flow</name>
    </types>
    <version>62.0</version>
</Package>
''')

ru = {"Autolaunched (No Trigger)": "Autolaunched Flow (No Trigger)", "Record-Triggered": "Record-Triggered Flow",
      "Schedule-Triggered": "Schedule-Triggered Flow", "Platform Event-Triggered": "Platform Event–Triggered Flow", "Screen": "Screen Flow"}
short = {"actionCalls": "Action", "assignments": "Assignment", "collectionProcessors": "Collection Filter/Sort", "decisions": "Decision",
         "loops": "Loop", "recordCreates": "Create", "recordDeletes": "Delete", "recordLookups": "Get", "recordUpdates": "Update",
         "screens": "Screen", "subflows": "Subflow", "waits": "Wait"}
rows = {}
for s in S:
    setn = "".join(ch for ch in s["module"] if ch.isdigit()) or "1"
    k = ", ".join(f"{short[t]}×{c}" for t, c in sorted(s["kinds"].items()))
    rows.setdefault(s["group"], []).append(f"| {setn} | `{s['api']}` | {s['count']} | {k} | {s['description']} |")
body = "\n\n".join(f"### {ru[g]} ({len(r)})\n\n| Набор | Flow | Элементов | Состав | Что делает |\n|---|---|---|---|---|\n" + "\n".join(r)
                   for g, r in rows.items())
waits = ", ".join(f"`{s['api']}`" for s in S if "waits" in s["kinds"])
total = len(S)
per = total // 5

readme = f'''# Flow Demo Pack: {total} flow для Salesforce

5 типов × {per} flow, API 62.0, все в статусе **Active**. Используются только стандартные объекты и поля: нет кастомных полей, объектов, email templates, custom notification types, очередей, record types или approval processes.

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

- **Fault path**: почти каждый DML, Get Records, Action и Wait имеет fault connector на логирование `$Flow.FaultMessage`: subflow `AUT_Log_Flow_Error`, а в platform-event flow — прямое создание Task. В screen flow после логирования показывается экран ошибки. Before-save flow fault path не нужен.
- **Вложенные flow**: autolaunched-утилиты (health score, pipeline summary, activity snapshot, normalizer, lead scoring, warranty check, duplicate finder, data quality report и др.) вызываются из autolaunched, record-triggered, scheduled и screen flow. Глубина вложенности доходит до 4 уровней.
- **Platform-event flow не могут содержать Subflow**: это ограничение платформы. Поэтому вместо вызова логгера они сами создают Task `[Flow Error] …` (в том числе в fault path).
- **Wait (Pause)** есть только в autolaunched flow: {waits}. Другие типы его не поддерживают. Эти flow не вызываются как subflow; их запускают через REST, Apex или из другого autolaunched flow.
- В record-triggered flow вместо Wait используются **Scheduled Paths** (в том числе с отрицательным смещением, «за N дней до») и **Async Path**. Есть before-save, after-save и before-delete flow; `$Record__Prior` используется в after-save update flow.
- **Platform-event flow** подписаны на стандартные события `BatchApexErrorEvent`, `FlowExecutionErrorEvent` и `PlatformStatusAlertEvent`.

## Состав

{body}

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
- Wait вне autolaunched flow, Subflow в platform-event flow;
- checkbox-поля на экранах (`isRequired` должен быть true), `limit` в сортировке, async path на update без условия изменения.
'''
open(os.path.join(PACK, "README.md"), "w").write(readme)
print("README + package.xml:", len(names), "flows")
