"""Small shared helpers: subprocess runner, channel/frequency math, ping."""
import re
import subprocess
import sys


def run(cmd, timeout=12):
    """Run a command, return stdout ('' on any failure). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout or ""
    except Exception:
        return ""


def channel_to_freq_mhz(channel, band=None):
    """Channel number -> center frequency in MHz. band hint: '2.4', '5' or '6'."""
    if channel is None:
        return None
    try:
        ch = int(channel)
    except (TypeError, ValueError):
        return None
    if band == "6":
        return 5950 + 5 * ch
    if 1 <= ch <= 14:
        return 2484 if ch == 14 else 2407 + 5 * ch
    if 15 <= ch <= 165:
        return 5000 + 5 * ch
    if 1 <= ch <= 233:  # 6 GHz low channels only reachable with band hint
        return 5950 + 5 * ch
    return None


def freq_to_channel(freq_mhz):
    """Frequency in MHz -> channel number (best effort)."""
    if freq_mhz is None:
        return None
    try:
        f = int(freq_mhz)
    except (TypeError, ValueError):
        return None
    if 2412 <= f <= 2484:
        return 14 if f == 2484 else (f - 2407) // 5
    if 5000 <= f <= 5895:
        return (f - 5000) // 5
    if 5955 <= f <= 7115:
        return (f - 5950) // 5
    return None


def freq_to_band(freq_mhz):
    if freq_mhz is None:
        return None
    if freq_mhz < 3000:
        return "2.4 GHz"
    if freq_mhz < 6000:
        return "5 GHz"
    return "6 GHz"


def ping_ms(host, count=1):
    """Single ping round-trip in ms, or None. Never raises."""
    if not host:
        return None
    try:
        if sys.platform.startswith("win"):
            cmd = ["ping", "-n", str(count), "-w", "1000", host]
        else:
            cmd = ["ping", "-c", str(count), "-W", "1", host]
        out = run(cmd, timeout=6)
        m = re.search(r"time[=<]\s*([\d.]+)\s*ms", out)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def short_bssid(bssid):
    if not bssid:
        return "—"
    return bssid[-8:].upper()
