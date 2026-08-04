#!/bin/bash
# Package build/Thorn.app into a distributable DMG.
#
# The disk image carries 9 MB; the app needs roughly 7.7 GB of local Python
# environment, syntax weights and an Ollama model that cannot live in a bundle.
# setup.command is what closes that gap on the recipient's machine, so it ships
# beside the app rather than as a paragraph of instructions nobody follows.
set -euo pipefail

cd "$(dirname "$0")/.."

APP="build/Thorn.app"
[[ -d "$APP" ]] || ./scripts/bundle.sh

VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" Resources/Info.plist)
VOLUME="Thorn"
STAGING="build/dmg"
DMG="build/Thorn-$VERSION.dmg"

rm -rf "$STAGING" "$DMG"
mkdir -p "$STAGING"

# ditto, not cp: the bundle's signature dies without resource forks and xattrs.
ditto --rsrc --extattr --acl "$APP" "$STAGING/Thorn.app"
ln -s /Applications "$STAGING/Applications"
cp scripts/setup.command "$STAGING/安装助手.command"
chmod +x "$STAGING/安装助手.command"

cat > "$STAGING/先读我.txt" <<'TXT'
Thorn — 英文精读工具（macOS 菜单栏）

安装两步：

  1. 把左边的 Thorn 拖到右边的 Applications 文件夹。
  2. 双击「安装助手.command」，按提示走完。

第 2 步会装齐 Thorn 自己带不动的东西：Python 句法引擎（约 1.5 GB）和
本地翻译模型（6.2 GB）。总共要下 7 GB 出头，请留够时间和硬盘。
中途断了没关系，重新双击安装助手会接着来。

如果双击安装助手被 macOS 拦下，打开「终端」，把下面这行粘进去回车：

  bash "/Volumes/Thorn/安装助手.command"

要求：Apple 芯片的 Mac（M1 及以后），macOS 14 或更新。

关于安全提示：这个 App 是作者自己签名的，没有花钱走 Apple 的公证流程，
所以首次打开时系统会说「无法验证开发者」。安装助手会问你是否解除这个
标记；也可以拒绝，然后在被拦时去 系统设置 → 隐私与安全性 → 仍要打开。
装不装、放不放行，取决于你信不信发给你这个文件的人。

所有解析和翻译都在本机完成，句子和截图不出这台 Mac。
TXT

hdiutil create \
  -volname "$VOLUME" \
  -srcfolder "$STAGING" \
  -ov -format UDZO \
  "$DMG" >/dev/null

rm -rf "$STAGING"
echo "Built: $DMG ($(du -h "$DMG" | cut -f1))"
