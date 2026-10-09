"""Tiny DSL that emits Salesforce Flow metadata XML (API 62.0) with WSDL field ordering."""
from xml.sax.saxutils import escape
from collections import deque

API = "62.0"
LAYOUT = "auto"   # "auto" -> AUTO_LAYOUT_CANVAS with Go To connectors; "free" -> FREE_FORM_CANVAS


class R:
    """element reference"""
    def __init__(self, ref):
        self.ref = ref


class D:
    """date literal"""
    def __init__(self, v):
        self.v = v


def value_xml(v):
    if isinstance(v, R):
        return f"<elementReference>{escape(v.ref)}</elementReference>"
    if isinstance(v, D):
        return f"<dateValue>{v.v}</dateValue>"
    if isinstance(v, bool):
        return f"<booleanValue>{'true' if v else 'false'}</booleanValue>"
    if isinstance(v, (int, float)):
        return f"<numberValue>{float(v)}</numberValue>"
    return f"<stringValue>{escape(str(v))}</stringValue>"


def tag(name, inner):
    return f"<{name}>{inner}</{name}>"


def conn(name, target):
    if not target:
        return ""
    return tag(name, tag("targetReference", target))


def cond_xml(c):
    left, op, val = c
    return tag("conditions", tag("leftValueReference", left) + tag("operator", op) + tag("rightValue", value_xml(val)))


def filt_xml(f, tagname="filters"):
    field, op, val = f
    return tag(tagname, tag("field", field) + tag("operator", op) + tag("value", value_xml(val)))


