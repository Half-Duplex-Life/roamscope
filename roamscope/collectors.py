"""Platform collectors.

Each backend exposes:
    collect() -> (sample_dict | None, neighbors | None)
    scan()    -> [neighbor_dict]

sample_dict keys:
    ts_epoch, ssid, bssid, rssi (dBm), noise (dBm|None),
    channel, width_mhz, freq_mhz, tx_mbps, phy, ping_ms, platform
neighbor_dict keys:
    ssid, bssid, rssi, channel, freq_mhz

collect() returns None when not associated / no wireless interface.
"""
import json
import urllib.request
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time

from .util import run, channel_to_freq_mhz, freq_to_channel, freq_to_band

MAC_RE = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")


def _norm_bssid(b):
    return b.strip().lower() if b else None


def _base(platform, ts=None):
    return {
        "ts_epoch": ts if ts is not None else time.time(),
        "ssid": None,
        "bssid": None,
        "rssi": None,
        "noise": None,
        "channel": None,
        "width_mhz": None,
        "freq_mhz": None,
        "tx_mbps": None,
        "phy": None,
        "ping_ms": None,
        "platform": platform,
    }


def _pct_to_dbm(pct):
    """Windows reports signal as 0-100%; convert to approximate dBm."""
    return round(pct / 2 - 100, 1)


# ---------------------------------------------------------------- Windows ----
def collect_windows():
    s = _base("windows")
    out = run(["netsh", "wlan", "show", "interfaces"], timeout=10)
    if not out:
        return None, None
    block = None
    for chunk in re.split(r"\n\s*\n", out):
        kv = {}
        for line in chunk.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip().lower()] = v.strip()
        if kv.get("state", "").lower() == "connected":
            block = kv
            break
    if not block:
        return None, None
    s["ssid"] = block.get("ssid") or None
    s["bssid"] = _norm_bssid(block.get("bssid"))
    m = re.search(r"(\d+)", block.get("signal", ""))
    if m:
        s["rssi"] = _pct_to_dbm(int(m.group(1)))
    s["phy"] = block.get("radio type") or None
    ch = block.get("channel", "")
    if ch.isdigit():
        s["channel"] = int(ch)
        band = (block.get("band") or "").lower()
        hint = "6" if "6" in band else ("5" if band.startswith("5") else ("2.4" if "2.4" in band else None))
        s["freq_mhz"] = channel_to_freq_mhz(int(ch), hint)
    m = re.search(r"([\d.]+)", block.get("transmit rate (mbps)", ""))
    if m:
        s["tx_mbps"] = float(m.group(1))
    # NOTE: Windows' public WLAN API does not expose the noise floor,
    # so SNR can't be computed on this backend.
    return s, None


def scan_windows():
    out = run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=30)
    neighbors, cur_ssid, cur = [], None, None
    for line in out.splitlines():
        m = re.match(r"\s*SSID \d+ : (.*)", line)
        if m:
            if cur:
                neighbors.append(cur)
                cur = None
            cur_ssid = m.group(1).strip() or None
            continue
        m = re.match(r"\s*BSSID \d+\s*:\s*(.*)", line)
        if m:
            if cur:
                neighbors.append(cur)
            cur = {"ssid": cur_ssid, "bssid": _norm_bssid(m.group(1)),
                   "rssi": None, "channel": None, "freq_mhz": None}
            continue
        if cur is not None and ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "signal":
                mm = re.search(r"(\d+)", v)
                if mm:
                    cur["rssi"] = _pct_to_dbm(int(mm.group(1)))
            elif k == "channel" and v.isdigit():
                cur["channel"] = int(v)
                cur["freq_mhz"] = channel_to_freq_mhz(int(v))
    if cur:
        neighbors.append(cur)
    return [n for n in neighbors if n["bssid"]]


# ------------------------------------------------------------------ macOS ----
_AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"


def _airport_bin():
    if os.path.exists(_AIRPORT):
        return _AIRPORT
    return shutil.which("airport")


