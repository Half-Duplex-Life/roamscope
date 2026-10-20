#!/usr/bin/env python3
"""RoamScope survey analyzer — turn one or more survey captures into an
executive summary: where the sticky roams happened, whether roams actually
improved the signal, and how much time was spent in dead zones.

Works directly on the .sqlite files from `roamscope.py --csv --name <walk>`
(the CSV exports travel alongside for spreadsheets; the .sqlite is what
this analyzer reads). Pure standard library.

    python analyze_survey.py ~/Downloads/roamscope/roamscope-out
    python analyze_survey.py floor-3.sqlite floor-4.sqlite --out analysis

Outputs a printed summary plus `survey-analysis.md` in --out.
"""
import argparse
import glob
import os
import re
import sqlite3
import sys
from datetime import datetime


def short_bssid(b):
    if not b:
        return "?"
    b = b.replace("-", ":")
    p = b.split(":")
    return ":".join(p[:1] + [".."] + p[-1:]) if len(p) == 6 else b


def fmt_dbm(v):
    return "n/a" if v is None else "%d dBm" % round(v)


def fmt_ts(epoch):
    return datetime.fromtimestamp(epoch).strftime("%H:%M:%S") if epoch else "?"


# ----------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------
def find_inputs(paths):
    """Expand dirs into their *.sqlite files; pass through explicit files."""
    inputs = []
    for p in paths:
        if os.path.isdir(p):
            inputs += sorted(glob.glob(os.path.join(p, "*.sqlite")))
        elif os.path.isfile(p):
            inputs.append(p)
        else:
            inputs += sorted(glob.glob(p))
    return inputs


def label_for(path):
    base = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r"roamscope-(?:(.+)-)?(\d{8}-\d{6})$", base)
    if m:
        name, stamp = m.group(1), m.group(2)
        return "%s (%s)" % (name or "unnamed", stamp)
    return base


