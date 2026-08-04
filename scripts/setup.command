#!/bin/bash
# Thorn 首次安装：装齐 App 自己带不动的那 7 GB。
#
# 双击运行。若 macOS 拦下这个脚本，打开「终端」把这一行粘进去回车：
#   bash "/Volumes/Thorn/setup.command"
set -uo pipefail

APP="/Applications/Thorn.app"
OLLAMA_MODEL="hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    %s\033[0m\n' "$1"; }
die() { printf '\n\033[31m失败：%s\033[0m\n\n' "$1"; exit 1; }

ask() {
  local reply
  read -r -p "$1 [y/N] " reply </dev/tty
  [[ "$reply" == [yY] ]]
}

printf '\033[1mThorn 安装助手\033[0m\n'
echo "这个脚本会检查并安装 Thorn 运行所需的本地环境。"
echo "全程只往你的机器上装东西，不上传任何内容。"

step "检查机型与系统"
[[ "$(uname -m)" == "arm64" ]] || die "Thorn 只支持 Apple 芯片的 Mac，这台是 $(uname -m)。"
major=$(sw_vers -productVersion | cut -d. -f1)
(( major >= 14 )) || die "需要 macOS 14 或更新，这台是 $(sw_vers -productVersion)。"
echo "    $(sw_vers -productName) $(sw_vers -productVersion) / $(uname -m)"

step "检查 Thorn.app"
if [[ ! -d "$APP" ]]; then
  die "还没把 Thorn 拖进「应用程序」。先把左边的 Thorn 图标拖到右边的 Applications 文件夹，再运行本脚本。"
fi
echo "    已安装：$APP"

# 从网上下载的 App 带着隔离标记，macOS 会以「无法验证开发者」拒绝打开。
# Thorn 用的是自签名证书（作者本人签的，不是 Apple 公证的），所以这一步需要
# 你自己确认：你信任把这个 DMG 发给你的人。
if xattr -p com.apple.quarantine "$APP" >/dev/null 2>&1; then
  step "解除隔离标记"
  echo "    macOS 给下载来的 App 打了隔离标记。Thorn 是自签名的，没有经过 Apple 公证，"
  echo "    所以默认会被拦下。移除这个标记等于你确认信任这份 App 的来源。"
  echo "    （不做也行，那就在首次打开被拦后，去 系统设置 → 隐私与安全性 → 仍要打开。）"
  if ask "    现在移除隔离标记？"; then
    xattr -dr com.apple.quarantine "$APP" && echo "    已移除。"
  else
    warn "跳过。首次打开时请手动放行。"
  fi
fi

step "检查 uv（负责跑 Thorn 的 Python 句法引擎）"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
  echo "    已安装：$(uv --version)"
elif command -v brew >/dev/null 2>&1 && ask "    未安装。用 Homebrew 安装 uv？"; then
  brew install uv || die "uv 安装失败。"
elif ask "    未安装。从 astral.sh 官方脚本安装 uv？"; then
  curl -LsSf https://astral.sh/uv/install.sh | sh || die "uv 安装失败。"
  export PATH="$HOME/.local/bin:$PATH"
else
  die "没有 uv，Thorn 无法解析句子。装好后重新运行本脚本。"
fi
command -v uv >/dev/null 2>&1 || die "uv 装好了但不在 PATH 里，重开一个终端再试。"

step "下载句法引擎（约 1.5 GB，慢，只需一次）"
echo "    包含 spaCy、Benepar、PyTorch 和英文句法权重。"
echo "    这一步会持续几分钟到十几分钟，中途没有输出是正常的。"
if uv run --script "$APP/Contents/Resources/sidecar/server.py" --install-models; then
  echo "    完成。"
else
  die "句法引擎安装失败。检查网络后重新运行本脚本。"
fi

step "检查 Ollama（负责中文翻译）"
if ! command -v ollama >/dev/null 2>&1 && [[ ! -d /Applications/Ollama.app ]]; then
  if command -v brew >/dev/null 2>&1 && ask "    未安装。用 Homebrew 安装 Ollama？"; then
    brew install --cask ollama || die "Ollama 安装失败。"
  else
    warn "未安装 Ollama。请到 https://ollama.com 下载安装，然后重新运行本脚本。"
    open "https://ollama.com/download" 2>/dev/null || true
    die "缺少 Ollama。"
  fi
fi
[[ -d /Applications/Ollama.app ]] && open -ga Ollama 2>/dev/null || true
for _ in $(seq 1 15); do
  curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 \
  || die "Ollama 没有在 127.0.0.1:11434 上响应。手动打开 Ollama 后重新运行本脚本。"
echo "    Ollama 正在运行。"

step "下载翻译模型（6.2 GB，最慢的一步）"
if ollama list 2>/dev/null | grep -Fq "$OLLAMA_MODEL"; then
  echo "    已存在，跳过。"
elif ollama pull "$OLLAMA_MODEL"; then
  echo "    完成。"
else
  die "模型下载失败。网络恢复后重新运行本脚本，已下载的部分会续上。"
fi

step "启动 Thorn"
open -a "$APP"
cat <<'DONE'

  装完了。菜单栏右上角会出现一个 ∂ 图标。

  还差最后一步，必须你手动做：
    系统设置 → 隐私与安全性 → 辅助功能 → 允许 Thorn
  不给这个权限，⌥A 取不到你选中的文字。

  用法：
    ⌥A  选中英文 → 拆句 + 翻译（选中单个词则拆拼读）
    ⌥S  框选屏幕任意位置的英文 → 识别后拆解
    ⌥X  打开输入框，写中文 → 换成英文并拆解
    ⌥Z  重现上一次结果

  第一句会慢十几秒（模型冷启动），之后就快了。

DONE