def _collect_macos_airport():
    """Primary macOS source: the airport CLI. Returns a sample dict or None."""
    s = _base("macos")
    ap = _airport_bin()
    if not ap:
        return None
    out = run([ap, "-I"], timeout=10)
    if not out or "BSSID" not in out:
        return None
    kv = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            kv[k.strip()] = v.strip()
    bssid = kv.get("BSSID")
    bare = re.sub(r"[^0-9a-f]", "", (bssid or "").lower())
    if not bare or bare == "0" * 12:  # covers 0:0:0:0:0:0 and 00:...:00
        return None
    s["bssid"] = _norm_bssid(bssid)
    s["ssid"] = kv.get("SSID") or None
    try:
        s["rssi"] = float(kv["agrCtlRSSI"])
    except (KeyError, TypeError, ValueError):
        pass
    try:
        s["noise"] = float(kv["agrCtlNoise"])
    except (KeyError, TypeError, ValueError):
        pass
    m = re.match(r"(\d+)(?:,(\d+))?", kv.get("channel", ""))
    if m:
        s["channel"] = int(m.group(1))
        s["width_mhz"] = int(m.group(2)) if m.group(2) else 20
        s["freq_mhz"] = channel_to_freq_mhz(s["channel"])
    try:
        s["tx_mbps"] = float(kv["lastTxRate"])
    except (KeyError, TypeError, ValueError):
        pass
    return s


def _collect_macos_sysprof():
    """Fallback when the airport CLI is missing or broken.

    system_profiler ships with every macOS and reports the same association
    data (BSSID, RSSI, noise, channel). Slower (~1-2 s per call), so it's only
    used when airport fails.
    """
    s = _base("macos")
    out = run(["system_profiler", "SPAirPortDataType"], timeout=25)
    if not out or "Current Network Information:" not in out:
        return None
    sec = out.split("Current Network Information:", 1)[1]
    mb = re.search(r"BSSID:\s*([0-9a-fA-F:]{17})", sec)
    if mb:
        s["bssid"] = _norm_bssid(mb.group(1))
    # Recent macOS releases may omit BSSID even when Wi-Fi is associated.
    # Keep RF samples; do not invent a BSSID or infer a roam.
    mssid = re.search(r"^\s{2,12}([^\s:][^:\n]*):\s*$", sec, re.M)
    s["ssid"] = mssid.group(1).strip() if mssid else None
    msn = re.search(r"Signal\s*/\s*Noise:\s*(-?\d+)\s*dBm\s*/\s*(-?\d+)\s*dBm", sec)
    if msn:
        s["rssi"] = float(msn.group(1))
        s["noise"] = float(msn.group(2))
    mc = re.search(r"^\s*Channel:\s*(\d+)", sec, re.M)
    if mc:
        s["channel"] = int(mc.group(1))
        s["freq_mhz"] = channel_to_freq_mhz(s["channel"])
    mt = re.search(r"Transmit Rate:\s*(\d+)", sec)
    if mt:
        s["tx_mbps"] = float(mt.group(1))
    mp = re.search(r"PHY Mode:\s*(\S+)", sec)
    if mp:
        s["phy"] = mp.group(1)
    # Require actual current-link RF telemetry to avoid treating nearby scans
    # as an active connection when the interface is disconnected.
    if s["rssi"] is None or s["channel"] is None:
        return None
    return s


