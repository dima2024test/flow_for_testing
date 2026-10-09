"""Auto-layout support: decides which connectors must be marked <isGoTo>true</isGoTo>.

Flow Builder's auto-layout renders a flow as a structured tree: every branching element
(Decision, Wait, Start with scheduled/async paths) has branches that either end or re-join at
one merge point; a Loop's "for each" branch returns to the loop; a fault path is its own
branch that must end. Any connector that jumps to an element already drawn elsewhere has to be
a Go To connector. The merge point of a branching element is its immediate post-dominator over
the non-fault graph.
"""
import re

CONN_RE = re.compile(r"<(connector|defaultConnector|faultConnector|nextValueConnector|noMoreValuesConnector)>"
                     r"<targetReference>([^<]+)</targetReference></\1>")
END = "__END__"
START = "__START__"


def edges_of(body):
    """Ordered list of (kind, target) as they appear in the element body."""
    return [(m.group(1), m.group(2)) for m in CONN_RE.finditer(body)]


def compute(flow):
    nodes = {e["name"]: e for e in flow.elements}
    kinds = {e["name"]: e["tag"] for e in flow.elements}
    edges = {n: edges_of(e["body"]) for n, e in nodes.items()}
    edges[START] = edges_of(flow.start_body)
    kinds[START] = "start"

    # successors over the non-fault graph (for post-dominators)
    succ = {}
    for n, es in edges.items():
        s = [t for k, t in es if k != "faultConnector"]
        succ[n] = s or [END]
    allnodes = list(succ) + [END]
    # iterative post-dominator sets
    pdom = {n: set(allnodes) for n in allnodes}
    pdom[END] = {END}
    changed = True
    while changed:
        changed = False
        for n in succ:
            new = set.intersection(*(pdom[s] for s in succ[n])) | {n}
            if new != pdom[n]:
                pdom[n], changed = new, True

    def ipdom(n):
        cands = pdom[n] - {n}
        # the immediate post-dominator is the candidate post-dominated by all other candidates
        for c in cands:
            if all(o in pdom[c] for o in cands):
                return c
        return END

    placed, gotos, faults, anomalies = set(), set(), [], []

    def edge(src, idx, t, stops):
        if t == END:
            return
        if stops and t == stops[-1]:
            return                                  # natural end of branch at merge / loop back edge
        if t in stops or t in placed:
            gotos.add((src, idx))
            return
        process(t, stops)

    def process(n, stops):
        placed.add(n)
        es = edges[n]
        for i, (k, t) in enumerate(es):
            if k == "faultConnector":
                faults.append((n, i, t))
        main = [(i, k, t) for i, (k, t) in enumerate(es) if k != "faultConnector"]
        kind = kinds[n]
        if kind == "loops":
            body = [x for x in main if x[1] == "nextValueConnector"]
            after = [x for x in main if x[1] == "noMoreValuesConnector"]
            for i, k, t in body:
                edge(n, i, t, stops + [n])
            for i, k, t in after:
                edge(n, i, t, stops)
        elif len(main) > 1 or kind in ("decisions", "waits") or (n == START and len(main) > 1):
            m = ipdom(n)
            if m != END and m in placed and m not in stops:
                # merge point already drawn elsewhere: no merge here, every branch reaching it is a Go To
                for i, k, t in main:
                    edge(n, i, t, stops)
                return
            for i, k, t in main:
                edge(n, i, t, stops + [m])
            if m != END:
                if m in stops:
                    if m != stops[-1]:
                        anomalies.append(f"merge {m} of {n} is an outer merge point")
                    return
                process(m, stops)
        else:
            for i, k, t in main:
                edge(n, i, t, stops)

    process(START, [])
    while faults:                                   # fault branches after the main structure
        n, i, t = faults.pop(0)
        edge(n, i, t, [])
    unplaced = set(nodes) - placed
    if unplaced:
        anomalies.append(f"unplaced {sorted(unplaced)}")
    return gotos, anomalies


def apply(body, src, gotos):
    """Rewrite the idx-th connector of an element body with isGoTo where needed."""
    counter = {"i": -1}

    def rep(m):
        counter["i"] += 1
        if (src, counter["i"]) in gotos:
            return f"<{m.group(1)}><isGoTo>true</isGoTo><targetReference>{m.group(2)}</targetReference></{m.group(1)}>"
        return m.group(0)
    return CONN_RE.sub(rep, body)
