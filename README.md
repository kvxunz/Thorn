# Thorn

一个常驻菜单栏的 macOS 小工具，帮英语学习者**读长难句**：选中一句英文，按一个热键，浮窗里立刻显示这句话的**句法教学树**（主干、从句、嵌套关系一层层展开）加上**整句中文翻译**。

拆句由本地 spaCy + Benepar 引擎完成，是确定性的规则解析，不经过大模型；翻译交给本地 Ollama 模型。全程在本机跑，句子和截图都不出这台 Mac。

> 面向个人精读场景的自用工具，不是打包分发的产品。下面的安装假设你愿意自己搭一套本地环境。

## 截图

<!-- 跑起来后 ⌥A 拆一句，把浮窗截图存成 docs/screenshot.png，再取消下一行注释 -->
<!-- ![Thorn 浮窗](docs/screenshot.png) -->

> 截图待补：`⌥A` 拆一句后截取浮窗，存到 `docs/screenshot.png` 并取消上面一行的注释即可。

## 它长什么样

选中英文 → `⌥A` → 浮窗出现：

- **顶部**是原句，鼠标悬停某个成分时对应文字高亮。
- **中间**是教学树。主干成分平铺在顶层，从句默认折叠成一块，点开才逐层展开——渐进披露，避免长句一上来糊你一脸。
- **底部**是整句中文翻译（结构先到，翻译随后补上）。

## 四条输入路径

| 热键 | 作用 |
| --- | --- |
| `⌥A` | 读取当前选中的英文（Accessibility 优先，失败时模拟 `⌘C` 兜底），拆句；**选中的是中文则换成英文再拆** |
| `⌥S` | 框选屏幕区域，用 Apple Vision 在本机 OCR 出文字再拆句（按 `Esc` 取消），中文同上 |
| `⌥X` | 弹出输入框，写一句中文，回车换成英文并拆句 |
| `⌥Z` | 重现上一次的结果 |

`Esc` 或点击浮窗外部关闭浮窗。双语材料（英文句夹中文注释）会自动只保留英文句子。

## 想说的话不知道怎么写？`⌥X`

前三条路径都是「看到英文 → 拆开看懂」，`⌥X` 是反过来的那条：**你先有中文，想知道英语里这句话是怎么搭起来的。**

按 `⌥X` 弹出输入框（这是唯一会短暂夺取键盘焦点的窗口——要打字），写中文，回车：

- 同一个 HY-MT2 反着跑一次，出英文；
- 英文立刻进句法引擎，浮窗给出教学树——不是只给你一句译文，而是给你这句英文的骨架；
- 底部那行中文是**你自己写的原话**，不是模型的回译。既省一次模型调用，也避免拿模型的改写冒充你的意思。
- 右上角的复制按钮把英文原句拿出去；`⌥Z` 重放时从你的中文重跑，不是从英文重跑。

模型若答非所问回了中文，会直接报错而不是把中文喂给英文解析器——那样只会得到一棵自信的、错的树。

**中文不用重打一遍**：`⌥A`/`⌥S` 抓到的内容如果找不出可拆的英文句子、而中文确实在，就自动走同一条路——等于「选中即 ⌥X」，浮窗仍开在鼠标旁（你刚在那儿选的），不是开在 `⌥X` 输入框的位置。其余语种照旧报错：日文靠假名一票否决（光看汉字分不出中日），韩、俄文同理——Thorn 帮不上，就不假装能帮。

## 选中的是单词？按自然拼读拆

选中内容只有一个英文单词时（允许 `don't`、`mother-in-law` 这类内部撇号/连字符），没有句法可拆，浮窗改为显示**自然拼读拆解**：

- 单词按「一块拼写 ↔ 一个音」切成色块，同音节同色，块下标注对应 IPA；
- 音节之间以 `·` 分隔，重音音节加粗并带 `ˈ`/`ˌ` 标记；
- 下方是整词 IPA 和本地 Ollama 给出的中文词义。

