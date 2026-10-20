"""Matplotlib charts -> base64 PNGs for the report and live dashboard."""
import base64
import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.style.use("dark_background")
COLORS = plt.rcParams["axes.prop_cycle"].by_key()["color"]
BG = "#14171c"


def _b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _dt(ts):
    return datetime.fromtimestamp(ts)


def _empty(title, msg="no data yet"):
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.text(0.5, 0.5, msg, ha="center", va="center", fontsize=12, color="#888")
    ax.set_title(title)
    ax.axis("off")
    return _b64(fig)


def _roam_vlines(ax, roams):
    for r in roams or []:
        ax.axvline(_dt(r["ts_epoch"]), color="#ff5555", ls="--", alpha=0.65, lw=1)


def _label(bssid, ap_names):
    if ap_names and bssid.lower() in ap_names:
        return ap_names[bssid.lower()]
    return bssid[-8:].upper()


def rssi_plot(samples, roams, ap_names=None):
    """RSSI over time, one line per BSSID, roam markers."""
    pts = [s for s in samples if s["bssid"] and s["rssi"] is not None]
    if not pts:
        return _empty("RSSI over time")
    by_bssid = {}
    for s in pts:
        by_bssid.setdefault(s["bssid"], []).append(s)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    for i, (bssid, p) in enumerate(sorted(by_bssid.items())):
        ax.plot([_dt(x["ts_epoch"]) for x in p], [x["rssi"] for x in p],
                label=_label(bssid, ap_names), color=COLORS[i % len(COLORS)], lw=1.6)
    _roam_vlines(ax, roams)
    ax.set_ylabel("RSSI (dBm)")
    ax.set_title("RSSI over time  (red dashed = roam)")
    ax.legend(fontsize=8, loc="best", ncol=min(4, len(by_bssid)))
    ax.grid(alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    return _b64(fig)


def snr_plot(samples, roams, ap_names=None):
    """SNR over time (needs noise floor; unavailable on Windows)."""
    pts = [s for s in samples
           if s["bssid"] and s["rssi"] is not None and s["noise"] is not None]
    if not pts:
        return _empty("SNR over time", "no noise-floor data on this platform")
    by_bssid = {}
    for s in pts:
        by_bssid.setdefault(s["bssid"], []).append(s)
    fig, ax = plt.subplots(figsize=(11, 3.6))
    for i, (bssid, p) in enumerate(sorted(by_bssid.items())):
        ax.plot([_dt(x["ts_epoch"]) for x in p],
                [x["rssi"] - x["noise"] for x in p],
                label=_label(bssid, ap_names), color=COLORS[i % len(COLORS)], lw=1.6)
    _roam_vlines(ax, roams)
    ax.set_ylabel("SNR (dB)")
    ax.set_title("Signal-to-noise ratio over time")
    ax.legend(fontsize=8, loc="best", ncol=min(4, len(by_bssid)))
    ax.grid(alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    return _b64(fig)


def roam_delta_plot(roams):
    """Before/after RSSI for each roam."""
    rs = [r for r in roams
          if r["rssi_before"] is not None and r["rssi_after"] is not None]
    if not rs:
        return _empty("Roam signal change", "no completed roams yet")
    fig, ax = plt.subplots(figsize=(11, 3.6))
    labels = ["R%d" % (i + 1) for i in range(len(rs))]
    before = [r["rssi_before"] for r in rs]
    after = [r["rssi_after"] for r in rs]
    x = range(len(rs))
    ax.bar([i - 0.2 for i in x], before, width=0.4, label="before", color="#e0a030")
    ax.bar([i + 0.2 for i in x], after, width=0.4, label="after", color="#30c0a0")
    for i, r in enumerate(rs):
        d = r["rssi_delta"]
        ax.text(i, max(before[i], after[i]) + 0.8, "%+.0f dB" % d,
                ha="center", fontsize=8, color="#ddd")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("RSSI (dBm)")
    ax.set_title("Signal before vs after each roam")
    ax.set_ylim(min(before + after) - 4, max(before + after) + 10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")
    return _b64(fig)


def dwell_plot(samples, ap_names=None):
    """Total time spent on each BSSID."""
    pts = sorted([s for s in samples if s["bssid"]],
                 key=lambda s: s["ts_epoch"])
    if len(pts) < 2:
        return _empty("Dwell time per AP")
    dwell = {}
    for a, b in zip(pts, pts[1:]):
        if a["bssid"] == b["bssid"]:
            dwell[a["bssid"]] = dwell.get(a["bssid"], 0) + (b["ts_epoch"] - a["ts_epoch"])
    if not dwell:
        return _empty("Dwell time per AP")
    items = sorted(dwell.items(), key=lambda kv: -kv[1])
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.barh([_label(k, ap_names) for k, _ in items], [v for _, v in items],
            color=COLORS[2])
    ax.set_xlabel("seconds on this AP")
    ax.set_title("Dwell time per access point")
    for i, (_, v) in enumerate(items):
        ax.text(v, i, " %ds" % v, va="center", fontsize=9, color="#ddd")
    ax.grid(alpha=0.25, axis="x")
    return _b64(fig)


def neighbor_plot(roams):
    """At each roam: RSSI of AP left, AP joined, and strongest neighbor seen."""
    rs = [r for r in roams if r["rssi_before"] is not None]
    if not rs:
        return _empty("Why did it roam?", "no roam data yet")
    fig, ax = plt.subplots(figsize=(11, 3.6))
    x = range(len(rs))
    w = 0.25
    before = [r["rssi_before"] for r in rs]
    after = [r["rssi_after"] if r["rssi_after"] is not None else float("nan") for r in rs]
    neigh = [r["best_neighbor_rssi"] if r["best_neighbor_rssi"] is not None else float("nan") for r in rs]
    ax.bar([i - w for i in x], before, width=w, label="AP left", color="#e0a030")
    ax.bar(x, after, width=w, label="AP joined", color="#30c0a0")
    ax.bar([i + w for i in x], neigh, width=w, label="strongest neighbor at roam", color="#7a6ff0")
    ax.set_xticks(list(x))
    ax.set_xticklabels(["R%d" % (i + 1) for i in x], fontsize=8)
    ax.set_ylabel("RSSI (dBm)")
    ax.set_title("Roam context: the AP you left vs the one you joined vs best neighbor visible")
    vals = [v for v in before + after + neigh if v == v]  # drop NaN
    if vals:
        ax.set_ylim(min(vals) - 4, max(vals) + 3)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")
    return _b64(fig)