class Flow:
    def __init__(self, api, label, kind, description):
        self.api, self.label, self.kind, self.description = api, label, kind, description
        self.res = {k: [] for k in ["choices", "constants", "dynamicChoiceSets", "formulas", "textTemplates", "variables"]}
        self.elements = []  # (toptag, name, header_extra, body, targets)
        self.names = set()
        self.start_xml = None
        self.start_targets = []
        self.screen_fields = set()
        self.inputs, self.outputs = {}, {}

    # ---------- resources ----------
    def _reg(self, name):
        assert name not in self.names, f"{self.api}: duplicate name {name}"
        assert len(name) <= 80
        self.names.add(name)

    def var(self, name, dt, coll=False, inp=False, out=False, obj=None, scale=None, default=None):
        self._reg(name)
        x = tag("name", name) + tag("dataType", dt) + tag("isCollection", str(coll).lower()) \
            + tag("isInput", str(inp).lower()) + tag("isOutput", str(out).lower())
        if obj:
            x += tag("objectType", obj)
        if scale is not None:
            x += tag("scale", str(scale))
        if default is not None:
            x += tag("value", value_xml(default))
        self.res["variables"].append(tag("variables", x))
        if inp:
            self.inputs[name] = dt
        if out:
            self.outputs[name] = dt
        return R(name)

    def formula(self, name, dt, expr, scale=None):
        self._reg(name)
        x = tag("name", name) + tag("dataType", dt) + tag("expression", escape(expr))
        if scale is not None:
            x += tag("scale", str(scale))
        self.res["formulas"].append(tag("formulas", x))
        return R(name)

    def tt(self, name, text):
        self._reg(name)
        self.res["textTemplates"].append(tag("textTemplates", tag("name", name) + tag("isViewedAsPlainText", "true") + tag("text", escape(text))))
        return R(name)

    def const(self, name, dt, v):
        self._reg(name)
        self.res["constants"].append(tag("constants", tag("name", name) + tag("dataType", dt) + tag("value", value_xml(v))))
        return R(name)

    def choice(self, name, text, v):
        self._reg(name)
        self.res["choices"].append(tag("choices", tag("name", name) + tag("choiceText", escape(text)) + tag("dataType", "String") + tag("value", value_xml(v))))

    def picklist_set(self, name, obj, field):
        self._reg(name)
        self.res["dynamicChoiceSets"].append(tag("dynamicChoiceSets", tag("name", name) + tag("dataType", "Picklist")
                                                 + '<displayField xsi:nil="true"/><object xsi:nil="true"/>'
                                                 + tag("picklistField", field) + tag("picklistObject", obj)))

    def record_set(self, name, obj, display, value_field, filters=(), sort=None, order="Asc", limit=200):
        self._reg(name)
        x = tag("name", name) + tag("dataType", "String") + tag("displayField", display)
        if filters:
            x += tag("filterLogic", "and") + "".join(filt_xml(f) for f in filters)
        x += tag("limit", str(limit)) + tag("object", obj)
        if sort:
            x += tag("sortField", sort) + tag("sortOrder", order)
        x += tag("valueField", value_field)
        self.res["dynamicChoiceSets"].append(tag("dynamicChoiceSets", x))

    # ---------- elements ----------
    def _el(self, toptag, name, label, body, targets, subtype=None):
        self._reg(name)
        self.elements.append(dict(tag=toptag, name=name, label=label, body=body, targets=[t for t in targets if t], subtype=subtype))
        return R(name)

    @staticmethod
    def lbl(name):
        return name.replace("_", " ")

    def assign(self, name, items, nxt=None):
        body = "".join(tag("assignmentItems", tag("assignToReference", a) + tag("operator", op) + tag("value", value_xml(v))) for a, op, v in items)
        body += conn("connector", nxt)
        return self._el("assignments", name, self.lbl(name), body, [nxt])

    def decision(self, name, rules, default=None, default_label="Default Outcome"):
        """rules: list of (rule_name, conds, target, logic)"""
        body = conn("defaultConnector", default) + tag("defaultConnectorLabel", escape(default_label))
        targets = [default]
        for r in rules:
            rname, conds, target = r[0], r[1], r[2]
            logic = r[3] if len(r) > 3 else "and"
            self._reg(rname)
            body += tag("rules", tag("name", rname) + tag("conditionLogic", logic) + "".join(cond_xml(c) for c in conds)
                        + conn("connector", target) + tag("label", self.lbl(rname)))
            targets.append(target)
        return self._el("decisions", name, self.lbl(name), body, targets)

    def get(self, name, obj, filters, nxt=None, fault=None, first=False, sort=None, order="Asc", logic="and"):
        body = tag("assignNullValuesIfNoRecordsFound", "false") + conn("connector", nxt) + conn("faultConnector", fault)
        if filters:
            body += tag("filterLogic", logic) + "".join(filt_xml(f) for f in filters)
        body += tag("getFirstRecordOnly", str(first).lower()) + tag("object", obj)
        if sort:
            body += tag("sortField", sort) + tag("sortOrder", order)
        body += tag("storeOutputAutomatically", "true")
        return self._el("recordLookups", name, self.lbl(name), body, [nxt, fault])

    def create(self, name, obj=None, fields=None, nxt=None, fault=None, id_to=None, input_ref=None):
        body = ""
        if id_to:
            body += tag("assignRecordIdToReference", id_to)
        body += conn("connector", nxt) + conn("faultConnector", fault)
        if input_ref:
            body += tag("inputReference", input_ref)
        else:
            body += "".join(tag("inputAssignments", tag("field", k) + tag("value", value_xml(v))) for k, v in fields.items())
            body += tag("object", obj)
            body += tag("storeOutputAutomatically", "true") if not id_to else ""
        return self._el("recordCreates", name, self.lbl(name), body, [nxt, fault])

    def update(self, name, obj=None, filters=None, fields=None, nxt=None, fault=None, input_ref=None):
        body = conn("connector", nxt) + conn("faultConnector", fault)
        if input_ref:
            body += tag("inputReference", input_ref)
        else:
            body += tag("filterLogic", "and") + "".join(filt_xml(f) for f in filters)
            body += "".join(tag("inputAssignments", tag("field", k) + tag("value", value_xml(v))) for k, v in fields.items())
            body += tag("object", obj)
        return self._el("recordUpdates", name, self.lbl(name), body, [nxt, fault])

    def delete(self, name, obj=None, filters=None, nxt=None, fault=None, input_ref=None):
        body = conn("connector", nxt) + conn("faultConnector", fault)
        if input_ref:
            body += tag("inputReference", input_ref)
        else:
            body += tag("filterLogic", "and") + "".join(filt_xml(f) for f in filters) + tag("object", obj)
        return self._el("recordDeletes", name, self.lbl(name), body, [nxt, fault])

    def loop(self, name, coll, nxt, done, var=None, order="Asc"):
        body = ""
        if var:
            body += tag("assignNextValueToReference", var)
        body += tag("collectionReference", coll) + tag("iterationOrder", order) + conn("nextValueConnector", nxt) + conn("noMoreValuesConnector", done)
        return self._el("loops", name, self.lbl(name), body, [nxt, done])

    def subflow(self, name, flow, inputs, outputs=None, nxt=None):
        if self.kind == "pef":
            # Platform event-triggered flows cannot contain Subflow elements: inline the logger as a Task insert.
            assert flow == "AUT_Log_Flow_Error" and not outputs, f"{self.api}: subflow {flow} not allowed in PE flow"
            return self._inline_log(name, inputs, nxt)
        body = conn("connector", nxt) + tag("flowName", flow)
        body += "".join(tag("inputAssignments", tag("name", k) + tag("value", value_xml(v))) for k, v in inputs.items())
        for k, v in (outputs or {}).items():
            body += tag("outputAssignments", tag("assignToReference", v) + tag("name", k))
        el = self._el("subflows", name, self.lbl(name), body, [nxt])
        self.elements[-1]["subflow"] = (flow, list(inputs), list((outputs or {}).keys()))
        return el

    def _inline_log(self, name, inputs, nxt):
        def fx(v):
            if isinstance(v, R):
                return "BLANKVALUE({!" + v.ref + "}, '')"
            return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"
        def tt(v):
            return "{!" + v.ref + "}" if isinstance(v, R) else str(v)
        sev = inputs.get("inSeverity", "Error")
        subj = self.formula(f"fx{name}_Subject", "String",
                            f"LEFT('[Flow Error] ' & {fx(inputs.get('inFlowName', self.api))} & ' (' & {fx(sev)} & ')', 255)")
        desc = self.tt(f"tt{name}_Details", f"Flow: {tt(inputs.get('inFlowName', self.api))}\nSeverity: {tt(sev)}\n"
                                            f"Record / reference: {tt(inputs.get('inRecordId', ''))}\nLogged at: {{!$Flow.CurrentDateTime}}\n\n"
                                            f"Error message:\n{tt(inputs.get('inErrorMessage', ''))}")
        fields = {"Subject": subj, "Description": desc, "Priority": "High" if sev == "Critical" else "Normal",
                  "Status": "Not Started", "ActivityDate": R("$Flow.CurrentDate")}
        if isinstance(inputs.get("inOwnerId"), R):
            fields["OwnerId"] = inputs["inOwnerId"]
        return self.create(name, "Task", fields, nxt=nxt, fault=None if name == "Log_Fault" else "Log_Fault")

    def email(self, name, to, subject, body_v, nxt=None, fault=None):
        body = tag("actionName", "emailSimple") + tag("actionType", "emailSimple") + conn("connector", nxt) + conn("faultConnector", fault)
        body += tag("flowTransactionModel", "CurrentTransaction")
        for k, v in (("emailAddresses", to), ("emailSubject", subject), ("emailBody", body_v)):
            body += tag("inputParameters", tag("name", k) + tag("value", value_xml(v)))
        body += tag("storeOutputAutomatically", "true")
        return self._el("actionCalls", name, self.lbl(name), body, [nxt, fault])

    def wait(self, name, event_name, base_time, offset, unit, nxt, fault=None):
        self._reg(event_name)
        body = tag("defaultConnectorLabel", "Default Path") + conn("faultConnector", fault)
        ev = tag("name", event_name) + tag("conditionLogic", "and") + conn("connector", nxt) + tag("eventType", "AlarmEvent")
        for k, v in (("AlarmTime", base_time), ("TimeOffset", offset), ("TimeOffsetUnit", unit)):
            ev += tag("inputParameters", tag("name", k) + tag("value", value_xml(v)))
        ev += tag("label", self.lbl(event_name))
        body += tag("waitEvents", ev)
        return self._el("waits", name, self.lbl(name), body, [nxt, fault])

    def filter_coll(self, name, coll, obj, conds, nxt, logic="and"):
        cur = f"currentItem_{name}"
        self.var(cur, "SObject", obj=obj)
        body = tag("assignNextValueToReference", cur) + tag("collectionProcessorType", "FilterCollectionProcessor") \
            + tag("collectionReference", coll) + tag("conditionLogic", logic) \
            + "".join(cond_xml((f"{cur}.{f}", op, v)) for f, op, v in conds) + conn("connector", nxt)
        return self._el("collectionProcessors", name, self.lbl(name), body, [nxt], subtype="FilterCollectionProcessor")

    def sort_coll(self, name, coll, field, order, nxt, limit=None):
        body = tag("collectionProcessorType", "SortCollectionProcessor") + tag("collectionReference", coll) + conn("connector", nxt)
        if limit:
            body += tag("limit", str(int(limit)))
        body += tag("sortOptions", tag("doesPutEmptyStringAndNullFirst", "false") + tag("sortField", field) + tag("sortOrder", order))
        return self._el("collectionProcessors", name, self.lbl(name), body, [nxt], subtype="SortCollectionProcessor")

    # screen fields
    def f_text(self, name, html):
        self._reg(name)
        return tag("fields", tag("name", name) + tag("fieldText", escape(html)) + tag("fieldType", "DisplayText"))

    def f_input(self, name, label, dt, required=False, scale=None, default=None):
        self._reg(name)
        if dt == "Boolean":
            required = True  # platform rule: checkbox inputs must have isRequired=true
        x = tag("name", name) + tag("dataType", dt)
        if default is not None:
            x += tag("defaultValue", value_xml(default))
        x += tag("fieldText", escape(label)) + tag("fieldType", "InputField") + tag("isRequired", str(required).lower())
        if scale is not None:
            x += tag("scale", str(scale))
        return tag("fields", x)

    def f_area(self, name, label, required=False):
        self._reg(name)
        return tag("fields", tag("name", name) + tag("fieldText", escape(label)) + tag("fieldType", "LargeTextArea") + tag("isRequired", str(required).lower()))

    def f_choice(self, name, label, choices, ftype="DropdownBox", required=True, default_choice=None):
        self._reg(name)
        x = tag("name", name) + "".join(tag("choiceReferences", c) for c in choices) + tag("dataType", "String")
        if default_choice:
            x += tag("defaultSelectedChoiceReference", default_choice)
        x += tag("fieldText", escape(label)) + tag("fieldType", ftype) + tag("isRequired", str(required).lower())
        return tag("fields", x)

    def screen(self, name, fields, nxt=None, allow_back=True):
        body = tag("allowBack", str(allow_back).lower()) + tag("allowFinish", "true") + tag("allowPause", "false") + conn("connector", nxt)
        body += "".join(fields) + tag("showFooter", "true") + tag("showHeader", "true")
        return self._el("screens", name, self.lbl(name), body, [nxt])

    # ---------- start ----------
    def start(self, nxt=None, obj=None, trigger=None, record_trigger=None, filters=(), changed=False,
              schedule=None, paths=(), filter_logic="and"):
        """paths: list of dicts {name,label,target,num,unit,field,source} or {'async':target}"""
        x = conn("connector", nxt)
        if changed:
            x += tag("doesRequireRecordChangedToMeetCriteria", "true")
        if filters:
            x += tag("filterLogic", filter_logic) + "".join(filt_xml(f) for f in filters)
        if obj:
            x += tag("object", obj)
        if record_trigger:
            x += tag("recordTriggerType", record_trigger)
        if schedule:
            freq, date, time = schedule
            x += tag("schedule", tag("frequency", freq) + tag("startDate", date) + tag("startTime", time))
        targets = [nxt]
        for p in paths:
            if "async" in p:
                x += tag("scheduledPaths", conn("connector", p["async"]) + tag("pathType", "AsyncAfterCommit"))
                targets.append(p["async"])
            else:
                self._reg(p["name"])
                y = tag("name", p["name"]) + conn("connector", p["target"]) + tag("label", p["label"]) \
                    + tag("offsetNumber", str(p["num"])) + tag("offsetUnit", p["unit"])
                if p.get("field"):
                    y += tag("recordField", p["field"])
                y += tag("timeSource", p.get("source", "RecordField"))
                x += tag("scheduledPaths", y)
                targets.append(p["target"])
        if trigger:
            x += tag("triggerType", trigger)
        self.start_body = x
        self.start_targets = [t for t in targets if t]

    # ---------- layout & emit ----------
    def _layout(self):
        by = {e["name"]: e for e in self.elements}
        level = {}
        q = deque()
        for t in self.start_targets:
            if t not in level:
                level[t] = 1
                q.append(t)
        while q:
            n = q.popleft()
            for t in by[n]["targets"]:
                if t not in level:
                    level[t] = level[n] + 1
                    q.append(t)
        for e in self.elements:
            level.setdefault(e["name"], max(level.values(), default=0) + 1)
        cols = {}
        pos = {}
        for e in self.elements:
            lv = level[e["name"]]
            c = cols.get(lv, 0)
            cols[lv] = c + 1
            pos[e["name"]] = (50 + c * 264, 182 + (lv - 1) * 168)
        return pos, level

    def xml(self):
        pos, _ = self._layout()
        gotos = set()
        self.layout_anomalies = []
        if LAYOUT == "auto":
            import autolayout
            gotos, self.layout_anomalies = autolayout.compute(self)
            pos = {n: (0, 0) for n in pos}
        self.goto_count = len(gotos)
        groups = {}
        for e in self.elements:
            x, y = pos[e["name"]]
            body = autolayout.apply(e["body"], e["name"], gotos) if gotos else e["body"]
            head = tag("name", e["name"]) + (tag("elementSubtype", e["subtype"]) if e["subtype"] else "") + tag("label", escape(e["label"])) \
                + tag("locationX", str(x)) + tag("locationY", str(y))
            groups.setdefault(e["tag"], []).append(tag(e["tag"], head + body))
        pmv = "".join(tag("processMetadataValues", tag("name", k) + tag("value", value_xml(v))) for k, v in
                      (("BuilderType", "LightningFlowBuilder"), ("CanvasMode", "AUTO_LAYOUT_CANVAS" if LAYOUT == "auto" else "FREE_FORM_CANVAS"), ("OriginBuilderType", "LightningFlowBuilder")))
        order = ["actionCalls", "apiVersion", "assignments", "choices", "collectionProcessors", "constants", "decisions",
                 "description", "dynamicChoiceSets", "environments", "formulas", "interviewLabel", "label", "loops",
                 "processMetadataValues", "processType", "recordCreates", "recordDeletes", "recordLookups", "recordUpdates",
                 "screens", "start", "status", "subflows", "textTemplates", "variables", "waits"]
        out = []
        for k in order:
            if k == "apiVersion":
                out.append(tag("apiVersion", API))
            elif k == "description":
                out.append(tag("description", escape(self.description)))
            elif k == "environments":
                out.append(tag("environments", "Default"))
            elif k == "interviewLabel":
                out.append(tag("interviewLabel", escape(self.label + " {!$Flow.CurrentDateTime}")))
            elif k == "label":
                out.append(tag("label", escape(self.label)))
            elif k == "processMetadataValues":
                out.append(pmv)
            elif k == "processType":
                out.append(tag("processType", "Flow" if self.kind == "screen" else "AutoLaunchedFlow"))
            elif k == "start":
                sb = autolayout.apply(self.start_body, "__START__", gotos) if gotos else self.start_body
                out.append(tag("start", tag("locationX", "0" if LAYOUT == "auto" else "50") + tag("locationY", "0") + sb))
            elif k == "status":
                out.append(tag("status", "Active"))
            elif k in self.res:
                out.extend(self.res[k])
            else:
                out.extend(groups.get(k, []))
        body = "".join(out)
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<Flow xmlns="http://soap.sforce.com/2006/04/metadata" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' + body + "</Flow>\n")

    def element_count(self):
        return len(self.elements)
