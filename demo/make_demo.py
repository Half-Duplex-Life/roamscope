#!/usr/bin/env python3
"""Render demo-video frames for a simulated RoamScope run.

Everything visualised is genuine output of the app's own modules
(collectors / roam tracker / graph renderers) — just replayed fast.
Frames land in demo-output/frames as unique PNGs + a concat list for ffmpeg.
"""
import base64
import io
import os
import random
import sys
import time
from datetime import datetime

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roamscope.collectors import SimulateBackend
from roamscope import roam as roammod, graphs
from roamscope.util import short_bssid
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 30
OUT = str(Path(__file__).resolve().parents[1] / "demo-output" / "frames")
os.makedirs(OUT, exist_ok=True)

from matplotlib import get_data_path
TTF = str(Path(get_data_path()) / "fonts" / "ttf") + os.sep
f_mono = lambda sz: ImageFont.truetype(TTF + "DejaVuSansMono.ttf", sz)
f_sans = lambda sz: ImageFont.truetype(TTF + "DejaVuSans.ttf", sz)
f_sans_b = lambda sz: ImageFont.truetype(TTF + "DejaVuSans-Bold.ttf", sz)

segs = []  # (filename, duration_s)


def add(img, dur, name):
    img.save("%s/%s.png" % (OUT, name))
    segs.append(("%s.png" % name, dur))


