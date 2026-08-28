<div align="center">

# Thorn

**读英文长难句的 macOS 菜单栏工具**

选中一句英文，按一个键，浮窗里出现这句话的句法教学树和整句中文翻译。<br>
结构由确定性解析器给出，翻译由本地模型给出——两者不混。

<img src="https://img.shields.io/badge/macOS-14%2B-2b2724?style=flat-square" alt="macOS 14+">
<img src="https://img.shields.io/badge/Apple_Silicon-only-2b2724?style=flat-square" alt="Apple Silicon">
<img src="https://img.shields.io/badge/离线-不联网推理-3d5a48?style=flat-square" alt="离线">
<img src="https://img.shields.io/badge/license-MIT-5a4a3d?style=flat-square" alt="MIT">

</div>

---

## 它给你什么

选中一句真正难读的话，按 `⌥A`：

> It’s all deliciously ironic when you consider that Shakespeare, who earns their living, was himself an actor (with a beard) and did his share of noise-making.

```
It's                                            主语+谓语
all                    状语   程度副词“完全”，不是“全部”
deliciously ironic                                  补语
when you consider that…                    状语从句   状语
├── when                                          连接成分
├── you                                              主语
├── consider                                         谓语
└── that Shakespeare, who earns…                 名词性从句
    ├── that          连接成分   引导宾语从句，本身不译
    ├── Shakespeare, who earns their living   ▸     主语
    ├── was                                          谓语
    ├── himself       状语   强调“本人、亲自”，不是宾语
    ├── an actor                                     补语
    ├── (with a beard)                             插入语
    ├── and                                       连接成分
    ├── did                                          谓语
    └── his share of noise-making                    宾语
```

主干成分平铺在顶层，从句默认折叠成一块，点开才逐层展开——渐进披露，长句不会一上来糊你一脸。鼠标悬停某个成分，顶部原句里对应的文字跟着高亮。底部是整句中文翻译。

关键处会自己开口说话：`all` 在这儿是程度副词「完全」而不是「全部」，`himself` 是强调不是宾语——这类最容易读错的地方，树会直接告诉你。

<!-- 想放真实截图：⌥A 拆一句，把浮窗截图存成 docs/screenshot.png，取消下一行注释 -->
<!-- <div align="center"><img src="docs/screenshot.png" width="620" alt="Thorn 浮窗"></div> -->

## 四条输入路径

| 热键 | 作用 |
| :-- | :-- |
| `⌥A` | 拆解**选中的英文**（Accessibility 优先，失败时模拟 `⌘C` 兜底） |
| `⌥S` | 框选屏幕任意区域，本机 Vision OCR 出文字再拆（`Esc` 取消） |
| `⌥X` | 弹出输入框，**写中文换英文**，再拆给你看 |
| `⌥Z` | 重现上一次结果 |

`Esc` 或点击浮窗外部关闭。双语材料（英文句夹中文注释）会自动只留英文句子。

**`⌥A` 和 `⌥S` 抓到的是中文？** 不报错，直接走 `⌥X` 那条路——等于「选中即 ⌥X」，浮窗仍开在鼠标旁，因为你刚在那儿选的。其余语种照旧报错：日文靠假名一票否决（光看汉字分不出中日），韩、俄同理。帮不上就不假装能帮。

<details>
<summary><b>⌥X：反过来的那条路——你先有中文，想知道英语怎么搭</b></summary>

<br>

前三条都是「看到英文 → 拆开看懂」，`⌥X` 是反向的。按键弹出输入框（这是唯一会短暂夺取键盘焦点的窗口，因为要打字），写中文，回车：

- 同一个 HY-MT2 反着跑一次，出英文；
- 英文立刻进句法引擎，浮窗给出教学树——不是只给你一句译文，是给你这句英文的骨架；
- 底部那行中文是**你自己写的原话**，不是模型的回译。既省一次模型调用，也避免拿模型的改写冒充你的意思；
- 右上角复制按钮把英文拿出去；`⌥Z` 重放时从你的中文重跑，不是从英文重跑。

