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
#
# The list is derived from server.py's own imports rather than maintained by
# hand: a new parser module forgotten here ships an app that dies with an
# ImportError on first parse, and no suite would catch it — every test imports
# from the checkout, where the file is always present.
SIDECAR_MODULES=$(/usr/bin/python3 - <<'PY'
import ast
import pathlib

root = pathlib.Path("sidecar")
local = {path.stem for path in root.glob("*.py")}
seen: set[str] = set()
stack = ["server"]
while stack:
    name = stack.pop()
    if name in seen:
        continue
    seen.add(name)
    tree = ast.parse((root / f"{name}.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found = [node.module.split(".")[0]]
        else:
            continue
        stack += [module for module in found if module in local]
print("\n".join(sorted(seen)))
PY
)
for module in $SIDECAR_MODULES; do
  cp "sidecar/$module.py" "$APP/Contents/Resources/sidecar/$module.py"
done
cp sidecar/relation_holdout.json "$APP/Contents/Resources/sidecar/relation_holdout.json"
echo "Sidecar modules: $(echo "$SIDECAR_MODULES" | tr '\n' ' ')"

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
