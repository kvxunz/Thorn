# 安装、配置与使用指南

Thorn 是 macOS 菜单栏英文精读工具。句法分析使用本地 spaCy/Benepar 模型及结构规则，翻译使用本地 Ollama。无需购买云端 API，也无需填写 API Key。首次准备环境和模型需要网络；下载完成后，正常解析和翻译在本机进行。

## 选择安装方式

| 方式 | 适合谁 | 是否需要 Xcode |
| --- | --- | --- |
| 预构建 DMG | 希望直接使用的人；前提是发布页有适用安装包 | 不需要完整 Xcode |
| 从源码构建 | 开发者、希望使用尚未发布改动的人 | 需要完整 Xcode，不能仅装 Command Line Tools |

两种方式均需要 Apple Silicon Mac、macOS 14 或更新版本、uv 和正在运行的 Ollama。安装助手会检查机型和系统。Intel Mac、Windows、Linux 不属于当前 App 支持范围。

App 包不包含大型模型。首次安装会下载 Python 依赖、英文解析权重和翻译模型，合计为数 GB；默认翻译模型下载量约 6.2 GB，实际占用还包括缓存。请预留额外磁盘空间。内存需求随模型和其他运行程序而变化，项目没有给出经过系统测试的最低内存保证。

## 路线一：使用 DMG

