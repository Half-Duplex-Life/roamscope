"""Build the self-contained HTML report (embedded PNGs, stats, roam table)."""
import os
from datetime import datetime

from html import escape
from . import store
try:
    from . import graphs
    CHART_MIME = "image/png"
except ModuleNotFoundError as exc:
    if exc.name != "matplotlib":
        raise
    from . import svg_charts as graphs
    CHART_MIME = "image/svg+xml"
from .util import freq_to_band


def compute_stats(db, ap_names=None):
    ap_names = ap_names or {}
    samples = store.fetch_samples(db)
    roams = store.fetch_roams(db)
    scans = store.fetch_scans(db)
    stats = {
        "n_samples": len(samples),
        "n_roams": len(roams),
        "n_scans": len(scans),
        "platform": store.get_meta(db, "platform", "?"),
        "started": store.get_meta(db, "started", "?"),
    }
    if samples:
        rssis = [s["rssi"] for s in samples if s["rssi"] is not None]
        span = samples[-1]["ts_epoch"] - samples[0]["ts_epoch"]
        stats.update({
            "span_s": round(span, 1),
            "avg_rssi": round(sum(rssis) / len(rssis), 1) if rssis else None,
            "min_rssi": round(min(rssis), 1) if rssis else None,
            "roams_per_hour": round(len(roams) / (span / 3600), 1) if span > 0 else 0,
        })
    completed = [r for r in roams if r["rssi_delta"] is not None]
    if completed:
        stats["avg_improvement_db"] = round(sum(r["rssi_delta"] for r in completed) / len(completed), 1)
        stats["sticky_roams"] = sum(1 for r in roams if r["reason"] == "sticky")
        dwells = [r["dwell_prev_s"] for r in roams if r["dwell_prev_s"]]
        stats["avg_dwell_s"] = round(sum(dwells) / len(dwells), 1) if dwells else None
    # per-AP summary
    by_ap = {}
    for s in samples:
        if not s["bssid"]:
            continue
        a = by_ap.setdefault(s["bssid"], {"n": 0, "rssis": [], "ssid": s["ssid"],
                                          "channel": s["channel"], "freq": s["freq_mhz"]})
        a["n"] += 1
        if s["rssi"] is not None:
            a["rssis"].append(s["rssi"])
    ap_rows = []
    for bssid, a in sorted(by_ap.items(), key=lambda kv: -len(kv[1]["rssis"])):
        ap_rows.append({
            "bssid": bssid,
            "name": ap_names.get(bssid.lower(), ""),
            "ssid": a["ssid"],
            "samples": a["n"],
            "avg_rssi": round(sum(a["rssis"]) / len(a["rssis"]), 1) if a["rssis"] else None,
            "min_rssi": round(min(a["rssis"]), 1) if a["rssis"] else None,
            "channel": a["channel"],
            "band": freq_to_band(a["freq"]),
            "freq_mhz": a["freq"],
        })
    stats["ap_rows"] = ap_rows
    return stats, samples, roams


CSS = """
body{background:#0f1216;color:#e8ecf1;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
     margin:0;padding:24px;max-width:1100px}
h1{font-size:26px;margin:0 0 4px} h2{font-size:18px;margin:28px 0 10px;color:#9fd0ff}
.sub{color:#8a94a3;font-size:13px;margin-bottom:18px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.card{background:#1a1f27;border:1px solid #2a3140;border-radius:10px;padding:12px 16px;min-width:130px}
.card .k{font-size:11px;color:#8a94a3;text-transform:uppercase;letter-spacing:.06em}
.card .v{font-size:22px;font-weight:600;margin-top:4px}
img{width:100%;border-radius:10px;border:1px solid #2a3140;background:#14171c}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #232a35}
th{color:#8a94a3;font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.05em}
tr:hover td{background:#161b22}
.pos{color:#30c0a0}.neg{color:#ff7a7a}.warn{color:#e0a030}
.note{background:#1a1f27;border-left:3px solid #7a6ff0;padding:10px 14px;border-radius:0 8px 8px 0;
      font-size:13px;color:#b9c2cf;margin:14px 0}
code{background:#232a35;padding:2px 6px;border-radius:4px;font-size:12px}
"""


def _fmt(v, suffix=""):
    return "—" if v is None else "%s%s" % (v, suffix)