def _collect_macos_helper():
    """Authorized GUI helper, local loopback only; no guessed BSSID."""
    try:
        with urllib.request.urlopen('http://127.0.0.1:18763/', timeout=1.5) as response:
            data = json.loads(response.read(4096))
        if not isinstance(data, dict) or not MAC_RE.fullmatch(data.get('bssid') or ''):
            return None
        s = _base('macos')
        s['ssid'] = data.get('ssid') or None
        s['bssid'] = _norm_bssid(data['bssid'])
        for key in ('rssi', 'noise', 'tx_mbps'):
            s[key] = float(data[key]) if data.get(key) is not None else None
        ch = int(data.get('channel') or 0)
        # Channel numbers overlap across bands; never infer 6 GHz from channel alone.
        band_text = str(data.get('channel_band') or '').lower()
        band_hint = ('6' if '6ghz' in band_text or '6gh' in band_text
                     else '5' if '5ghz' in band_text or '5gh' in band_text
                     else '2.4' if '2ghz' in band_text or '2gh' in band_text
                     else None)
        if ch:
            s['channel'] = ch
            # Legacy helper provides no band hint. Only resolve unambiguous
            # channels, leaving 1-14 unknown rather than mislabeling 6 GHz.
            if band_hint or ch >= 15:
                s['freq_mhz'] = channel_to_freq_mhz(ch, band_hint)
        width_text = str(data.get('channel_width') or '').lower()
        import re as _re
        width_match = _re.search(r'(20|40|80|160|320)', width_text)
        if width_match:
            s['width_mhz'] = int(width_match.group(1))
        return s
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def collect_macos():
    authorized = _collect_macos_helper()
    if authorized is not None:
        return authorized, None
    s = _collect_macos_airport()
    if s is not None:
        return s, None
    fb = _collect_macos_sysprof()
    if fb is not None:
        return fb, None
    return None, None


def scan_macos():
    ap = _airport_bin()
    if not ap:
        return []
    out = run([ap, "-s"], timeout=30)
    neighbors = []
    for line in out.splitlines():
        m = MAC_RE.search(line)
        if not m:
            continue
        ssid = line[:m.start()].strip() or None
        rest = line[m.end():].split()
        if len(rest) < 2:
            continue
        try:
            rssi = float(rest[0])
        except ValueError:
            continue
        chm = re.match(r"(\d+)", rest[1])
        ch = int(chm.group(1)) if chm else None
        neighbors.append({
            "ssid": ssid, "bssid": _norm_bssid(m.group(0)), "rssi": rssi,
            "channel": ch, "freq_mhz": channel_to_freq_mhz(ch) if ch else None,
        })
    return neighbors


# ------------------------------------------------------------------ Linux ----
def _linux_iface():
    out = run(["iw", "dev"], timeout=5)
    m = re.search(r"^\s*Interface\s+(\S+)", out, re.M)
    return m.group(1) if m else None


def _linux_noise(iface, freq):
    if not freq:
        return None
    out = run(["iw", "dev", iface, "survey", "dump"], timeout=8)
    for block in re.split(r"Survey data from", out):
        if "[in use]" not in block:
            continue
        mf = re.search(r"frequency:\s*(\d+)\s*MHz", block)
        if mf and int(mf.group(1)) == freq:
            mn = re.search(r"noise:\s*(-?[\d.]+)\s*dBm", block)
            if mn:
                return float(mn.group(1))
    return None


def collect_linux():
    s = _base("linux")
    iface = _linux_iface()
    if not iface:
        return None, None
    out = run(["iw", "dev", iface, "link"], timeout=8)
    if not out or "Not connected" in out:
        return None, None
    m = re.search(r"Connected to (\S+)", out)
    s["bssid"] = _norm_bssid(m.group(1)) if m else None
    m = re.search(r"^\s*SSID:\s*(.+)$", out, re.M)
    s["ssid"] = m.group(1).strip() or None if m else None
    m = re.search(r"^\s*freq:\s*(\d+)", out, re.M)
    if m:
        s["freq_mhz"] = int(m.group(1))
        s["channel"] = freq_to_channel(s["freq_mhz"])
    m = re.search(r"^\s*signal:\s*(-?[\d.]+)", out, re.M)
    if m:
        s["rssi"] = float(m.group(1))
    m = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", out)
    if m:
        s["tx_mbps"] = float(m.group(1))
    s["noise"] = _linux_noise(iface, s["freq_mhz"])
    return s, None


