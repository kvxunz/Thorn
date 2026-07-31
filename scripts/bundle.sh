#!/bin/bash
# Build release binary and assemble Thorn.app.
set -euo pipefail

cd "$(dirname "$0")/.."

# CLT toolchain lacks SwiftUI macro plugins; use full Xcode.
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode-beta.app/Contents/Developer}"

swift build -c release

APP="build/Thorn.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp .build/release/Thorn "$APP/Contents/MacOS/Thorn"
cp Resources/Info.plist "$APP/Contents/Info.plist"
cp Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
# Phonics dictionary (single-word ⌥A path); regenerate with
# scripts/build_phonics_dict.py.
cp Resources/phonics-en.tsv "$APP/Contents/Resources/phonics-en.tsv"

# Stable identity so the TCC accessibility grant survives rebuilds.
# Hash, not name: two same-named "DocR Dev" certs in keychain make the name ambiguous.
codesign --force --sign DBC95BDD0F6B5D17A0DDEEE2AB051CACFDBCE4A1 "$APP"
codesign --verify --strict "$APP"
codesign -dv "$APP" 2>&1 | grep -E "^Signature|^Authority" || true

echo "Built: $APP"
echo "Install: cp -r $APP /Applications/"