def build_report(db_path, out_html, ap_names=None):
    ap_names = ap_names or {}
    db = store.open_db(db_path)
    stats, samples, roams = compute_stats(db, ap_names)
    db.close()

    def safe(value):
        return escape(str(value if value is not None else "—"), quote=True)

    def disp(bssid):
        """AP name when we have one, else the full BSSID (never truncated)."""
        if not bssid:
            return "—"
        return safe(ap_names.get(bssid.lower(), bssid))

    imgs = {
        "rssi": graphs.rssi_plot(samples, roams, ap_names),
        "snr": graphs.snr_plot(samples, roams, ap_names),
        "delta": graphs.roam_delta_plot(roams),
        "neighbor": graphs.neighbor_plot(roams),
        "dwell": graphs.dwell_plot(samples, ap_names),
    }

    valid_bssid = sum(bool(s.get("bssid")) for s in samples)
    identity_note = ""
    if valid_bssid < len(samples):
        identity_note = ('<div class="note">Connected BSSID available in %d of %d samples. '
                         'Roaming and AP dwell are unavailable or incomplete during identity gaps; '
                         'zero observed events does not establish zero actual roams. '
                         'Channel changes alone are not roaming evidence.</div>' % (valid_bssid, len(samples)))
    cards = [
        ("Samples", stats["n_samples"]),
        ("Observed transitions", stats["n_roams"] if valid_bssid else "Unavailable"),
        ("Transitions/hour", stats.get("roams_per_hour", "—") if valid_bssid else "Unavailable"),
        ("Avg RSSI", _fmt(stats.get("avg_rssi"), " dBm")),
        ("Worst RSSI", _fmt(stats.get("min_rssi"), " dBm")),
        ("Avg improvement", _fmt(stats.get("avg_improvement_db"), " dB")),
        ("Sticky roams", stats.get("sticky_roams", 0)),
        ("Avg dwell", _fmt(stats.get("avg_dwell_s"), " s")),
    ]
    cards_html = "".join(
        '<div class="card"><div class="k">%s</div><div class="v">%s</div></div>' % kv
        for kv in cards)

    ap_rows = "".join(
        "<tr><td>%s</td><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            safe(a["name"] or "—"), safe(a["bssid"]), safe(a["ssid"] or "—"), a["samples"],
            _fmt(a["avg_rssi"], " dBm"), _fmt(a["min_rssi"], " dBm"),
            a["channel"] or "—", a["band"] or "—", _fmt(a["freq_mhz"], " MHz"))
        for a in stats["ap_rows"])

    roam_rows = []
    for i, r in enumerate(roams, 1):
        d = r["rssi_delta"]
        dcls = "pos" if (d is not None and d >= 0) else "neg"
        rsn = safe(r["reason"] or "—")
        rsn = '<span class="warn">%s</span>' % rsn if rsn == "sticky" else rsn
        roam_rows.append(
            "<tr><td>R%d</td><td>%s</td><td>%s</td><td><code>%s</code> &rarr; <code>%s</code></td>"
            "<td>%s &rarr; %s</td><td class='%s'>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                i, safe(r["ts"][11:]), safe(r["ssid"] or "—"),
                disp(r["from_bssid"]), disp(r["to_bssid"]),
                _fmt(r["rssi_before"]), _fmt(r["rssi_after"], " dBm"),
                dcls, _fmt(d, " dB") if d is not None else "—",
                _fmt(r["dwell_prev_s"], " s"), rsn,
                ("%s (%s dBm)" % (disp(r["best_neighbor_bssid"]),
                                  r["best_neighbor_rssi"])
                 if r["best_neighbor_bssid"] else "—")))
    roam_rows = "".join(roam_rows) or '<tr><td colspan="9">No observed transitions. Check BSSID coverage before interpreting this result.</td></tr>'

    platform_note = ""
    if stats["platform"] == "windows":
        platform_note = ('<div class="note">Windows reports signal as a 0&ndash;100% quality figure, '
                         'so RSSI here is approximated as <code>dBm &asymp; quality/2 &minus; 100</code>. '
                         'Windows exposes no noise floor to apps, so the SNR chart is unavailable on this backend.</div>')

    platform_note += identity_note
    if CHART_MIME == "image/svg+xml":
        platform_note += '<div class="note">Using built-in SVG charts; install Matplotlib for the original detailed charts.</div>'
    html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>RoamScope report</title><style>%s</style></head><body>
<h1>RoamScope report</h1>
<div class="sub">Backend: %s &middot; captured %s &middot; %d samples over %s s &middot;
<a href="#" onclick="location.reload()" style="color:#9fd0ff">refresh</a></div>
%s
<div class="cards">%s</div>
<h2>RSSI over time</h2><img src="data:image/png;base64,%s">
<h2>Signal-to-noise ratio</h2><img src="data:image/png;base64,%s">
<h2>Signal change per roam</h2><img src="data:image/png;base64,%s">
<h2>Why did it roam?</h2><img src="data:image/png;base64,%s">
<h2>Dwell time per access point</h2><img src="data:image/png;base64,%s">
<h2>Roam events</h2>
<table><tr><th>#</th><th>Time</th><th>SSID</th><th>From &rarr; to</th><th>RSSI</th>
<th>Change</th><th>Dwell before</th><th>Reason</th><th>Best neighbor at roam</th></tr>%s</table>
<h2>Access points seen</h2>
<table><tr><th>Name</th><th>BSSID</th><th>SSID</th><th>Samples</th><th>Avg RSSI</th><th>Min RSSI</th>
<th>Channel</th><th>Band</th><th>Primary frequency</th></tr>%s</table>
<div class="sub" style="margin-top:24px">RoamScope %s &middot; raw data in the .sqlite file next to this report</div>
</body></html>""" % (
        CSS, safe(stats["platform"]), safe(stats["started"]), stats["n_samples"],
        _fmt(stats.get("span_s")), platform_note, cards_html,
        imgs["rssi"], imgs["snr"], imgs["delta"], imgs["neighbor"], imgs["dwell"],
        roam_rows, ap_rows or '<tr><td colspan="9">No associated AP identity available. Neighbor scan results are not proof of association.</td></tr>',
        __import__("roamscope").__version__,
    )
    html = html.replace("data:image/png;base64,", "data:" + CHART_MIME + ";base64,")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    return out_html
