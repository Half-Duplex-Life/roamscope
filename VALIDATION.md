# RoamScope validation and Windows check

## Validation status

On 20 October 2026, a Windows single-AP check recorded 10 samples over approximately 18 seconds. All 10 had a valid connected BSSID obtained using Native Wi-Fi, with one stable associated AP. RSSI, channel, frequency and transmit rate were recorded. CSV and SQLite counts agreed. The HTML contained an AP entry and embedded SVG charts. Zero observed transitions was expected; neighbor scanning was disabled. Raw identifiers and captures are excluded from this repository. Browser display confirmation remains pending.

The reported macOS pilot detected nine BSSID transitions aligned with nine Mist events within approximately 0–2 seconds. Windows AP-to-AP roaming, per-roam 802.11r negotiation and actual interruption duration have not been validated; the latter two remain outside scope.

## Run on this Windows computer

1. Extract this ZIP into a new folder. Keep the whole source hierarchy.
2. With Python 3 installed, double-click Windows-Check.cmd. Or run `py -3 windows_check.py` in PowerShell from the extracted folder.
3. The preflight must show a real connected BSSID. If it fails, the check stops and saves doctor.txt locally. Do not run elevated solely to bypass a failure; inspect the error and applicable Windows permissions.
4. Leave the laptop connected to the home AP for five minutes. The check disables neighbor scanning and does not change Wi-Fi settings.
5. Open the report.html path printed at completion. Verify the summary, RSSI graph, associated AP row, channel information when available, and unavailable-noise/SNR message. A stationary run should normally show one BSSID and zero observed transitions; it cannot validate roaming.
6. Share only shareable-summary.json, plus whether the report displayed correctly. It excludes SSID, BSSID, AP names and local paths. Raw CSV, database, report and doctor output remain sensitive local files.

If the launcher cannot find Python, install an approved Python 3 release or use the full path of your existing Python interpreter with windows_check.py. Matplotlib remains recommended for the original graphs; the report can now use built-in SVG charts without it.

## Collection and reporting behavior

- Read connected BSSID using the documented Native Wi-Fi current-connection query, with explicit ctypes layouts and buffer/handle cleanup.
- Retain an English netsh fallback accepting both BSSID and AP BSSID. Do not guess localized keys, choose arbitrarily between connected adapters, or use scan/client MACs as association identity.
- Supplement native fields from netsh only when associated BSSIDs match. Frequency stays unknown without reliable band evidence.
- Fail Windows preflight when BSSID is missing instead of declaring capture ready from connected state alone.
- Keep RSSI visible when BSSID is absent; identify AP/roaming coverage gaps and escape network names in HTML.
- Add built-in SVG chart fallback if Matplotlib is not installed. Existing Matplotlib chart path remains available.
- Preserve the macOS collector functions and Swift helper source unchanged.

## Test matrix

| Check | Result |
| --- | --- |
| Windows parser, Native Wi-Fi ABI conversion and fallback behavior | PASS: synthetic tests |
| Invalid identifiers, adapter ambiguity and preflight rejection | PASS: synthetic tests |
| Missing-BSSID, stationary, roaming and empty reports; HTML escaping | PASS: synthetic tests |
| Automated tests | 17 passed |
| macOS collector and Swift source compared with original | Unchanged |
| Windows single-AP collection and export consistency | PASS: 10 samples, approximately 18 seconds |
| HTML AP entry and embedded chart content | PASS: file inspection |
| Browser display on the test laptop | Awaiting confirmation |
| Windows multi-AP roaming | Pending |
| Original affected corporate capture reproduction | Untested: captures unavailable |
| Native macOS execution and Matplotlib rendering of this update | Untested |

Run `python -m unittest discover -s tests -v` from the source folder.

## API references

- [WlanQueryInterface](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlanqueryinterface)
- [WLAN_ASSOCIATION_ATTRIBUTES](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/ns-wlanapi-wlan_association_attributes)
- [WLAN_CONNECTION_ATTRIBUTES](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/ns-wlanapi-wlan_connection_attributes)

Licensed under the [MIT License](LICENSE), copyright (c) 2026 Param Chawla. No real network captures or identifiers are included.
