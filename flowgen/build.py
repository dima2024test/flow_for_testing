import os, re, sys, json, shutil
import xml.etree.ElementTree as ET
import importlib, glob

# usage: python3 build.py <out_dir>   |   python3 build.py --check   (validate only, no files written)
CHECK = "--check" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = args[0] if args else "/home/claude/flow-pack-build"
FLOWDIR = os.path.join(OUT, "force-app/main/default/flows")
NS = "{http://soap.sforce.com/2006/04/metadata}"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TYPES = [("autolaunched", "Autolaunched (No Trigger)"), ("record_triggered", "Record-Triggered"), ("scheduled", "Schedule-Triggered"),
         ("platform_event", "Platform Event-Triggered"), ("screen", "Screen")]
groups = {}
for prefix, g in TYPES:
    mods = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(HERE, prefix + "*.py")))
    mods = [m for m in mods if re.fullmatch(prefix + r"\d*", m)]
    mods.sort(key=lambda m: int(m[len(prefix):] or 1))
    groups[g] = []
    for m in mods:
        try:
            groups[g] += [(m, fn) for fn in importlib.import_module(m).ALL]
        except Exception as ex:
            print(f"ERROR module {m} failed to import: {ex!r}")

PICKLISTS = {"Type", "Status", "Priority", "StageName", "LeadSource", "Rating", "Industry", "Origin", "Reason", "ForecastCategoryName", "Salutation"}

if not CHECK:
    if os.path.exists(os.path.join(OUT, ".git")):
        sys.exit("refusing to wipe a git repo; pass a scratch out_dir")
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(FLOWDIR)

flows = {}
for g, fns in groups.items():
    for mod, fn in fns:
        try:
            f = fn()
        except Exception as ex:
            import traceback
            print(f"ERROR {mod}.{fn.__name__} failed: {ex!r}\n" + traceback.format_exc(limit=3))
            continue
        f.group = g
        f.module = mod
        if f.api in flows:
            print(f"ERROR duplicate flow api name {f.api} ({mod})")
            continue
        flows[f.api] = f

errors = []
NAME_RE = re.compile(r"^[A-Za-z](?!.*__)[A-Za-z0-9_]*(?<!_)$")
ELEMENT_TAGS = {"actionCalls", "assignments", "collectionProcessors", "decisions", "loops", "recordCreates", "recordDeletes",
                "recordLookups", "recordUpdates", "screens", "subflows", "waits"}
