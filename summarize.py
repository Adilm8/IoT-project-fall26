#!/usr/bin/env python3
"""Summarize one experiment set of logs (Task.md section VIII).

    python3 summarize.py 02                 # reads logs/02/, writes logs/02/results/
    python3 summarize.py 02 --expect 1,3,4  # also expect these source IDs (warn if silent)
    python3 summarize.py 02 --no-write      # print only

Reads the files described in LOGGING.md (root and node `summary` + `events` files, any folder
layout below logs/<NN>/). Standard library only; plots need matplotlib and are skipped without it.
Prints a Markdown report (also saved as results/summary.md) and writes the underlying tables as
results/runs.csv and results/per_source.csv.
"""
import argparse
import csv
import glob
import os
import statistics
import sys

STABLE_ADV_INTERVALS = 3   # Task.md VIII: a route must stay unchanged for three advertisement intervals
NO_ROUTE = 255


# ---- parsing -------------------------------------------------------------------------------
def read_kv(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def num(d, key, default=None):
    try:
        return int(float(d[key]))
    except (KeyError, ValueError):
        return default


def read_events(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                r["t_ms"] = int(r["t_ms"])
            except (ValueError, TypeError):
                continue
            for k in ("node", "seq", "via", "rssi", "hop", "parent"):
                try:
                    r[k] = int(r[k])
                except (ValueError, TypeError, KeyError):
                    r[k] = None
            rows.append(r)
    return rows


class Run:
    def __init__(self, mode, run_id):
        self.mode, self.run_id = mode, run_id
        self.root = None          # (kv, events)
        self.nodes = {}           # device_id -> (kv, events)
        self.warn = []


def load(set_dir, warnings):
    runs = {}
    for path in sorted(glob.glob(os.path.join(set_dir, "**", "*_summary_*.txt"), recursive=True)):
        try:
            kv = read_kv(path)
        except OSError as e:
            warnings.append("cannot read %s: %s" % (path, e))
            continue
        rel = os.path.relpath(path, set_dir)
        mode, rid, dev, did = kv.get("mode"), num(kv, "run_id"), kv.get("device"), num(kv, "device_id")
        if kv.get("format") != "1" or mode not in ("dv", "flood") or rid is None or dev not in ("root", "node") or did is None:
            warnings.append("%s: not a format-1 summary (needs format, mode, run_id, device, device_id), skipped" % rel)
            continue
        ev_path = path.replace("_summary_", "_events_")[:-4] + ".csv"
        events = []
        if os.path.exists(ev_path):
            events = read_events(ev_path)
        else:
            warnings.append("%s: events file missing (%s)" % (rel, os.path.basename(ev_path)))
        run = runs.setdefault((mode, rid), Run(mode, rid))
        if dev == "root":
            if run.root:
                warnings.append("%s: second root file for %s run %d, ignored" % (rel, mode, rid))
            else:
                run.root = (kv, events)
        else:
            if did in run.nodes:
                warnings.append("%s: second file for node %d in %s run %d, ignored" % (rel, did, mode, rid))
            else:
                run.nodes[did] = (kv, events)
    return runs


# ---- metrics -------------------------------------------------------------------------------
def convergence_time(rows, quiet_ms, end_ms):
    """Same rule as the root's CONVERGE line: the earliest time T at which every connected device
    (one that ever advertised a route) has a valid route and no device changes its route for quiet_ms.
    Returns (T in ms or None, devices without a valid route at the end of the log)."""
    ch = sorted((r for r in rows if r["event"] == "route" and r["node"] is not None), key=lambda r: r["t_ms"])
    connected = {r["node"] for r in ch if r["hop"] is not None and r["hop"] < NO_ROUTE}
    state = {}
    for i, r in enumerate(ch):
        state[r["node"]] = r["hop"]
        if i + 1 < len(ch) and ch[i + 1]["t_ms"] == r["t_ms"]:
            continue   # several changes in the same millisecond: judge after the last one
        nxt = ch[i + 1]["t_ms"] if i + 1 < len(ch) else end_ms
        if all(state.get(n, NO_ROUTE) < NO_ROUTE for n in connected) and nxt - r["t_ms"] >= quiet_ms:
            return r["t_ms"], []
    return None, sorted(n for n in connected if state.get(n, NO_ROUTE) >= NO_ROUTE)


def analyze(run, expect, assume_full=()):
    rkv, rrows = run.root
    nodekv = {i: v[0] for i, v in run.nodes.items()}
    sched = (num(rkv, "warmup_s", 60), num(rkv, "run_s", 300), num(rkv, "drain_s", 60))
    end_ms = sum(sched) * 1000
    adv_ms = num(rkv, "adv_interval_s", 5) * 1000

    # unique deliveries by (origin, seq), first reception wins
    first = {}
    for r in rrows:
        if r["event"] == "rx" and r["node"] is not None and r["seq"] is not None:
            first.setdefault((r["node"], r["seq"]), r)
    by_src = {}
    for (o, s), r in first.items():
        by_src.setdefault(o, []).append((r["t_ms"], s))

    sources = sorted((set(nodekv) | set(by_src) | set(expect)) - {0})
    per, estimated, assumed = {}, [], []
    for n in sources:
        kv = nodekv.get(n)
        seqs = {s for _, s in by_src.get(n, [])}
        est = max(seqs) + 1 if seqs else None
        gen = num(kv, "generated") if kv else None
        exact = gen is not None
        if gen is None and n in assume_full and seqs:
            gen = len(seqs)         # --assume-full: no summary, generated := delivered (PDR 100% by assumption)
            assumed.append(n)
        elif gen is None:
            gen = est
        got = len([s for s in seqs if gen is not None and s < gen])
        if exact and len(seqs) != got:
            run.warn.append("node %d: %d delivered seq(s) >= generated=%d (reboot or wrong summary?), not counted"
                            % (n, len(seqs) - got, gen))
        if not exact and gen is not None and n not in assumed:
            estimated.append(n)
        if gen is None:
            run.warn.append("node %d: nothing delivered and no summary, source not in PDR" % n)
        per[n] = {"generated": gen, "exact": exact, "delivered": got,
                  "pdr": got / gen if gen else None,
                  "acq_fail": num(kv, "acq_fail", 0) if kv else None,
                  "noroute": num(kv, "drop_noroute", 0) if kv else None}
    if assumed:
        run.warn.append("no summary for node(s) %s: generated ASSUMED equal to delivered (--assume-full), PDR 100%% by assumption"
                        % ", ".join(map(str, assumed)))
    if estimated:
        run.warn.append("no summary for node(s) %s: generated estimated as highest seq + 1 (PDR is an upper bound)"
                        % ", ".join(map(str, estimated)))
    gen_total = sum(p["generated"] for p in per.values() if p["generated"])
    got_total = sum(p["delivered"] for p in per.values() if p["generated"])
    delivered_all = sum(p["delivered"] for p in per.values())

    # overhead: send attempts on all devices, root adverts included (Task.md VIII)
    data_tx = sum(num(k, "data_tx_own", 0) + num(k, "data_tx_relay", 0) for k in nodekv.values())
    own_tx = sum(num(k, "data_tx_own", 0) for k in nodekv.values())
    adv_tx = sum(num(k, "adv_tx", 0) for k in nodekv.values()) + num(rkv, "adv_tx", 0)
    missing = [n for n in sources if n not in nodekv]
    if missing:
        run.warn.append("no node summary for %s: overhead is a lower bound" % ", ".join(map(str, missing)))
    m = {"mode": run.mode, "run_id": run.run_id, "sources": len(per),
         "generated": gen_total, "delivered": got_total,
         "pdr": got_total / gen_total if gen_total else None,
         "data_tx": data_tx, "own_tx": own_tx, "relay_tx": data_tx - own_tx, "adv_tx": adv_tx, "total_tx": data_tx + adv_tx,
         "overhead": (data_tx + adv_tx) / delivered_all if delivered_all else None,
         "complete": not missing, "per_source": per,
         "dup_at_root": num(rkv, "drop_dup", 0)}

    # topology: last advertised route per node, mean RSSI of the last hop
    last_route, rssi = {}, {}
    for r in sorted(rrows, key=lambda r: r["t_ms"]):
        if r["event"] == "route" and r["node"] is not None:
            last_route[r["node"]] = (r["hop"], r["parent"])
        if r["event"] == "rx" and r["rssi"] is not None and r["via"] is not None:
            rssi.setdefault(r["via"], []).append(r["rssi"])
    m["last_route"] = last_route
    m["rssi"] = {k: sum(v) / len(v) for k, v in rssi.items()}
    m["changes"] = sum(1 for r in rrows if r["event"] == "route" and r["t_ms"] >= sched[0] * 1000) if run.mode == "dv" else None

    # DV startup convergence: every connected device has a valid route unchanged for 3 adv intervals
    m["convergence_s"], m["not_converged"] = None, []
    if run.mode == "dv":
        t, m["not_converged"] = convergence_time(rrows, STABLE_ADV_INTERVALS * adv_ms, end_ms)
        m["convergence_s"] = t / 1000 if t is not None else None
        if not rrows:
            run.warn.append("root events missing: no convergence analysis")

    return m


# ---- report --------------------------------------------------------------------------------
def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def f2(x, nd=2):
    return "n/a" if x is None else ("%.*f" % (nd, x))


def ms(vals, fmt=f2, scale=1.0):
    """mean +- sample stdev (n runs)."""
    v = [x * scale for x in vals if x is not None]
    if not v:
        return "n/a"
    sd = statistics.stdev(v) if len(v) > 1 else None
    return "%s ± %s (n=%d)" % (fmt(statistics.mean(v)), fmt(sd) if sd is not None else "–", len(v))


def pct_f(x):
    return "n/a" if x is None else "%.1f%%" % x


def build_report(set_id, results, warnings):
    out = []
    w = out.append
    groups = {}
    for m in results:
        groups.setdefault(m["mode"], []).append(m)
    w("# Experiment set %s: summary\n" % set_id)
    if warnings:
        w("## Warnings\n")
        for x in warnings:
            w("- " + x)
        w("")
    w("## Runs (underlying results)\n")
    w("| mode | run | sources | generated | delivered | PDR | data tx | adv tx | total tx | overhead | convergence (s) | complete |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for m in sorted(results, key=lambda m: (m["mode"], m["run_id"])):
        w("| %s | %d | %d | %d | %d | %s | %d | %d | %d | %s | %s | %s |" % (
            m["mode"], m["run_id"], m["sources"], m["generated"], m["delivered"], pct(m["pdr"]),
            m["data_tx"], m["adv_tx"], m["total_tx"], f2(m["overhead"]),
            f2(m["convergence_s"], 0) if m["mode"] == "dv" else "–", "yes" if m["complete"] else "NO"))
    w("\nOverhead = (data + relayed + advertisement send attempts of all devices, root included) / unique packets delivered. "
      "PDR = unique (origin, seq) at the root / `generated` of each source. "
      "With `complete = NO` some node summaries are missing and the overhead is a lower bound.\n")

    w("## Mean ± standard deviation across runs\n")
    w("| mode | runs | PDR | overhead | data tx | adv tx | duplicates dropped at root |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for mo, ms_ in sorted(groups.items()):
        w("| %s | %d | %s | %s | %s | %s | %s |" % (
            mo, len(ms_), ms([m["pdr"] for m in ms_], pct_f, 100), ms([m["overhead"] for m in ms_ if m["complete"]]),
            ms([m["data_tx"] for m in ms_ if m["complete"]], lambda x: "%.0f" % x),
            ms([m["adv_tx"] for m in ms_ if m["complete"]], lambda x: "%.0f" % x),
            ms([m["dup_at_root"] for m in ms_], lambda x: "%.0f" % x)))
    w("")
    for mo, ms_ in sorted(groups.items()):
        if len(ms_) < 3:
            w("⚠ %s: only %d run(s), Task.md asks for at least three." % (mo, len(ms_)))
        done = sum(1 for m in ms_ if m["complete"])
        if done < len(ms_):
            w("⚠ %s: overhead, data tx and adv tx use only the %d of %d runs with every node summary present (the others would undercount)." % (mo, done, len(ms_)))

    w("## Per-source PDR (mean ± sd)\n")
    cols = sorted(groups)
    srcs = sorted({n for m in results for n in m["per_source"]})
    w("| source | " + " | ".join(cols) + " |")
    w("| --- |" + " --- |" * len(cols))
    for n in srcs:
        cells = []
        for c in cols:
            vals = [m["per_source"][n]["pdr"] for m in groups[c] if n in m["per_source"]]
            cells.append(ms(vals, pct_f, 100))
        w("| node %d | " % n + " | ".join(cells) + " |")
    w("\nA source that is far below the others in every run is consistently disadvantaged.\n")

    dv = [m for m in results if m["mode"] == "dv"]
    if dv:
        w("## DV startup convergence\n")
        w("Time from root boot (t = 0) until every connected device has a valid route and no device changes its route for %d advertisement intervals "
          "(from the routes the root hears advertised; same rule as the root's CONVERGE line).\n" % STABLE_ADV_INTERVALS)
        w("| run | convergence (s) | devices without a route at the end | route changes after warm-up |")
        w("| --- | --- | --- | --- |")
        for m in sorted(dv, key=lambda m: m["run_id"]):
            w("| %d | %s | %s | %s |" % (m["run_id"],
              f2(m["convergence_s"], 0) if m["convergence_s"] is not None else "not converged",
              ", ".join(map(str, m["not_converged"])) or "–", m["changes"]))
        w("\nMany route changes after warm-up mean parents keep flapping; that costs delivery (packets sent to a stale parent are lost).\n")

    w("## Topology (per run)\n")
    w("Last route each node advertised to the root (hop / parent, DV) and mean RSSI at the root of each transmitter heard (dBm). "
      "Use this for the connectivity graph.\n")
    w("| mode | run | route (node: hop/parent) | mean RSSI at root of last hop (node: dBm) |")
    w("| --- | --- | --- | --- |")
    for m in sorted(results, key=lambda m: (m["mode"], m["run_id"])):
        rt = ", ".join("%d: %s/%s" % (n, h, p) for n, (h, p) in sorted(m["last_route"].items())) or "–"
        rs = ", ".join("%d: %.0f" % kv for kv in sorted(m["rssi"].items())) or "–"
        w("| %s | %d | %s | %s |" % (m["mode"], m["run_id"], rt, rs))
    w("")

    w("## Answers to Task.md section VIII\n")
    d, fl = groups.get("dv"), groups.get("flood")
    if not (d and fl):
        w("- Only %s runs found, no DV vs flooding comparison." % ("DV" if d else "flooding"))
    else:
        avg = lambda g, k, only_complete=False: statistics.mean(
            [m[k] for m in g if m[k] is not None and (m["complete"] or not only_complete)] or [float("nan")])
        w("- **PDR**: DV %s, flooding %s." % (pct_f(100 * avg(d, "pdr")), pct_f(100 * avg(fl, "pdr"))))
        w("- **Overhead** (send attempts per delivered packet): DV %.2f (data %.0f + adverts %.0f per run), flooding %.2f (data %.0f)."
          % (avg(d, "overhead", True), avg(d, "data_tx", True), avg(d, "adv_tx", True), avg(fl, "overhead", True), avg(fl, "data_tx", True)))
        conv = [m["convergence_s"] for m in d if m["convergence_s"] is not None]
        w("- **DV convergence**: %s." % (("%s s mean over %d of %d runs" % (f2(statistics.mean(conv), 0), len(conv), len(d)))
                                       if conv else "no run converged (some route kept changing)"))
    w("")
    return "\n".join(out)


def write_tables(res_dir, results):
    with open(os.path.join(res_dir, "runs.csv"), "w", newline="") as f:
        c = csv.writer(f)
        c.writerow(["mode", "run_id", "sources", "generated", "delivered", "pdr", "data_tx", "own_tx",
                    "relay_tx", "adv_tx", "total_tx", "overhead", "convergence_s", "route_changes", "complete"])
        for m in results:
            c.writerow([m["mode"], m["run_id"], m["sources"], m["generated"], m["delivered"],
                        m["pdr"], m["data_tx"], m["own_tx"], m["relay_tx"], m["adv_tx"], m["total_tx"], m["overhead"],
                        m["convergence_s"], m["changes"], m["complete"]])
    with open(os.path.join(res_dir, "per_source.csv"), "w", newline="") as f:
        c = csv.writer(f)
        c.writerow(["mode", "run_id", "source", "generated", "generated_exact", "delivered", "pdr", "acq_fail", "drop_noroute"])
        for m in results:
            for n, p in sorted(m["per_source"].items()):
                c.writerow([m["mode"], m["run_id"], n, p["generated"], p["exact"], p["delivered"],
                            p["pdr"], p["acq_fail"], p["noroute"]])


def plots(res_dir, results):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "matplotlib not installed, plots skipped (pip install matplotlib)"
    groups = {}
    for m in results:
        groups.setdefault(m["mode"], []).append(m)
    colors = {"dv": "#1f77b4", "flood": "#ff7f0e"}
    names = {"dv": "DV", "flood": "Flooding"}

    def sd(v):
        return statistics.stdev(v) if len(v) > 1 else 0

    srcs = sorted({n for m in results for n in m["per_source"]})
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for j, mo in enumerate(("dv", "flood")):
        g = groups.get(mo, [])
        vals = [[m["per_source"][n]["pdr"] * 100 for m in g if n in m["per_source"] and m["per_source"][n]["pdr"] is not None] for n in srcs]
        ax.bar([i + (j - 0.5) * 0.38 for i in range(len(srcs))], [statistics.mean(v) if v else 0 for v in vals], 0.38,
               yerr=[sd(v) for v in vals], capsize=2, label=names[mo], color=colors[mo])
    ax.set_xticks(range(len(srcs)))
    ax.set_xticklabels(["node %d" % n for n in srcs])
    ax.set_ylabel("PDR (%)")
    ax.set_ylim(0, 105)
    ax.set_title("Per-source PDR (mean ± sd over runs)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(res_dir, "plot_per_source_pdr.png"), dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 3.6))
    modes = [mo for mo in ("dv", "flood") if mo in groups]
    vals = [[m["overhead"] for m in groups[mo] if m["overhead"] is not None] for mo in modes]
    ax.bar(range(len(modes)), [statistics.mean(v) if v else 0 for v in vals], 0.5,
           yerr=[sd(v) for v in vals], capsize=3, color=[colors[mo] for mo in modes])
    ax.set_xticks(range(len(modes)))
    ax.set_xticklabels([names[mo] for mo in modes])
    ax.set_ylabel("send attempts per delivered packet")
    ax.set_title("Transmission overhead (mean ± sd over runs)")
    fig.tight_layout()
    fig.savefig(os.path.join(res_dir, "plot_overhead.png"), dpi=150)
    plt.close(fig)
    return "plots written"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("set_id", help="experiment set folder under --logs, e.g. 02")
    ap.add_argument("--logs", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
    ap.add_argument("--expect", default="", help="comma-separated source IDs that must appear in every run")
    ap.add_argument("--assume-full", default="", help="comma-separated source IDs: where their node summary is missing, "
                    "take generated = delivered (PDR 100%%); listed as a warning in the report")
    ap.add_argument("--no-write", action="store_true", help="print only, do not write results/")
    a = ap.parse_args()
    set_dir = os.path.join(a.logs, a.set_id)
    if a.set_id == "00":
        print("note: 00 is the unstructured test set; see logs/00/SUMMARY.md", file=sys.stderr)
    if not os.path.isdir(set_dir):
        sys.exit("no such folder: " + set_dir)
    expect = [int(x) for x in a.expect.split(",") if x.strip()]
    assume_full = [int(x) for x in a.assume_full.split(",") if x.strip()]
    warnings = []
    runs = load(set_dir, warnings)
    results = []
    for (mode, rid), run in sorted(runs.items()):
        if run.root is None:
            warnings.append("%s run %d: node files but no root summary, run skipped (nodes: %s)"
                            % (mode, rid, ", ".join(map(str, sorted(run.nodes)))))
            continue
        m = analyze(run, expect, assume_full)
        warnings += ["%s run %d: %s" % (mode, rid, x) for x in run.warn]
        results.append(m)
    if not results:
        sys.exit("no usable runs in " + set_dir)
    report = build_report(a.set_id, results, warnings)
    print(report)
    if not a.no_write:
        res_dir = os.path.join(set_dir, "results")
        os.makedirs(res_dir, exist_ok=True)
        with open(os.path.join(res_dir, "summary.md"), "w") as f:
            f.write(report + "\n")
        write_tables(res_dir, results)
        print("\n(%s; tables and report in %s)" % (plots(res_dir, results), res_dir), file=sys.stderr)


if __name__ == "__main__":
    main()
