import os, re, sys, json, shutil
import xml.etree.ElementTree as ET
import autolaunched, record_triggered, scheduled, platform_event, screen

OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/flow-pack"
FLOWDIR = os.path.join(OUT, "force-app/main/default/flows")
NS = "{http://soap.sforce.com/2006/04/metadata}"

groups = {"Autolaunched (No Trigger)": autolaunched.ALL, "Record-Triggered": record_triggered.ALL,
          "Schedule-Triggered": scheduled.ALL, "Platform Event-Triggered": platform_event.ALL, "Screen": screen.ALL}

if os.path.exists(OUT):
    shutil.rmtree(OUT)
os.makedirs(FLOWDIR)

flows = {}
for g, fns in groups.items():
    for fn in fns:
        f = fn()
        f.group = g
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
            if base not in ("$Record", "$Flow", "$User"):
                errors.append(f"{api}: odd global {r}")
            if base == "$Record" and f.kind in ("auto", "screen"):
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
    summary.append(dict(api=api, group=f.group, label=f.label, description=f.description, count=cnt, kinds=kinds, fault=has_fault))

for e in errors:
    print("ERROR", e)
json.dump(summary, open(os.path.join("/home/claude/flowgen", "summary.json"), "w"), indent=1)
for s in summary:
    print(f"{s['group'][:12]:12} {s['api']:42} {s['count']:3} fault={s['fault']} {s['kinds']}")
print("errors:", len(errors))