def load_survey(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row

    def rows(table):
        try:
            return [dict(r) for r in
                    db.execute("SELECT * FROM %s ORDER BY ts_epoch" % table)]
        except sqlite3.OperationalError:
            return []

    samples, roams, scans = rows("samples"), rows("roams"), rows("scans")
    meta = {}
    try:
        meta = {r["key"]: r["value"]
                for r in db.execute("SELECT key, value FROM meta")}
    except sqlite3.OperationalError:
        pass
    db.close()
    return {"path": path, "label": label_for(path), "meta": meta,
            "samples": samples, "roams": roams, "scans": scans}


# ----------------------------------------------------------------------------
# analysis
# ----------------------------------------------------------------------------
def analyze(s, weak=-70, bad=-80):
    samples, roams = s["samples"], s["roams"]
    rssi_vals = [x["rssi"] for x in samples if x.get("rssi") is not None]

    # per-AP presence
    ap_stats = {}
    for x in samples:
        b = x.get("bssid") or "?"
        a = ap_stats.setdefault(b, {"n": 0, "rssi": [], "ssid": x.get("ssid"),
                                   "channel": x.get("channel"),
                                   "freq": x.get("freq_mhz")})
        a["n"] += 1
        if x.get("rssi") is not None:
            a["rssi"].append(x["rssi"])

    weak_n = sum(1 for v in rssi_vals if v < weak)
    bad_n = sum(1 for v in rssi_vals if v < bad)

    # roam quality
    reasons = {}
    roamed_up = roamed_down = missed = 0
    worst = []   # (delta, roam)
    sticky_dwells = []
    for r in roams:
        reasons[r.get("reason") or "?"] = reasons.get(r.get("reason") or "?", 0) + 1
        d = r.get("rssi_delta")
        if d is not None:
            if d > 0:
                roamed_up += 1
            elif d <= -3:
                roamed_down += 1
            worst.append((d, r))
        bn, ra = r.get("best_neighbor_rssi"), r.get("rssi_after")
        if bn is not None and ra is not None and bn - ra >= 3:
            missed += 1
        if (r.get("reason") == "sticky" and r.get("dwell_prev_s")):
            sticky_dwells.append((r["dwell_prev_s"], r))

    worst.sort(key=lambda t: t[0])
    sticky_dwells.sort(key=lambda t: -t[0])

    dur = (samples[-1]["ts_epoch"] - samples[0]["ts_epoch"]) if len(samples) > 1 else 0

    return {
        "label": s["label"], "platform": s["meta"].get("platform", "?"),
        "duration_s": dur, "n_samples": len(samples), "n_roams": len(roams),
        "roams": roams,
        "n_aps": len(ap_stats), "ap_stats": ap_stats,
        "weak_pct": 100.0 * weak_n / max(1, len(rssi_vals)),
        "bad_pct": 100.0 * bad_n / max(1, len(rssi_vals)),
        "mean_rssi": sum(rssi_vals) / max(1, len(rssi_vals)) if rssi_vals else None,
        "reasons": reasons, "roamed_up": roamed_up, "roamed_down": roamed_down,
        "missed": missed, "worst": worst[:5], "sticky_dwells": sticky_dwells[:5],
    }


def pct(n, d):
    return "%.0f%%" % (100.0 * n / d) if d else "n/a"


# ----------------------------------------------------------------------------
# reporting
# ----------------------------------------------------------------------------
def render(all_res, weak, bad):
    L = []
    add = L.append
    add("# RoamScope survey analysis")
    add("")
    add("Walks analyzed: %d" % len(all_res))
    add("")

    for r in all_res:
        add("## %s" % r["label"])
        add("")
        mins = r["duration_s"] / 60.0
        add("- Walk time: **%.0f min**, samples: %d, backend: %s" %
            (mins, r["n_samples"], r["platform"]))
        add("- APs seen: **%d** · mean RSSI: **%s**" %
            (r["n_aps"], fmt_dbm(r["mean_rssi"])))
        add("- Time below %d dBm: **%.0f%%** · below %d dBm: **%.0f%%**" %
            (weak, r["weak_pct"], bad, r["bad_pct"]))
        add("")
        add("### Time per AP")
        add("")
        for b, a in sorted(r["ap_stats"].items(), key=lambda kv: -kv[1]["n"]):
            share = pct(a["n"], r["n_samples"])
            rs = a["rssi"]
            mean = fmt_dbm(sum(rs) / len(rs)) if rs else "n/a"
            mn = fmt_dbm(min(rs)) if rs else "n/a"
            ch = a["channel"] or "?"
            add("- `%s` — %s of walk, mean %s, worst %s, ch %s (%s)" %
                (short_bssid(b), share, mean, mn, ch, a["ssid"] or "?"))
        add("")
        add("### Roams: %d" % r["n_roams"])
        add("")
        if r["n_roams"]:
            rs = r["reasons"]
            add("- sticky: **%d** · fast: %d · normal: %d" %
                (rs.get("sticky", 0), rs.get("fast", 0), rs.get("normal", 0)))
            add("- roamed to a **stronger** signal: %d · roamed ≥3 dB **weaker**: %d" %
                (r["roamed_up"], r["roamed_down"]))
            add("- missed opportunities (better neighbor visible at roam time): %d" %
                r["missed"])
            if r["worst"]:
                add("")
                add("Roams by signal change (worst first):")
                for d, w in r["worst"]:
                    add("  - %s: %s → %s (%s → %s, %+d dB) [%s]" % (
                        fmt_ts(w["ts_epoch"]), short_bssid(w["from_bssid"]),
                        short_bssid(w["to_bssid"]), fmt_dbm(w["rssi_before"]),
                        fmt_dbm(w["rssi_after"]), d, w.get("reason") or "?"))
            if r["sticky_dwells"]:
                add("")
                add("Longest clings before a sticky roam:")
                for dwell, w in r["sticky_dwells"]:
                    add("  - %.0fs on %s (%s) before roaming to %s at %s" % (
                        dwell, short_bssid(w["from_bssid"]),
                        fmt_dbm(w["rssi_before"]),
                        short_bssid(w["to_bssid"]), fmt_ts(w["ts_epoch"])))
        else:
            add("- none recorded on this walk")
        add("")

    # cross-walk aggregation
    if len(all_res) > 1:
        add("## Across walks")
        add("")
        total_roams = sum(r["n_roams"] for r in all_res)
        total_sticky = sum(r["reasons"].get("sticky", 0) for r in all_res)
        add("- total roams: %d, sticky: %d (%s)" %
            (total_roams, total_sticky, pct(total_sticky, total_roams)))
        pair_counts = {}
        for r in all_res:
            for w in r["roams"]:
                key = (w.get("from_bssid") or "?", w.get("to_bssid") or "?")
                pc = pair_counts.setdefault(key, {"n": 0, "sticky": 0})
                pc["n"] += 1
                if w.get("reason") == "sticky":
                    pc["sticky"] += 1
        if pair_counts:
            add("")
            add("Roam pairs (from → to):")
            for (frm, to), pc in sorted(pair_counts.items(),
                                        key=lambda kv: -kv[1]["n"])[:10]:
                add("  - %s → %s: %d roams (%d sticky)" %
                    (short_bssid(frm), short_bssid(to), pc["n"], pc["sticky"]))
        add("")

    add("### How to read this")
    add("")
    add("- **sticky** roams = the client clung to an AP below %d dBm instead of" % weak)
    add("  roaming earlier — these are the spots to fix with AP placement or")
    add("  client roam-aggressiveness, not more radios.")
    add("- A **worst roam ≥3 dB negative** or a **missed opportunity** means the")
    add("  client roamed to a weaker AP while a better one was visible — check")
    add("  for band/channel steering issues or overlapping coverage.")
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description="Analyze RoamScope survey captures.")
    p.add_argument("inputs", nargs="+",
                   help="survey .sqlite file(s) or folder(s) containing them")
    p.add_argument("--out", default=".",
                   help="where to write survey-analysis.md (default: cwd)")
    p.add_argument("--weak", type=float, default=-70,
                   help="sticky threshold in dBm (default: -70)")
    p.add_argument("--bad", type=float, default=-80,
                   help="dead-zone threshold in dBm (default: -80)")
    args = p.parse_args(argv)

    files = find_inputs(args.inputs)
    if not files:
        print("No .sqlite survey files found in: %s" % " ".join(args.inputs))
        return 2

    all_res = [analyze(load_survey(f), args.weak, args.bad) for f in files]
    report = render(all_res, args.weak, args.bad)

    # print the condensed summary: per-walk headline blocks only
    for r in all_res:
        print("== %s ==" % r["label"])
        print("  %.0f min · %d samples · %d APs · %d roams (sticky %d) · "
              "mean %s · below %d dBm %.0f%%" % (
                  r["duration_s"] / 60.0, r["n_samples"], r["n_aps"],
                  r["n_roams"], r["reasons"].get("sticky", 0),
                  fmt_dbm(r["mean_rssi"]), args.weak, r["weak_pct"]))
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "survey-analysis.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("\nFull report: %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