def scan_linux():
    iface = _linux_iface()
    if not iface:
        return []
    out = run(["iw", "dev", iface, "scan"], timeout=40)
    neighbors, cur = [], None
    for line in out.splitlines():
        m = re.match(r"BSS\s+([0-9a-fA-F:]{17})", line)
        if m:
            if cur:
                neighbors.append(cur)
            cur = {"ssid": None, "bssid": _norm_bssid(m.group(1)),
                   "rssi": None, "channel": None, "freq_mhz": None}
            continue
        if cur is None:
            continue
        ms = re.match(r"\s*signal:\s*(-?[\d.]+)\s*dBm", line)
        if ms:
            cur["rssi"] = float(ms.group(1))
            continue
        mf = re.match(r"\s*freq:\s*(\d+)", line)
        if mf:
            cur["freq_mhz"] = int(mf.group(1))
            cur["channel"] = freq_to_channel(cur["freq_mhz"])
            continue
        mssid = re.match(r"\s*SSID:\s*(.*)$", line)
        if mssid:
            cur["ssid"] = mssid.group(1).strip() or None
    if cur:
        neighbors.append(cur)
    return [n for n in neighbors if n["bssid"] and n["rssi"] is not None]


# ----------------------------------------------------------------- Termux ----
# Android via Termux + Termux:API (install both from F-Droid, grant location).
def collect_termux():
    s = _base("termux")
    try:
        d = json.loads(run(["termux-wifi-connectioninfo"], timeout=8))
    except Exception:
        return None, None
    if not isinstance(d, dict) or not d.get("bssid"):
        return None, None
    s["bssid"] = _norm_bssid(d.get("bssid"))
    ssid = d.get("ssid")
    s["ssid"] = None if ssid in (None, "<unknown ssid>") else ssid
    r = d.get("rssi")
    s["rssi"] = float(r) if isinstance(r, (int, float)) else None
    f = d.get("frequency_mhz")
    s["freq_mhz"] = int(f) if f else None
    s["channel"] = freq_to_channel(s["freq_mhz"])
    ls = d.get("link_speed_mbps")
    s["tx_mbps"] = float(ls) if isinstance(ls, (int, float)) else None
    return s, None


def scan_termux():
    try:
        arr = json.loads(run(["termux-wifi-scaninfo"], timeout=30))
    except Exception:
        return []
    if isinstance(arr, dict):
        arr = arr.get("results", [])
    neighbors = []
    for d in arr or []:
        if not isinstance(d, dict):
            continue
        f = d.get("frequency_mhz")
        f = int(f) if f else None
        r = d.get("rssi")
        neighbors.append({
            "ssid": d.get("ssid") or None,
            "bssid": _norm_bssid(d.get("bssid")),
            "rssi": float(r) if isinstance(r, (int, float)) else None,
            "channel": freq_to_channel(f),
            "freq_mhz": f,
        })
    return [n for n in neighbors if n["bssid"]]


# --------------------------------------------------------------- Simulate ----
class SimulateBackend:
    """Synthetic roaming walk: 3 APs, client roams with hysteresis like real
    clients. Lets you see the graphs without a Wi-Fi radio (--simulate)."""

    APS = [
        {"bssid": "aa:bb:cc:11:22:33", "ssid": "HomeNet", "channel": 6,
         "freq": 2437, "width": 20, "base": -55, "amp": 12, "period": 70,
         "phase": 0.0, "noise": -92},
        {"bssid": "aa:bb:cc:44:55:66", "ssid": "HomeNet", "channel": 36,
         "freq": 5180, "width": 80, "base": -58, "amp": 14, "period": 95,
         "phase": 2.1, "noise": -90},
        {"bssid": "aa:bb:cc:77:88:99", "ssid": "HomeNet", "channel": 44,
         "freq": 5220, "width": 80, "base": -62, "amp": 10, "period": 55,
         "phase": 4.2, "noise": -91},
    ]
    DESCRIPTION = "Simulated 3-AP walk (demo mode)"

    def __init__(self):
        self.t0 = time.time()
        self.cur = 0
        self.above = 0  # hysteresis counter

    def _rssi(self, ap, t):
        return (ap["base"] + ap["amp"] * math.sin(2 * math.pi * t / ap["period"] + ap["phase"])
                + random.uniform(-1.5, 1.5))

    def collect(self):
        t = time.time() - self.t0
        rssis = [self._rssi(ap, t) for ap in self.APS]
        best = max(range(len(self.APS)), key=lambda i: rssis[i])
        if best != self.cur and rssis[best] > rssis[self.cur] + 5:
            self.above += 1
            if self.above >= 2:  # sticky for 2 samples, then roam
                self.cur = best
                self.above = 0
        else:
            self.above = 0
        ap = self.APS[self.cur]
        s = _base("simulate")
        s["ssid"] = ap["ssid"]
        s["bssid"] = ap["bssid"]
        s["rssi"] = round(rssis[self.cur], 1)
        s["noise"] = ap["noise"]
        s["channel"] = ap["channel"]
        s["freq_mhz"] = ap["freq"]
        s["width_mhz"] = ap["width"]
        s["tx_mbps"] = round(random.uniform(300, 1200), 1)
        s["phy"] = "802.11ax"
        neighbors = [
            {"ssid": a["ssid"], "bssid": a["bssid"], "rssi": round(r, 1),
             "channel": a["channel"], "freq_mhz": a["freq"]}
            for a, r in zip(self.APS, rssis) if a["bssid"] != ap["bssid"]
        ]
        return s, neighbors

    def scan(self):
        return []


