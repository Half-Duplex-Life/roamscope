"""Five-minute stationary check. Run with Python in the normal Windows session.

Raw local files contain Wi-Fi identifiers. Nothing is uploaded or transmitted.
"""
import argparse
import csv
import json
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Run this on Windows.')
    folder = Path(__file__).resolve().parent / 'roamscope-out' / datetime.now().strftime('windows-check-%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    # Doctor output stays local, including identity and actionable error codes.
    with (folder / 'doctor.txt').open('w', encoding='utf-8') as f:
        result = subprocess.run([sys.executable, 'roamscope.py', '--doctor'], cwd=Path(__file__).resolve().parent,
                                stdout=f, stderr=subprocess.STDOUT)
    if result.returncode:
        print('Preflight did not pass. Review', folder / 'doctor.txt')
        print('No survey started. Keep identifiers private; share redacted errors only.')
        return 1
    result = subprocess.run([sys.executable, 'roamscope.py', '--duration', str(args.seconds), '--interval', '2',
                             '--scan-interval', '0', '--csv', '--no-open', '--out', str(folder)],
                            cwd=Path(__file__).resolve().parent)
    if result.returncode:
        return result.returncode
    files = list(folder.glob('*-samples.csv'))
    rows = list(csv.DictReader(files[0].open(encoding='utf-8'))) if files else []
    valid = [r for r in rows if r.get('bssid')]
    from roamscope.collectors import valid_windows_bssid
    summary = dict(os=platform.system(), python=platform.python_version(), samples=len(rows),
                   valid_bssid_samples=sum(bool(valid_windows_bssid(r.get('bssid'))) for r in rows),
                   distinct_associated_bssids=len({r['bssid'] for r in valid}),
                   rssi_samples=sum(bool(r.get('rssi')) for r in rows),
                   channel_samples=sum(bool(r.get('channel')) for r in rows),
                   html_created=(folder/'report.html').exists(),
                   roaming_validation='Not performed: stationary single-AP check')
    (folder/'shareable-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print('Review the report locally:', folder/'report.html')
    print('Only share shareable-summary.json; raw CSV/doctor/report files contain network identifiers.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
