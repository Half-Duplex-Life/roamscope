#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
APP="$PWD/RoamScopeWiFiHelper.app"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>RoamScopeWiFiHelper</string>
<key>CFBundleIdentifier</key><string>org.roamscope.wifihelper.localtest</string>
<key>CFBundleName</key><string>RoamScope Wi-Fi Helper</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>CFBundleShortVersionString</key><string>0.1</string>
<key>NSLocationWhenInUseUsageDescription</key><string>Read the current Wi-Fi network identity to diagnose access point roaming.</string>
</dict></plist>
PLIST
xcrun swiftc -framework Cocoa -framework CoreLocation -framework CoreWLAN -framework Network main.swift -o "$APP/Contents/MacOS/RoamScopeWiFiHelper"
/usr/bin/plutil -lint "$APP/Contents/Info.plist"
/usr/bin/codesign --force --sign - "$APP"
/usr/bin/codesign --verify --verbose=2 "$APP"
echo "Built: $APP"
echo "If locally built apps are permitted by your organization, launch using: open \"$APP\""