def b64_to_img(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


# ---------------------------------------------------------- simulated data --
def run_sim(seed):
    random.seed(seed)
    sim = SimulateBackend()
    tracker = roammod.RoamTracker()
    t0 = time.time()
    samples, roams = [], []
    for i in range(90):
        sim.t0 = t0 - i * 2  # advance the walk clock 2 s per sample
        s, nb = sim.collect()
        s["ts_epoch"] = t0 + i * 2
        samples.append(s)
        ev = tracker.feed(s, nb)
        if ev:
            roams.append(ev)
    return samples, roams


for _seed in range(40):
    samples, roams = run_sim(_seed)
    if len(roams) >= 3:
        break
print("seed=%d samples=%d roams=%d" % (_seed, len(samples), len(roams)))


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def sample_line(s):
    return "  %s  %-18s %s  %s" % (
        fmt_ts(s["ts_epoch"]), (s["ssid"] or "?")[:18],
        short_bssid(s["bssid"]),
        "—" if s["rssi"] is None else "%d dBm" % round(s["rssi"]))


def roam_line(ev):
    b = "—" if ev["rssi_before"] is None else "%d dBm" % round(ev["rssi_before"])
    a = "—" if ev["rssi_after"] is None else "%d dBm" % round(ev["rssi_after"])
    d = (" (%+.0f dB)" % ev["rssi_delta"]) if ev["rssi_delta"] is not None else ""
    dwell = (" dwell %ds" % ev["dwell_prev_s"]) if ev["dwell_prev_s"] else ""
    return "ROAM %s  %s  %s -> %s  %s -> %s%s%s [%s]" % (
        fmt_ts(ev["ts_epoch"]), ev["ssid"] or "?",
        short_bssid(ev["from_bssid"]), short_bssid(ev["to_bssid"]),
        b, a, d, dwell, ev["reason"] or "?")


# ------------------------------------------------------------- title card --
img = Image.new("RGB", (W, H), "#0f1216")
d = ImageDraw.Draw(img)
d.text((W // 2, 290), "RoamScope", font=f_sans_b(100), fill="#e8ecf1", anchor="mm")
d.text((W // 2, 400), "Wi-Fi roaming capture — simulated demo", font=f_sans(34),
       fill="#8a94a3", anchor="mm")
d.text((W // 2, 462), "no Wi-Fi radio needed", font=f_sans(24), fill="#5a6472", anchor="mm")
add(img, 2.5, "a_title")


# --------------------------------------------------------------- terminal --
def term_img(vis):
    img = Image.new("RGB", (W, H), "#0d1117")
    d = ImageDraw.Draw(img)
    d.text((40, 22), "demo-machine: ~/roamscope", font=f_mono(20), fill="#5a6472")
    y = 66
    for ln in vis[-20:]:
        if ln.startswith("ROAM"):
            col = "#ff7b72"
        elif ln.startswith("Report") or ln.startswith("Captured"):
            col = "#7ee787"
        elif ln.startswith("RoamScope backend") or ln.startswith("Capturing"):
            col = "#8b949e"
        else:
            col = "#e6edf3"
        d.text((40, y), ln, font=f_mono(21), fill=col)
        y += 30
    return img


CMD = "$ python roamscope.py --simulate --duration 0"
for n in range(1, len(CMD) + 1):
    add(term_img([CMD[:n] + "▌"]), 1.0 / FPS, "b_type_%03d" % n)
add(term_img([CMD]), 0.6, "b_cmd_hold")

tlines = ["RoamScope backend: Simulated 3-AP walk (demo mode)",
          "Capturing every 2.0s — Ctrl+C to stop and build the report."]
roam_by_ts = {}
for ev in roams:
    roam_by_ts.setdefault(ev["ts_epoch"], []).append(ev)
for i, s in enumerate(samples):
    if i < 3 or i % 4 == 0:
        tlines.append(sample_line(s))
    for ev in roam_by_ts.get(s["ts_epoch"], []):
        tlines.append(roam_line(ev))
tlines += ["^C", "Stopped.", "Captured %d samples" % len(samples),
            "Report: report.html"]

vis = [CMD]
for j, ln in enumerate(tlines):
    vis = vis + [ln]
    last = (j == len(tlines) - 1)
    dur = 1.4 if last else (0.9 if ln == "^C" else 0.32)
    add(term_img(vis), dur, "b_line_%03d" % j)


# ------------------------------------------------- progressive RSSI graph --
def graph_frame(pil_graph, caption, sub):
    img = Image.new("RGB", (W, H), "#0f1216")
    gw, gh = pil_graph.size
    scale = min(1200.0 / gw, 545.0 / gh)
    g = pil_graph.resize((int(gw * scale), int(gh * scale)), Image.LANCZOS)
    img.paste(g, ((W - g.width) // 2, 28))
    d = ImageDraw.Draw(img)
    d.text((W // 2, 636), caption, font=f_sans_b(30), fill="#e8ecf1", anchor="mm")
    if sub:
        d.text((W // 2, 676), sub, font=f_sans(22), fill="#8a94a3", anchor="mm")
    return img


seen_roams = set()
STEPS = 30
for step in range(1, STEPS + 1):
    k = step * 90 // STEPS
    upto = [r for r in roams if r["ts_epoch"] <= samples[k - 1]["ts_epoch"]]
    png = b64_to_img(graphs.rssi_plot(samples[:k], upto))
    new = [r for r in upto if id(r) not in seen_roams]
    seen_roams.update(id(r) for r in upto)
    if new:
        r = new[-1]
        cap = "Roam!  %s → %s  (%+.0f dB)" % (
            short_bssid(r["from_bssid"]), short_bssid(r["to_bssid"]),
            r["rssi_delta"] or 0)
    else:
        cap = "Live capture — RSSI per access point"
    sub = "sample %d / 90 · one line per AP" % k
    add(graph_frame(png, cap, sub), 26.0 / STEPS, "c_prog_%02d" % step)


# ------------------------------------------------------- final report tour --
trio = [
    (graphs.rssi_plot(samples, roams), "RSSI over time", "red dashes mark each roam"),
    (graphs.snr_plot(samples, roams), "Signal-to-noise ratio", "needs the noise floor — free on macOS/Linux"),
    (graphs.roam_delta_plot(roams), "Signal before → after each roam", None),
    (graphs.neighbor_plot(roams), "Why did it roam?", "AP left vs AP joined vs best neighbor in range"),
    (graphs.dwell_plot(samples), "Dwell time per access point", None),
]
for j, (b64, cap, sub) in enumerate(trio):
    add(graph_frame(b64_to_img(b64), cap, sub), 4.4, "d_rep_%d" % j)


# ---------------------------------------------------------------- end card --
img = Image.new("RGB", (W, H), "#0f1216")
d = ImageDraw.Draw(img)
d.text((W // 2, 220), "Your turn", font=f_sans_b(64), fill="#e8ecf1", anchor="mm")
d.text((W // 2, 330), "$ python roamscope.py --duration 0 --csv --name floor-3",
       font=f_mono(30), fill="#7ee787", anchor="mm")
d.text((W // 2, 410), "walk your route  ·  Ctrl+C when done",
       font=f_sans(26), fill="#8a94a3", anchor="mm")
d.text((W // 2, 458), "report + CSVs appear by themselves",
       font=f_sans(26), fill="#8a94a3", anchor="mm")
add(img, 5.0, "e_end")

with open(str(Path(OUT).parent / "list.txt"), "w") as f:
    for name, dur in segs:
        f.write("file '%s/%s'\nduration %.3f\n" % (OUT, name, dur))
    f.write("file '%s/%s'\n" % (OUT, segs[-1][0]))  # repeat last for concat

total = sum(d for _, d in segs)
print("frames=%d total=%.1fs" % (len(segs), total))