模型若答非所问回了中文，直接报错，不会把中文喂给英文解析器——那样只会得到一棵自信的、错的树。

</details>

<details>
<summary><b>选中的是单词？改按自然拼读拆</b></summary>

<br>

选中内容只有一个英文单词时（允许 `don't`、`mother-in-law` 这类内部撇号/连字符），没有句法可拆，浮窗改为显示自然拼读拆解：

- 单词按「一块拼写 ↔ 一个音」切成色块，同音节同色，块下标注对应 IPA；
- 音节之间以 `·` 分隔，重音音节加粗并带 `ˈ`/`ˌ` 标记；
- 下方是整词 IPA 和本地模型给出的中文词义。

拆分来自打包进 App 的对齐词典（`Resources/phonics-en.tsv`，CMUdict 离线对齐生成，约 12.5 万词，见 [docs/phonics-dict.md](docs/phonics-dict.md)），查表纯本地、确定性、零延迟。词典未收录的词退回规则近似拆分，浮窗会标注「近似拆分」且不猜发音。

</details>

## 工作原理

```
Swift 菜单栏 App                       Python sidecar (uv run --script)
────────────────                      ─────────────────────────────────
热键捕获 → 归一化 / 抽英文
   │
   ├─ HTTP /parse ───────────────────→ spaCy(en_core_web_trf) + Benepar
   │   ← 教学 chunk 树 + source tokens     确定性规则拆句，无 LLM
   │
   └─ Ollama /chat ──────────────────→ 本地 HY-MT2 模型
       ← 整句中文翻译                       (默认 Hy-MT2-7B-GGUF:Q6_K)
```

- 解析与翻译**并发**跑，结构树先渲染，翻译落地后再填，谁也不等谁。
- `⌥X` 是唯一串行的一条：句法引擎要等模型先造出那句英文，才有东西可拆。
- sidecar 每次启动用**随机端口 + 一次性 token** 鉴权，空闲 10 分钟自动退出，下次请求再拉起。
- 返回的树要过一道**完整性校验**：span 严格递增不重叠、节点文本必须逐字等于对应 source token 的拼接。过不了的树宁可报错也不显示。

## 装给自己

