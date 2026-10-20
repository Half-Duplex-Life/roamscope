"""Roam detection: a roam = BSSID change while the SSID stays the same.

Also records disconnects/reconnects, dwell time on the previous AP, the
strongest same-SSID neighbor visible at roam time, and a rough reason tag:
  sticky  - client clung to a weak AP (RSSI < -70 dBm) before roaming
  fast    - roamed again within 20 s (flapping between APs)
  normal  - everything else
"""


class RoamTracker:
    def __init__(self):
        self.bssid = None
        self.ssid = None
        self.since = None      # epoch when we joined the current BSSID
        self.last_rssi = None

    def _event(self, ts, ssid, frm, to, r_before, r_after, dwell, neighbors, reason):
        best_b, best_r = None, None
        for n in neighbors or []:
            nb = n.get("bssid")
            nr = n.get("rssi")
            if not nb or nr is None or nb == to:
                continue
            if (n.get("ssid") or "") != (ssid or ""):
                continue
            if best_r is None or nr > best_r:
                best_b, best_r = nb, nr
        delta = None
        if r_before is not None and r_after is not None:
            delta = round(r_after - r_before, 1)
        return {
            "ts_epoch": ts,
            "ssid": ssid,
            "from_bssid": frm,
            "to_bssid": to,
            "rssi_before": r_before,
            "rssi_after": r_after,
            "rssi_delta": delta,
            "dwell_prev_s": round(dwell, 1) if dwell is not None else None,
            "best_neighbor_bssid": best_b,
            "best_neighbor_rssi": best_r,
            "reason": reason,
        }

    def feed(self, sample, neighbors):
        """Feed one sample. Returns a roam-event dict, or None."""
        b = sample.get("bssid")
        ssid = sample.get("ssid")
        ts = sample.get("ts_epoch")
        rssi = sample.get("rssi")
        event = None

        if self.bssid is None and b is not None:
            if self.since is not None:
                # we had disconnected earlier -> this is a reconnect
                event = self._event(ts, ssid, None, b, None, rssi, 0,
                                    neighbors, "reconnect")
            self.bssid, self.ssid, self.since = b, ssid, ts
        elif b is None and self.bssid is not None:
            dwell = ts - (self.since or ts)
            event = self._event(ts, self.ssid, self.bssid, None,
                                self.last_rssi, None, dwell,
                                neighbors, "disconnect")
            self.bssid, self.ssid, self.since = None, None, None
        elif (b is not None and self.bssid is not None and b != self.bssid
                and (ssid or "") == (self.ssid or "")):
            dwell = ts - (self.since or ts)
            before = self.last_rssi
            if before is not None and before < -70:
                reason = "sticky"
            elif dwell < 20:
                reason = "fast"
            else:
                reason = "normal"
            event = self._event(ts, ssid, self.bssid, b, before, rssi,
                                dwell, neighbors, reason)
            self.bssid, self.ssid, self.since = b, ssid, ts
        elif b is not None and b != self.bssid:
            # SSID changed (or first sample): adopt quietly, no roam counted
            self.bssid, self.ssid, self.since = b, ssid, ts

        self.last_rssi = rssi
        return event