summary = []
for api, f in flows.items():
    xml = f.xml()
    path = os.path.join(FLOWDIR, f"{api}.flow-meta.xml")
    import xml.dom.minidom as md
    pretty = md.parseString(xml).toprettyxml(indent="    ")
    pretty = "\n".join(l for l in pretty.splitlines() if l.strip())
    pretty = pretty.replace('<?xml version="1.0" ?>', '<?xml version="1.0" encoding="UTF-8"?>', 1) + "\n"
    if not CHECK:
        open(path, "w").write(pretty)
    root = ET.fromstring(xml)
    # names
    for n in f.names | {api}:
        if not NAME_RE.match(n):
            errors.append(f"{api}: bad name {n}")
    elements = {e["name"]: e for e in f.elements}
    # targets
    for e in f.elements:
        for t in e["targets"]:
            if t not in elements:
                errors.append(f"{api}: {e['name']} -> missing target {t}")
    for t in f.start_targets:
        if t not in elements:
            errors.append(f"{api}: start -> missing {t}")
    # reachability
    seen, stack = set(), list(f.start_targets)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(elements[n]["targets"])
    unreachable = set(elements) - seen
    if unreachable:
        errors.append(f"{api}: unreachable {unreachable}")
    # references
    refs = set()
    for el in root.iter():
        if el.tag in (NS + "elementReference", NS + "leftValueReference", NS + "assignToReference", NS + "collectionReference",
                      NS + "assignNextValueToReference", NS + "inputReference", NS + "assignRecordIdToReference"):
            refs.add(el.text)
        if el.text and "{!" in el.text:
            refs.update(re.findall(r"\{!([^}]+)\}", el.text))
    for r in refs:
        base = r.split(".")[0]
        if base.startswith("$"):
            if base not in ("$Record", "$Record__Prior", "$Flow", "$User"):
                errors.append(f"{api}: odd global {r}")
            if base == "$Record__Prior" and "<recordTriggerType>Update</recordTriggerType>" not in xml and "<recordTriggerType>CreateAndUpdate</recordTriggerType>" not in xml:
                errors.append(f"{api}: $Record__Prior without update trigger")
            if base.startswith("$Record") and f.kind in ("auto", "screen"):
                errors.append(f"{api}: $Record used in {f.kind}")
            continue
        if base not in f.names:
            errors.append(f"{api}: undefined reference {r}")
    # subflow IO
    for e in f.elements:
        if "subflow" in e:
            target, ins, outs = e["subflow"]
            if target not in flows:
                errors.append(f"{api}: subflow target {target} missing")
                continue
            t = flows[target]
            for i in ins:
                if i not in t.inputs:
                    errors.append(f"{api}: {target} has no input {i}")
            for o in outs:
                if o not in t.outputs:
                    errors.append(f"{api}: {target} has no output {o}")
            if any(x["tag"] == "waits" for x in t.elements):
                errors.append(f"{api}: calls subflow with wait {target}")
    # counts
    cnt = len(f.elements)
    if not 10 <= cnt <= 20:
        errors.append(f"{api}: element count {cnt}")
    kinds = {}
    for e in f.elements:
        kinds[e["tag"]] = kinds.get(e["tag"], 0) + 1
    has_fault = "<faultConnector>" in xml
    if f.kind == "rtf" and "RecordBeforeSave" in xml:
        bad = {e["tag"] for e in f.elements} - {"assignments", "decisions", "recordLookups", "loops"}
        if bad:
            errors.append(f"{api}: before-save has {bad}")
    # lint
    for an in getattr(f, "layout_anomalies", []):
        errors.append(f"{api}: auto-layout: {an}")
    if "BR()" in xml:
        errors.append(f"{api}: BR() in formula")
    if len(api) > 80 or len(f.label) > 255:
        errors.append(f"{api}: name/label too long")
    for el in root.iter(NS + "formulas"):
        expr = el.find(NS + "expression").text or ""
        for m in re.findall(r"\{!(Loop_[A-Za-z0-9_]+)\.", expr):
            errors.append(f"{api}: formula references loop element {m}; use loop var")
        for m in re.findall(r"\{!([A-Za-z0-9_$]+)\.([A-Za-z]+)\}", expr):
            if m[1] in PICKLISTS and f"TEXT({{!{m[0]}.{m[1]}}})" not in expr and f"ISPICKVAL({{!{m[0]}.{m[1]}}}" not in expr:
                errors.append(f"{api}: picklist {m[0]}.{m[1]} in formula without TEXT()")
    for el in root.iter():
        if el.tag in (NS + "conditions", NS + "filters"):
            fld = el.find(NS + "leftValueReference")
            fld = fld.text if fld is not None else (el.find(NS + "field").text if el.find(NS + "field") is not None else "")
            op = el.find(NS + "operator").text
            if fld.split(".")[-1] in PICKLISTS and op in ("Contains", "StartsWith", "EndsWith") and ("$Record" in fld or el.find(NS + "field") is not None):
                errors.append(f"{api}: text operator {op} on picklist {fld}")
    if f.kind == "pef" and any(e["tag"] == "subflows" for e in f.elements):
        errors.append(f"{api}: Subflow element in platform event-triggered flow")
    if re.search(r"<limit><numberValue>", xml):
        errors.append(f"{api}: limit must be a plain integer")
    for el in root.iter(NS + "fields"):
        dt = el.find(NS + "dataType"); req = el.find(NS + "isRequired")
        if dt is not None and dt.text == "Boolean" and req is not None and req.text == "false":
            errors.append(f"{api}: boolean screen input with isRequired=false")
    if "<pathType>AsyncAfterCommit</pathType>" in xml and re.search(r"<recordTriggerType>(Update|CreateAndUpdate)</recordTriggerType>", xml) \
            and "<doesRequireRecordChangedToMeetCriteria>true" not in xml and "<operator>IsChanged</operator>" not in xml:
        errors.append(f"{api}: async path on update needs 'changed' or IsChanged filter")
    if f.kind != "auto" and any(e["tag"] == "waits" for e in f.elements):
        errors.append(f"{api}: wait outside autolaunched")
    if f.kind == "screen" and not any(e["tag"] == "screens" for e in f.elements):
        errors.append(f"{api}: screen flow without screens")
    summary.append(dict(api=api, module=f.module, group=f.group, label=f.label, description=f.description, count=cnt, kinds=kinds, fault=has_fault))

for e in errors:
    print("ERROR", e)
if not CHECK:
    json.dump(summary, open(os.path.join(HERE, "summary.json"), "w"), indent=1)
for s in summary:
    if CHECK and "-v" not in sys.argv:
        continue
    print(f"{s['group'][:12]:12} {s['api']:42} {s['count']:3} fault={s['fault']} {s['kinds']}")
print("flows:", len(flows), "errors:", len(errors))