> [!NOTE]
> 需要 macOS 14+、Apple 芯片、完整 Xcode（纯 CLT 缺构建 SwiftUI 所需的 SDK/插件），
> 以及 [uv](https://docs.astral.sh/uv/) 和 [Ollama](https://ollama.com/)。

```bash
# 1. 句法模型（一次性，联网下载 spaCy transformer 权重和 Benepar）
uv run --script sidecar/server.py --install-models

# 2. 翻译模型
ollama pull hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K

# 3. 构建并安装（先退出正在运行的 Thorn）
./scripts/bundle.sh
rm -rf /Applications/Thorn.app
ditto --rsrc --extattr --acl build/Thorn.app /Applications/Thorn.app
open /Applications/Thorn.app
```

`ditto` 的目标固定为 `/Applications/Thorn.app`，重复执行得到同一个干净 bundle。`bundle.sh` 默认使用仓库开发证书哈希；要保留自己的 TCC 授权，用 `THORN_CODESIGN_IDENTITY` 传入钥匙串里的签名身份。

**授权**：`⌥A` 需要「辅助功能」，`⌥S` 需要「屏幕录制」（首次弹窗）。`⌥X` 不需要任何权限——它不读取任何东西，只接受你在自己输入框里打的字。

最后到菜单栏图标 → 「设置…」里选一个已安装的 Ollama 翻译模型。

> 安装后的 App 使用包内自带的 sidecar，不再依赖仓库路径。开发时如需改用另一份脚本：
> ```bash
> defaults write com.xvz.thorn sidecarScript /你的路径/sidecar/server.py
> ```

## 装给别人

```bash
./scripts/dmg.sh   # -> build/Thorn-<版本>.dmg
```

镜像里是 `Thorn.app`、指向 `/Applications` 的软链、`先读我.txt` 和 `安装助手.command`。

> [!IMPORTANT]
> 镜像不到 3 MB，但这个 App 跑起来还需要约 **7.7 GB**：Python 环境和英文句法权重（约 1.5 GB）、
> Benepar/NLTK 数据（323 MB）、Ollama 翻译模型（6.2 GB）。这些既装不进 bundle 也不该装进去。

`安装助手.command` 在对方机器上补齐这一切：检查机型和系统、按需装 uv 与 Ollama、跑 `--install-models`、拉翻译模型。每步都会跳过已满足的部分，中断后重跑即可。

两处必须对方自己点，脚本里写清楚了：

- **Gatekeeper。** 签名是自签证书，没有 Developer ID、没走 Apple 公证，首次打开会显示「无法验证开发者」。安装助手会**询问**是否移除隔离标记；拒绝也能装，手动去 系统设置 → 隐私与安全性 → 仍要打开。想双击即开，只有 $99/年 的 Developer ID + 公证一条路。
- **辅助功能授权。** 不给权限 `⌥A` 取不到选区，这一步无法脚本化。

## 隐私

- 解析和翻译只访问本机 `127.0.0.1` 的 sidecar 和 Ollama。联网只发生在装环境的时候：首次 `uv run --script` 装 Python 依赖，`--install-models` 下句法权重，`ollama pull` 拉模型。
- `⌥S` 的截图写到权限 `0700` 的临时目录，读入内存后立即删除，不经过全局剪贴板。
- 诊断日志默认关闭；开启后（`defaults write com.xvz.thorn debugLog -bool true`）写到 Application Support，权限 `0600`，不记录捕获的文本。

## 项目结构

```
Sources/Thorn/                  Swift 菜单栏 App（热键、浮窗、sidecar 客户端、OCR、翻译、拼读）
sidecar/                        Python 句法引擎（spaCy + Benepar），FastAPI 服务
Resources/phonics-en.tsv        单词拼读对齐词典（离线生成，随 App 打包）
Tests/ThornTests/               Swift 单测
scripts/bundle.sh               构建 + 签名 + 组装 .app
scripts/dmg.sh                  打包成可分发的 DMG
scripts/setup.command           收件人那侧的一键环境安装
scripts/githooks/               提交前的快照闸（git config core.hooksPath scripts/githooks）
scripts/build_phonics_dict.py   拼读词典离线生成器（CMUdict + EM 对齐）
scripts/makeicon.swift          Resources/AppIcon.icns 的唯一生成源（见文件首行的两条命令）
docs/parsing-issues.md          句法拆解的已知问题与回归样本
docs/phonics-dict.md            拼读词典的数据格式与生成说明
.learnings/LEARNINGS.md         踩坑档案：症状 → 根因 → 解法 → 诊断手法
```

## 一点设计立场

这个项目走过一段弯路：早期让 LLM 直接生成句法结构，反复被小模型「不服从 schema + 破坏结构不变量」坑。最终结论写在 [`.learnings/LEARNINGS.md`](.learnings/LEARNINGS.md) 里——**结构交给确定性解析器，翻译交给 LLM，两者别混**。想知道为什么代码是现在这个样子，那个文件比读代码快。

同一条立场的一个小例子：曾经有人在归一化那里留了句注释，说弯引号是正常的英文排版、应当原样保留。这话对文本成立，对解析器不成立——同一句话里 `It’s` 的 `’` 会让 spaCy 把 `all` 标成兜底词性，卡片就退化成「其他」；换成 ASCII 撇号，它立刻变回「状语」，连带那条「程度副词『完全』」的注解也才有地方挂。网页和电子书里复制出来的每一句都带弯引号，所以那是常见路径在悄悄退化，不是边角情况。

## License

[MIT](LICENSE)
