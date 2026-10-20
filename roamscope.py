#!/usr/bin/env python3
"""RoamScope — capture Wi-Fi roaming data (RSSI, SNR, roam timestamps) and
draw neat graphs.

Runs on Windows, macOS, Linux, and Android (via Termux + Termux:API).

    python roamscope.py --duration 300          # capture 5 minutes
    python roamscope.py --duration 600 --live   # + live dashboard at :8899
    python roamscope.py --simulate --duration 90  # demo without Wi-Fi
    python roamscope.py --report out/session.sqlite  # rebuild a report
"""
import argparse
import csv
import os
import re
import sys
import time
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from roamscope import collectors, live as livemod, report as reportmod, store
from roamscope import roam as roammod
from roamscope.util import ping_ms, short_bssid, freq_to_band


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Capture Wi-Fi roaming RSSI/SNR data and build graphs.")
    p.add_argument("--duration", type=float, default=300,
                   help="capture seconds (0 = until Ctrl+C)")
    p.add_argument("--interval", type=float, default=2,
                   help="seconds between samples")
    p.add_argument("--scan-interval", type=float, default=30,
                   help="seconds between neighbor scans (0 = off)")
    p.add_argument("--backend", default="auto",
                   choices=["auto", "windows", "macos", "linux", "termux", "simulate"],
                   help="capture backend (default: auto-detect)")
    p.add_argument("--simulate", action="store_true",
                   help="use the simulated 3-AP walk (demo, no Wi-Fi needed)")
    p.add_argument("--ping", default=None, metavar="HOST",
                   help="also log ping latency to HOST each sample")
    p.add_argument("--out", default="roamscope-out",
                   help="output directory")
    p.add_argument("--live", action="store_true",
                   help="serve a live auto-refreshing dashboard while capturing")
    p.add_argument("--port", type=int, default=8899,
                   help="dashboard port (with --live)")
    p.add_argument("--report", default=None, metavar="DB",
                   help="rebuild report.html from an existing .sqlite file and exit")
    p.add_argument("--no-open", action="store_true",
                   help="don't open the report in a browser at the end")
    p.add_argument("--csv", action="store_true",
                   help="also export samples/roams/scans as CSV files next to the report")
    p.add_argument("--name", default=None, metavar="NAME",
                   help="label for this capture; used in output filenames (e.g. floor-3)")
    p.add_argument("--ap-names", default=None, metavar="FILE",
                   help="CSV (bssid,name) or JSON file mapping BSSIDs to AP names; "
                        "the report, graphs and CSVs show names instead of MACs")
    p.add_argument("--doctor", action="store_true",
                   help="diagnose whether this machine's Wi-Fi radio is readable, and why not")
    return p.parse_args(argv)


def fmt_roam_line(ev):
    b = _fmt_dbm(ev["rssi_before"])
    a = _fmt_dbm(ev["rssi_after"])
    d = (" (%+.0f dB)" % ev["rssi_delta"]) if ev["rssi_delta"] is not None else ""
    dwell = (" dwell %ds" % ev["dwell_prev_s"]) if ev["dwell_prev_s"] else ""
    return ("ROAM %s  %s  %s -> %s  %s -> %s%s%s [%s]" % (
        store.ts_str(ev["ts_epoch"])[11:], ev["ssid"] or "?",
        short_bssid(ev["from_bssid"]), short_bssid(ev["to_bssid"]),
        b, a, d, dwell, ev["reason"] or "?"))


def _fmt_dbm(v):
    return "—" if v is None else "%d dBm" % round(v)


def load_ap_names(path):
    """Load a BSSID -> AP name mapping from a CSV (bssid,name) or JSON file.

    Beacons never carry AP hostnames, so the client can't discover them —
    this lookup table is how every survey tool does it. In Juniper Mist the
    MAC -> name map is the AP inventory (Organization -> Access Points).
    """
    import json
    names = {}
    try:
        if path.lower().endswith(".json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            pairs = data.items() if isinstance(data, dict) else []
        else:
            with open(path, encoding="utf-8", newline="") as f:
                rows = [r for r in csv.reader(f) if r and len(r) >= 2]
            if rows and rows[0][0].strip().lower() == "bssid":
                rows = rows[1:]  # tolerate a header row
            pairs = [(r[0], r[1]) for r in rows]
        for bssid, name in pairs:
            b, n = bssid.strip().lower(), name.strip()
            if b and n:
                names[b] = n
    except Exception as e:
        print("warning: couldn't load AP names from %s (%s)" % (path, e))
    if names:
        print("Loaded %d AP names from %s" % (len(names), path))
    else:
        print("warning: no AP names loaded from %s" % path)
    return names


def rebuild_report(db_path, out_dir, no_open, ap_names=None):
    html = os.path.join(out_dir, "report.html")
    reportmod.build_report(db_path, html, ap_names)
    print("Report: %s" % html)
    if not no_open:
        webbrowser.open("file://" + os.path.abspath(html))


def export_csv(db_path, out_dir, base, ap_names=None):
    """Dump samples/roams/scans tables to CSV (plus AP-name columns)."""
    import sqlite3
    ap_names = ap_names or {}
    db = sqlite3.connect(db_path)
    paths = []

    def ap_name(bssid):
        return ap_names.get((bssid or "").lower(), "")

    for table, extra_cols in (("samples", ["ap_name"]),
                              ("roams", ["from_ap_name", "to_ap_name"]),
                              ("scans", ["ap_name"])):
        cur = db.execute("SELECT * FROM %s ORDER BY id" % table)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        path = os.path.join(out_dir, "%s-%s.csv" % (base, table))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols + extra_cols)
            for row in rows:
                d = dict(zip(cols, row))
                if table == "roams":
                    extra = [ap_name(d.get("from_bssid")), ap_name(d.get("to_bssid"))]
                else:
                    extra = [ap_name(d.get("bssid"))]
                w.writerow(list(row) + extra)
        paths.append(path)
    db.close()
    return paths