# --------------------------------------------------------------- registry ----
class Backend:
    def __init__(self, name, collect_fn, scan_fn, description):
        self.name = name
        self._collect = collect_fn
        self._scan = scan_fn
        self.description = description

    def collect(self):
        return self._collect()

    def scan(self):
        try:
            return self._scan()
        except Exception:
            return []


def get_backend(name="auto"):
    if name == "simulate":
        sim = SimulateBackend()
        return Backend("simulate", sim.collect, sim.scan, SimulateBackend.DESCRIPTION)
    if name == "auto":
        if shutil.which("termux-wifi-connectioninfo"):
            name = "termux"
        elif sys.platform == "win32":
            name = "windows"
        elif sys.platform == "darwin":
            name = "macos"
        else:
            name = "linux"
    table = {
        "windows": (collect_windows, scan_windows, "Windows via netsh (signal % -> approx dBm; no noise floor)"),
        "macos": (collect_macos, scan_macos,
                  "macOS via airport -I, system_profiler fallback (true dBm RSSI + noise floor)"),
        "linux": (collect_linux, scan_linux, "Linux via iw (true dBm RSSI; noise via survey dump)"),
        "termux": (collect_termux, scan_termux, "Android via Termux:API (needs location permission)"),
    }
    if name not in table:
        raise ValueError("unknown backend: %s" % name)
    collect_fn, scan_fn, desc = table[name]
    return Backend(name, collect_fn, scan_fn, desc)


# ------------------------------------------------------------- diagnostics ----
def resolve_backend_name(name="auto"):
    if name == "simulate":
        return "simulate"
    if name == "auto":
        if shutil.which("termux-wifi-connectioninfo"):
            return "termux"
        elif sys.platform == "win32":
            return "windows"
        elif sys.platform == "darwin":
            return "macos"
        return "linux"
    return name