拆分来自打包进 App 的对齐词典（`Resources/phonics-en.tsv`，由 CMUdict 离线对齐生成，约 12.5 万词，见 `docs/phonics-dict.md`），查表纯本地、确定性、零延迟。词典未收录的词退回规则近似拆分，浮窗会标注「近似拆分」且不猜发音。

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
- `⌥X` 是唯一串行的一条：句法引擎要等 HY-MT2 先造出那句英文，才有东西可拆。
- sidecar 每次启动用**随机端口 + 一次性 token** 鉴权，空闲 10 分钟自动退出，下次请求再拉起。
- 返回的树要过一道**完整性校验**（span 严格递增不重叠、节点文本必须逐字等于对应 source token 拼接），过不了的树宁可报错也不显示。

## 环境要求

- macOS 14+
- [uv](https://docs.astral.sh/uv/)（运行 Python sidecar，依赖内联在脚本头部，自动装）
- [Ollama](https://ollama.com/) 且已拉取翻译模型：
  ```bash
  ollama pull hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K
  ```
- 构建 App 需要完整 Xcode（纯 CLT 不提供构建 SwiftUI 所需的完整 SDK/插件）；`scripts/bundle.sh` 会优先使用 `/Applications/Xcode.app`，也可用 `DEVELOPER_DIR` 指定位置

## 安装

1. **装句法模型**（一次性，会联网下载 spaCy transformer 权重和 Benepar，启动 App 不会自动下）：
   ```bash
   uv run --script sidecar/server.py --install-models
   ```

2. **构建并安装 App**：
   ```bash
   ./scripts/bundle.sh
   # 先退出正在运行的 Thorn；明确替换同一个 .app 目标，避免复制进旧 bundle
   sudo rm -rf /Applications/Thorn.app
   sudo ditto --rsrc --extattr --acl build/Thorn.app /Applications/Thorn.app
   open /Applications/Thorn.app
   ```
   `ditto` 的目标固定为 `/Applications/Thorn.app`，重复执行会得到同一个干净 bundle。`bundle.sh` 默认使用仓库开发证书哈希；若要保留你自己的 TCC 授权，请通过 `THORN_CODESIGN_IDENTITY` 传入钥匙串中的签名身份。

3. **授权**：
   - `⌥A` 需要「辅助功能」权限
   - `⌥S` 需要「屏幕录制」权限（首次会弹窗）
   - `⌥X` 不需要额外权限：它不读取任何东西，只接受你在自己的输入框里打的字

4. 菜单栏图标 → 「设置…」里选一个已安装的 Ollama 翻译模型。

> 安装后的 App 会使用包内自带的 sidecar，不再依赖仓库路径。开发时如需改用另一份脚本，可覆盖：
> ```bash
> defaults write com.xvz.thorn sidecarScript /你的路径/sidecar/server.py
> ```

## 隐私

- 解析和翻译请求只访问本机 `127.0.0.1` 的 sidecar 和 Ollama；首次运行 `uv run --script` 可能联网安装脚本声明的 Python 依赖，`--install-models` 也会联网下载句法权重。
- `⌥S` 的截图写到创建时设为权限 `0700` 的临时目录中的单次 PNG，读入内存后立即删除，不经过全局剪贴板。
- 诊断日志默认关闭；开启后（`defaults write com.xvz.thorn debugLog -bool true`）写到 Application Support、权限 `0600`、不记录捕获的文本。

## 项目结构

```
Sources/Thorn/          Swift 菜单栏 App（热键、浮窗、sidecar 客户端、OCR、翻译、拼读）
sidecar/                Python 句法引擎（spaCy + Benepar），FastAPI 服务
Resources/phonics-en.tsv 单词拼读对齐词典（离线生成，随 App 打包）
Tests/ThornTests/       Swift 单测
scripts/bundle.sh       构建 + 签名 + 组装 .app
scripts/githooks/       提交前的快照闸（git config core.hooksPath scripts/githooks）
scripts/build_phonics_dict.py 拼读词典离线生成器（CMUdict + EM 对齐）
docs/parsing-issues.md  句法拆解的已知问题与回归样本
docs/phonics-dict.md    拼读词典的数据格式与生成说明
.learnings/LEARNINGS.md 踩坑档案：症状 → 根因 → 解法 → 诊断手法
```

## 一点设计立场

这个项目走过一段弯路：早期让 LLM 直接生成句法结构，反复被小模型「不服从 schema + 破坏结构不变量」坑。最终的结论写在 `.learnings/LEARNINGS.md` 里——**结构交给确定性解析器，翻译交给 LLM，两者别混**。想了解为什么代码是现在这个样子，那个文件比读代码快。

## License

[MIT](LICENSE)
