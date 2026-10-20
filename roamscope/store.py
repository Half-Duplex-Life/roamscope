"""SQLite storage for samples, roam events and neighbor scans."""
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_epoch REAL NOT NULL,
    ts TEXT NOT NULL,
    ssid TEXT,
    bssid TEXT,
    rssi REAL,
    noise REAL,
    channel INTEGER,
    width_mhz INTEGER,
    freq_mhz INTEGER,
    tx_mbps REAL,
    phy TEXT,
    ping_ms REAL,
    platform TEXT
);
CREATE TABLE IF NOT EXISTS roams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_epoch REAL NOT NULL,
    ts TEXT NOT NULL,
    ssid TEXT,
    from_bssid TEXT,
    to_bssid TEXT,
    rssi_before REAL,
    rssi_after REAL,
    rssi_delta REAL,
    dwell_prev_s REAL,
    best_neighbor_bssid TEXT,
    best_neighbor_rssi REAL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_epoch REAL NOT NULL,
    ts TEXT NOT NULL,
    ssid TEXT,
    bssid TEXT,
    rssi REAL,
    channel INTEGER,
    freq_mhz INTEGER
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_scans_ts ON scans(ts_epoch);
"""


def ts_str(epoch):
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def open_db(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def set_meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))
    db.commit()


def get_meta(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def insert_sample(db, s):
    db.execute(
        """INSERT INTO samples
           (ts_epoch, ts, ssid, bssid, rssi, noise, channel, width_mhz,
            freq_mhz, tx_mbps, phy, ping_ms, platform)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (s.get("ts_epoch"), ts_str(s.get("ts_epoch", 0)), s.get("ssid"),
         s.get("bssid"), s.get("rssi"), s.get("noise"), s.get("channel"),
         s.get("width_mhz"), s.get("freq_mhz"), s.get("tx_mbps"),
         s.get("phy"), s.get("ping_ms"), s.get("platform")),
    )
    db.commit()


def insert_scans(db, neighbors, ts_epoch):
    import time
    ts_epoch = ts_epoch or time.time()
    rows = [
        (ts_epoch, ts_str(ts_epoch), n.get("ssid"), n.get("bssid"),
         n.get("rssi"), n.get("channel"), n.get("freq_mhz"))
        for n in (neighbors or []) if n.get("bssid")
    ]
    if rows:
        db.executemany(
            """INSERT INTO scans
               (ts_epoch, ts, ssid, bssid, rssi, channel, freq_mhz)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
        db.commit()


def insert_roam(db, r):
    db.execute(
        """INSERT INTO roams
           (ts_epoch, ts, ssid, from_bssid, to_bssid, rssi_before, rssi_after,
            rssi_delta, dwell_prev_s, best_neighbor_bssid, best_neighbor_rssi, reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (r.get("ts_epoch"), ts_str(r.get("ts_epoch", 0)), r.get("ssid"),
         r.get("from_bssid"), r.get("to_bssid"), r.get("rssi_before"),
         r.get("rssi_after"), r.get("rssi_delta"), r.get("dwell_prev_s"),
         r.get("best_neighbor_bssid"), r.get("best_neighbor_rssi"),
         r.get("reason")),
    )
    db.commit()


def fetch_samples(db):
    return [dict(r) for r in db.execute("SELECT * FROM samples ORDER BY ts_epoch")]


def fetch_roams(db):
    return [dict(r) for r in db.execute("SELECT * FROM roams ORDER BY ts_epoch")]


def fetch_scans(db):
    return [dict(r) for r in db.execute("SELECT * FROM scans ORDER BY ts_epoch")]
