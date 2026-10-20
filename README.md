# RoamScope

Endpoint-based Wi-Fi roaming and RF diagnostics tool for macOS and Windows.

RoamScope samples connected endpoint Wi-Fi telemetry, detects observed BSSID transitions, and creates local reports for comparison with infrastructure telemetry.

## Validation status

The reported macOS pilot detected **nine BSSID transitions**, aligned with **nine Mist roaming events within approximately 0–2 seconds** in compared displayed timestamps. This supports transition detection in that pilot. Raw captures and Mist exports are excluded. **Windows validation remains pending.** Per-roam 802.11r negotiation and actual roaming interruption duration are outside the current scope.

## Features and architecture

- Samples SSID, BSSID, RSSI, channel, band, primary-channel frequency and available noise/SNR and transmit-rate fields.
- Records BSSID changes within the same SSID, signal changes, AP dwell time and available neighbor scans.
- Produces SQLite, HTML graphs and optional CSV exports, a local live dashboard, AP-name mappings and synthetic simulation.
- macOS: Python reads a locally built Swift CoreWLAN helper over loopback HTTP port 18763. Keep the helper open; Location Services permission may be needed. The bridge currently selects interface `en0`.
- Windows: Python reads Windows Wi-Fi telemetry; no Swift helper is needed.

Linux and Termux backends also exist in source; those are outside this pilot validation.

## Requirements

Python 3 with venv/pip and `matplotlib>=3.5` from requirements.txt. macOS needs Apple Command Line Tools/Swift and permission to run a locally built helper. Windows needs a Wi-Fi adapter/driver with readable netsh telemetry. Exact minimum OS/Python versions have not been established by this pilot.

## Installation

Extract RoamScope.zip and work inside the roamscope folder containing roamscope.py.

### macOS

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd RoamScopeHelper
bash ./build.sh
open ./RoamScopeWiFiHelper.app
cd ..
python roamscope.py --doctor
```

In the helper, request Location Access if needed, select Read Wi-Fi, confirm a real BSSID, and keep it open. The build is locally ad-hoc signed.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
netsh wlan show interfaces
.\.venv\Scripts\python.exe roamscope.py --doctor
```

Use that environment interpreter for later commands. Full instructions: [macOS PDF](docs/macOS_Setup_Guide.pdf), [Windows PDF](docs/Windows_Setup_Guide.pdf).

The original PDFs are preserved as historical installation/test guides. The macOS PDF references an older teammate package and pre-pilot status; the validation status above supersedes that status text. Follow organizational installation and sharing policies.

## Usage

With the environment active, or its Python interpreter specified:

```sh
python roamscope.py --duration 300 --interval 2 --csv
python roamscope.py --duration 0 --interval 2 --csv --name survey
python roamscope.py --duration 300 --live --csv
python roamscope.py --simulate --duration 30 --csv --no-open
python roamscope.py --report roamscope-out/SESSION.sqlite --no-open
python analyze_survey.py roamscope-out --out roamscope-out
python roamscope.py --help
```

Duration zero runs until Ctrl+C. Verify clean termination on Windows, or use a finite duration. The optional dashboard is at http://127.0.0.1:8899/report.html. `--ap-names FILE` accepts CSV (`bssid,name`) or JSON mappings; keep inventories private. `--ping HOST` records sampled round-trip latency, not interruption duration.

## Outputs

The default roamscope-out folder contains timestamped roamscope-*.sqlite databases and a regenerated report.html (which can replace the preceding report). `--csv` adds timestamped *-samples.csv, *-roams.csv and *-scans.csv files. The analyzer writes survey-analysis.md. Reports retain network identifiers; AP labels and shortened display BSSIDs do not anonymize the underlying data.

## Troubleshooting and limitations

- macOS missing BSSID: keep the helper open, check Location Services, try `curl --noproxy '*' --max-time 5 http://127.0.0.1:18763/`, then rerun --doctor.
- Windows missing BSSID: compare netsh wlan show interfaces and --doctor; check adapter, driver, permissions and locale.
- Missing packages: install requirements using the virtual environment interpreter.
- Empty scans or missing RF fields may reflect OS/driver limitations, not neighboring AP quality.
- Two-second polling can miss brief transitions and does not establish exact roam start/end times.
- Sticky, fast and normal labels are heuristics; fast is not proof of 802.11r.
- This is endpoint telemetry, not management-frame capture, a predictive RF survey or production certification.

See the [knowledge article](KNOWLEDGE_ARTICLE.md). Optional demo scripts produce synthetic presentation assets and need additional ReportLab/Pillow dependencies; they are not required for normal operation.

## Privacy and ownership

Do not commit real captures, client MACs, private SSIDs/BSSIDs, AP inventories, internal screenshots, credentials or generated reports. Browser uploads do not automatically honor .gitignore.

No license has been selected or added. The supplied archive does not establish employer IP clearance or third-party provenance. Confirm applicable rights before broader distribution or choosing a license. Keep the repository private unless explicitly authorized otherwise.
