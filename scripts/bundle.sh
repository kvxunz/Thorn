#!/bin/bash
# Build release binary and assemble Thorn.app.
set -euo pipefail

cd "$(dirname "$0")/.."

# CLT toolchain lacks the complete SwiftUI SDK/plugin set; use full Xcode.
# Prefer the stable installation, while retaining the beta path for machines
# that have not installed a stable Xcode yet. An explicit DEVELOPER_DIR wins.
if [[ -z "${DEVELOPER_DIR:-}" ]]; then
  if [[ -d /Applications/Xcode.app/Contents/Developer ]]; then
    export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
  elif [[ -d /Applications/Xcode-beta.app/Contents/Developer ]]; then
    export DEVELOPER_DIR="/Applications/Xcode-beta.app/Contents/Developer"
  else
    echo "Full Xcode is required (set DEVELOPER_DIR to its Developer directory)." >&2
    exit 1
  fi
fi

swift build -c release

APP="build/Thorn.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/sidecar"

cp .build/release/Thorn "$APP/Contents/MacOS/Thorn"
cp Resources/Info.plist "$APP/Contents/Info.plist"
cp Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
# Phonics dictionary (single-word ⌥A path); regenerate with
# scripts/build_phonics_dict.py.
cp Resources/phonics-en.tsv "$APP/Contents/Resources/phonics-en.tsv"
# Runtime-only Python sidecar. Keeping these modules inside the signed app
# removes the installed binary's dependency on the source checkout path.
for file in server.py alignment.py chunk_rules.py constituency.py grammar_notes.py teaching_tree.py; do
  cp "sidecar/$file" "$APP/Contents/Resources/sidecar/$file"
done

# Stable identity so the TCC accessibility grant survives rebuilds.
# Hash, not name: two same-named "DocR Dev" certs in keychain make the name ambiguous.
# Override for another keychain identity; an ad-hoc fallback keeps local builds
# possible when no signing certificate is installed (TCC will not persist then).
SIGNING_IDENTITY="${THORN_CODESIGN_IDENTITY:-DBC95BDD0F6B5D17A0DDEEE2AB051CACFDBCE4A1}"
if ! security find-identity -v -p codesigning | grep -Fq -- "$SIGNING_IDENTITY"; then
  if [[ -n "${THORN_CODESIGN_IDENTITY:-}" ]]; then
    echo "Requested signing identity not found: $SIGNING_IDENTITY" >&2
    exit 1
  fi
  SIGNING_IDENTITY="-"
  echo "Signing ad hoc; set THORN_CODESIGN_IDENTITY to preserve TCC grants." >&2
fi
codesign --force --sign "$SIGNING_IDENTITY" "$APP"
codesign --verify --strict "$APP"
codesign -dv "$APP" 2>&1 | grep -E "^Signature|^Authority" || true

echo "Built: $APP"
echo "Install: sudo rm -rf /Applications/Thorn.app && sudo ditto --rsrc --extattr --acl $APP /Applications/Thorn.app"