def diagnose_macos():
    helper_sample = _collect_macos_helper()
    sample, _ = collect_macos()
    if sample is not None:
        return True, [
            "Wi-Fi source: %s" % ("authorized local helper" if helper_sample is not None else "macOS fallback (helper did not supply BSSID)"),
            "Channel: %s; RSSI: %s dBm; BSSID: %s" % (
                sample.get("channel"), sample.get("rssi"),
                sample.get("bssid") or "UNAVAILABLE"),
            "WARNING: Roam detection requires BSSID; no BSSID means RSSI/channel tracking only."
            if not sample.get("bssid") else "BSSID is available for roam detection.",
        ]
    ap = _airport_bin()
    if not ap:
        return False, [
            "airport tool not found (looked in %s and PATH)." % _AIRPORT,
            "This macOS version may have moved it — please report this.",
        ]
    lines = ["airport tool: %s" % ap]
    out = run([ap, "-I"], timeout=10)
    if not out.strip():
        return False, lines + [
            "`airport -I` printed nothing.",
            "Is Wi-Fi powered on? Try: networksetup -setairportpower en0 on",
        ]
    for key in ("state", "SSID", "BSSID", "agrCtlRSSI", "agrCtlNoise", "channel"):
        m = re.search(r"^\s*%s:\s*(.+)$" % key, out, re.M)
        if m:
            lines.append("  %s: %s" % (key, m.group(1).strip()))
    if "AirPort: Off" in out:
        return False, lines + [
            "Wi-Fi is OFF on this Mac (very common when docked over Ethernet).",
            "Turn Wi-Fi on and join a network, then rerun.",
        ]
    m = re.search(r"^\s*BSSID:\s*(\S+)", out, re.M)
    bare = re.sub(r"[^0-9a-f]", "", (m.group(1) if m else "").lower())
    if not bare or bare == "0" * 12:
        return False, lines + [
            "Wi-Fi is on, but not associated to any network.",
            "Join a Wi-Fi network and rerun.",
        ]
    return True, lines + ["Radio is readable — captures will work."]


def diagnose_windows():
    out = run(["netsh", "wlan", "show", "interfaces"], timeout=10)
    if not out.strip():
        return False, ["`netsh wlan show interfaces` printed nothing.",
                       "Is there a Wi-Fi adapter? Is its driver installed?"]
    if "There is no wireless interface" in out:
        return False, ["Windows reports no wireless interface.",
                       "Enable the Wi-Fi adapter / install its driver."]
    states = [s.strip() for s in re.findall(r"^\s*State\s*:\s*(.+)$", out, re.M)]
    if any(s.lower() == "connected" for s in states):
        return True, ["Wi-Fi interface found and connected — captures will work."]
    return False, [
        "Wi-Fi adapter found but not connected (state: %s)." % (", ".join(states) or "?"),
        "Join a Wi-Fi network and rerun.",
    ]


def diagnose_linux():
    if not shutil.which("iw"):
        return False, ["`iw` is not installed.",
                       "Install it: sudo apt install iw  (or your distro's equivalent)"]
    iface = _linux_iface()
    if not iface:
        return False, ["`iw dev` shows no wireless interface.",
                       "Is Wi-Fi enabled? A hardware switch / airplane mode can disable it."]
    out = run(["iw", "dev", iface, "link"], timeout=8)
    if not out.strip() or "Not connected" in out:
        return False, ["Interface %s exists but is not associated." % iface,
                       "Join a Wi-Fi network and rerun."]
    m = re.search(r"signal:\s*(-?[\d.]+)", out)
    return True, ["Interface %s associated%s — captures will work."
                  % (iface, " (signal %s dBm)" % m.group(1) if m else "")]


def diagnose_termux():
    if not shutil.which("termux-wifi-connectioninfo"):
        return False, ["termux-wifi-connectioninfo not found.",
                       "Install Termux:API from F-Droid plus the Termux:API app."]
    try:
        d = json.loads(run(["termux-wifi-connectioninfo"], timeout=8))
    except Exception:
        d = None
    if not isinstance(d, dict) or not d.get("bssid"):
        return False, ["Termux:API returned no connection info.",
                       "Grant Location permission to Termux:API (Android requires it for Wi-Fi),",
                       "then make sure Wi-Fi is connected."]
    return True, ["Connected to %s (%s dBm) — captures will work."
                  % (d.get("ssid"), d.get("rssi"))]


def diagnose(backend_name="auto"):
    """Check whether the radio is readable. Returns (ok, [message lines])."""
    backend_name = resolve_backend_name(backend_name)
    if backend_name == "simulate":
        return True, ["simulate backend: always readable (no radio needed)."]
    fn = {"windows": diagnose_windows, "macos": diagnose_macos,
          "linux": diagnose_linux, "termux": diagnose_termux}.get(backend_name)
    if not fn:
        return False, ["unknown backend: %s" % backend_name]
    try:
        return fn()
    except Exception as e:
        return False, ["diagnostic failed: %s" % e]