1. 打开 [GitHub Releases](https://github.com/kvxunz/Thorn/releases)，阅读对应版本说明并下载 DMG。没有适用包时使用下一节的源码路线。
2. 打开镜像，将 `Thorn.app` 拖入 `Applications`。不要长期直接运行镜像内的 App。
3. 双击镜像里的 `安装助手.command`。它会检查 `/Applications/Thorn.app`、安装或查找 uv、准备句法模型、检查 Ollama、下载默认翻译模型并验证摘要。
4. 等待安装助手明确报告完成。首次下载可能很慢；出现错误时保留终端输出，检查网络后重跑。安装助手会复用已满足的环境。
5. 启动 Thorn，按后文完成权限配置和首次测试。

脚本被系统拦截时，可在终端执行以下命令。镜像挂载名不同则替换路径，或将脚本直接拖到终端定位：

```sh
bash "/Volumes/Thorn/安装助手.command"
```

**安全提示：** 当前打包流程不包含 Apple 公证；自签名或 ad-hoc 签名不能等同于 Apple Developer ID。只运行可信来源的包和脚本。安装助手会询问是否移除该 App 的隔离标记；也可以拒绝，并通过系统设置中的安全提示手动处理。不要关闭整个系统的 Gatekeeper。

## 路线二：从源码构建

以下命令在终端执行。安装完整 Xcode 并先启动一次，完成其首次组件安装。uv 和 Ollama 可从各自官方网站安装；如果已经使用 Homebrew，也可以执行：

```sh
brew install uv
brew install --cask ollama
```

确认工具可用：

```sh
uname -m
sw_vers -productVersion
uv --version
ollama --version
```

下载仓库并进入目录：

```sh
git clone https://github.com/kvxunz/Thorn.git
cd Thorn
```

使用你希望安装的发布标签或分支。不要假设默认分支总是包含最新开发修复；对应提交可在 GitHub 提交记录中核对。

准备模型并构建：

```sh
open -a Ollama
uv run --locked --script sidecar/server.py --install-models
ollama pull hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K
bash scripts/bundle.sh
```

`bundle.sh` 自动查找 `/Applications/Xcode.app`，其次查找 Xcode-beta；自定义安装位置可指定：

```sh
DEVELOPER_DIR="/你的路径/Xcode.app/Contents/Developer" bash scripts/bundle.sh
```

成功后得到 `build/Thorn.app`。首次安装时，将它复制到 `/Applications`：

```sh
ditto --rsrc --extattr --acl build/Thorn.app /Applications/Thorn.app
open /Applications/Thorn.app
```

**如果已经有旧版，不要直接执行上述覆盖命令，先按「升级与回滚」处理。** `/Applications` 写入被拒绝时，通过 Finder 操作并按系统提示授权，不要随意改变整个目录权限。

构建脚本优先使用配置的签名身份；找不到默认身份时会退回 ad-hoc。开发者可通过 `THORN_CODESIGN_IDENTITY` 指定自己的有效签名身份。签名身份改变后可能需要重新授予辅助功能权限。

安装后的 App 使用包内 sidecar，不需要一直保留仓库；uv、模型环境和 Ollama 仍是运行依赖。不要在未安装依赖的情况下仅复制 App 就认为安装完成。

## 首次配置与运行

### 1. 找到菜单栏图标

Thorn 是菜单栏应用，启动后不会出现常驻主窗口。找屏幕顶部菜单栏图标，点击后打开「设置…」。没有主窗口不代表启动失败。

### 2. 授予权限

在「系统设置 → 隐私与安全性」中：

- **辅助功能**：允许 `/Applications/Thorn.app`，用于 `⌥A` 读取选区。
- **屏幕录制**：使用 `⌥S` 时按系统提示授权；名称可能随 macOS 版本变化。
- 授权后如仍无效，退出并重新打开 Thorn；重签名后应核对权限列表中的旧条目。

`⌥X` 的手动输入不读取其他应用选区，也不需要截图权限。权限必须由你在系统界面确认，安装脚本不能代替。

### 3. 配置本地翻译

打开 Ollama，并确认其本地接口可访问：

```sh
curl --fail http://127.0.0.1:11434/api/tags
ollama list
```

Thorn 设置中的端点固定为 `http://127.0.0.1:11434`，不是可配置的远程服务。点击「刷新模型」，在「整句翻译」中选择已下载模型。默认使用 `hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K`；其他模型可以选择，但不保证翻译质量和指令兼容性。

首次下载完成不代表 Ollama 服务已启动。仅安装 CLI 的用户可在独立终端运行 `ollama serve`；已由 Ollama App 提供服务时不必重复启动。

### 4. 做一次完整测试

在 TextEdit 新建文档，输入 `The scientist who discovered the comet received a prize.`，选中整句并按 `⌥A`。

预期依次看到：结构树出现、主干角色可辨、从句可展开、随后底部出现中文翻译。第一次模型冷启动比后续请求慢，时间取决于机器；不要把文档中的耗时估算当成超时保证。

解析和翻译串行执行，翻译失败时保留结构树。项目有意不缓存翻译，因此重复请求仍可能执行模型调用。sidecar 空闲后会退出，再次使用需要重新加载。

## 日常使用

| 快捷键 | 操作 |
| --- | --- |
| `⌥A` | 选中英文后拆句；单词输入改为自然拼读 |
| `⌥S` | 框选屏幕区域，经本机 OCR 识别后拆解；`Esc` 取消 |
| `⌥X` | 输入中文、回车，先翻译成英文，再分析英文结构 |
| `⌥Z` | 重现上次结果 |

`⌥` 就是 Option 键。点击从句箭头展开子层，悬停查看原文高亮；右上角提供复制和固定浮窗操作。普通浮窗可用 `Esc` 或点击外部关闭。

选中中文时会走中译英流程。单词拼读优先用内置词典，未收录词只做近似拆分。OCR 识别错误也会影响后续分析，遇到异常先核对原文。

## 升级与回滚

1. 确认新版来源，先完成下载或构建；不要边运行边修改 App 包。
2. 从菜单栏退出 Thorn，等待进程退出。
3. 用 Finder 将旧 `/Applications/Thorn.app` 压缩成备份，保存到单独位置。压缩包不会作为第二个可启动 App 显示。
4. 将旧 App 移到废纸篓，再复制新版到 `/Applications`，避免合并遗留文件。
5. 运行新版，检查权限、模型设置和一次完整拆句。成功前不要清空旧版备份。
6. 测试完成后，退出 DMG；不需要的 `build/Thorn.app` 可移除，避免搜索或启动列表出现两份同名应用。

正常替换 App 不需要清除偏好设置、uv 环境或 Ollama 模型。若新版异常，退出它，将其移出 `/Applications`，再解压备份恢复旧版。不要同时启动两个版本。

源码升级先检查 `git status` 并保留自己的修改，再更新所选分支，重跑锁定模型安装和构建步骤。制作新的分发镜像前应先重新运行 `bundle.sh`，因为 `dmg.sh` 会复用已经存在的 `build/Thorn.app`：

```sh
bash scripts/bundle.sh
bash scripts/dmg.sh
```

## 故障排查

| 现象 | 检查及处理 |
| --- | --- |
| 启动后没有窗口 | 检查菜单栏；这是菜单栏应用 |
| `⌥A` 没反应 | 确认有选中文本、辅助功能授权指向当前 App、快捷键未冲突；用 TextEdit 对照测试 |
| `⌥S` 无法截图 | 检查屏幕录制权限；授权后重启 App |
| `uv` 找不到 | 在终端执行 `uv --version`；确认标准安装路径，重跑安装助手 |
| 首句一直加载或提示解析服务失败 | 运行下方包内模型安装命令，查看完整错误；检查网络、空间及模型校验结果 |
| 有结构但没有翻译 | 检查 Ollama 是否启动、`/api/tags` 是否响应、设置中的模型是否确实安装 |
| 模型摘要不一致 | 不要直接改锁文件绕过校验；核对 App 版本及模型来源，提交错误信息 |
| Xcode 构建失败 | 确认完整 Xcode 已初始化，必要时指定 `DEVELOPER_DIR` |
| 两份 Thorn 图标 | 检查应用目录、构建目录和挂载镜像；保留一份安装副本并退出镜像，不要删除用户数据来修图标 |
| 句子结构明显错误 | 核对 OCR/复制原文；记录原句、错误归属、期望解释及版本，提交 Issue |

对已安装版本重新准备句法模型：

```sh
uv run --locked --script /Applications/Thorn.app/Contents/Resources/sidecar/server.py --install-models
```

如果曾手动设置开发脚本覆盖路径，移除它后重启 App，恢复包内引擎：

```sh
defaults delete com.xvz.thorn sidecarScript
```

键不存在时提示未找到是正常的。不要直接删除整个偏好域来解决单个路径问题。

## 验证与反馈

在仓库根目录运行：

```sh
swift test --skip LiveHYMT2
uv run --locked --script scripts/check_sidecar.py
uv run --locked --script sidecar/server.py --check-regressions
bash scripts/run-sidecar.sh tree_snapshot.py
```

前两项是快速验证；后两项需要安装真实解析模型。Swift 测试需要支持本项目的 Xcode 工具链。不要为了让测试通过直接重写快照，应先审阅每个结构变化。

在 [Issues](https://github.com/kvxunz/Thorn/issues) 反馈时附：macOS 版本、芯片、安装来源/提交号、触发快捷键、复现步骤、完整报错和必要截图。可附 `uv --version`、`ollama --version`、`ollama list`。先遮盖截图中的私人内容，勿上传密钥或整份个人日志。

语法树是阅读辅助，不是标准答案。部分修饰归属存在真实歧义，外部评测也有尚未解决的解析与标注差异。详见 [评测说明](ielts-corpus-evaluation.md)、[外部差异](external-review.md) 和 [独立盲标边界](blind-annotation.md)。

## 卸载

从菜单栏退出 Thorn，将 `/Applications/Thorn.app` 移到废纸篓即可移除应用。需要的话，在系统隐私设置中撤销权限。偏好和模型不随 App 自动删除，便于以后重装。

uv 缓存、Ollama 程序和模型可能被其他工具共享，不要为了卸载 Thorn 整体清除它们。确认没有其他用途后，再通过各自的管理工具按需删除指定模型或环境。