def main(argv=None):
    args = parse_args(argv)

    ap_names = load_ap_names(args.ap_names) if args.ap_names else {}

    if args.report:
        out_dir = os.path.dirname(os.path.abspath(args.report)) or "."
        rebuild_report(args.report, out_dir, args.no_open, ap_names)
        if args.csv:
            base = os.path.splitext(os.path.basename(args.report))[0]
            for p in export_csv(args.report, out_dir, base, ap_names):
                print("CSV: %s" % p)
        return 0

    backend_name = "simulate" if args.simulate else args.backend
    if args.doctor:
        ok, lines = collectors.diagnose(backend_name)
        print("RoamScope doctor (backend: %s):"
              % collectors.resolve_backend_name(backend_name))
        for ln in lines:
            print("  " + ln)
        return 0 if ok else 1
    backend = collectors.get_backend(backend_name)
    print("RoamScope backend: %s" % backend.description)

    # sanity check: can we read the radio at all?
    sample, _ = backend.collect()
    misses = 0
    if sample is None and backend.name != "simulate":
        print("Trying to read the Wi-Fi radio", end="", flush=True)
        for _ in range(4):
            time.sleep(1.5)
            print(".", end="", flush=True)
            sample, _ = backend.collect()
            if sample is not None:
                break
        print()
    if sample is None and backend.name != "simulate":
        print("\nCouldn't read Wi-Fi state. Are you connected to Wi-Fi?")
        print("Run `python roamscope.py --doctor` for a specific diagnosis.")
        print("Tip: run with --simulate to see a full demo without a Wi-Fi radio.")
        return 2

    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", args.name or "").strip("-")
    base = "roamscope-%s-%s" % (label, stamp) if label else "roamscope-%s" % stamp
    db_path = os.path.join(args.out, base + ".sqlite")
    db = store.open_db(db_path)
    store.set_meta(db, "platform", backend.name)
    store.set_meta(db, "started", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if args.live:
        livemod.start_server(os.path.abspath(args.out), args.port)
        print("Live dashboard: http://127.0.0.1:%d/report.html" % args.port)

    tracker = roammod.RoamTracker()
    next_scan = 0
    last_dash = 0
    start = time.time()
    n = 0
    print("Capturing every %.1fs%s — Ctrl+C to stop and build the report." % (
        args.interval,
        (" for %ds" % args.duration) if args.duration > 0 else ""))

    try:
        while True:
            loop_t0 = time.time()
            if args.duration > 0 and loop_t0 - start >= args.duration:
                break
            sample, pending_nb = backend.collect()
            if sample is None:
                misses += 1
                if misses == 1:
                    print(".. radio unreadable / disconnected, waiting ..")
            else:
                if misses:
                    print(".. radio readable again ..")
                    misses = 0
                if args.ping:
                    sample["ping_ms"] = ping_ms(args.ping)
                store.insert_sample(db, sample)
                n += 1
                nb = pending_nb
                if args.scan_interval > 0 and loop_t0 >= next_scan:
                    if nb is None:
                        nb = backend.scan()
                    if nb:
                        store.insert_scans(db, nb, loop_t0)
                    next_scan = loop_t0 + args.scan_interval
                ev = tracker.feed(sample, nb)
                if ev:
                    store.insert_roam(db, ev)
                    print(fmt_roam_line(ev), flush=True)
                elif n % 10 == 1:
                    frequency = sample.get("freq_mhz")
                    band = freq_to_band(frequency) if frequency is not None else "band unknown"
                    channel = sample.get("channel")
                    width = sample.get("width_mhz")
                    channel_label = "ch %s" % channel if channel is not None else "ch ?"
                    if width is not None:
                        channel_label += "/%sMHz" % width
                    freq_label = "%s MHz" % frequency if frequency is not None else "freq unknown"
                    print("  %s  %-18s %s  %s  %s  %s  %s" % (
                        datetime.fromtimestamp(sample["ts_epoch"]).strftime("%H:%M:%S"),
                        (sample["ssid"] or "?")[:18],
                        short_bssid(sample["bssid"]), _fmt_dbm(sample["rssi"]),
                        channel_label, band, freq_label), flush=True)
            if args.live and loop_t0 - last_dash >= 10:
                try:
                    reportmod.build_report(db_path, os.path.join(args.out, "report.html"),
                                           ap_names)
                    last_dash = loop_t0
                except Exception as e:
                    print("dashboard refresh failed: %s" % e)
            time.sleep(max(0.1, args.interval - (time.time() - loop_t0)))
    except KeyboardInterrupt:
        print("\nStopped.")

    db.close()
    print("Captured %d samples -> %s" % (n, db_path))
    rebuild_report(db_path, args.out, args.no_open, ap_names)
    if args.csv:
        for p in export_csv(db_path, args.out, base, ap_names):
            print("CSV: %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
