# Thorn

一个常驻菜单栏的 macOS 小工具，帮英语学习者**读长难句**：选中一句英文，按一个热键，浮窗里立刻显示这句话的**句法教学树**（主干、从句、嵌套关系一层层展开）加上**整句中文翻译**。

拆句由本地 spaCy + Benepar 引擎完成，是确定性的规则解析，不经过大模型；翻译交给本地 Ollama 模型。全程在本机跑，句子和截图都不出这台 Mac。

> 面向个人精读场景的自用工具，不是打包分发的产品。下面的安装假设你愿意自己搭一套本地环境。

## 它长什么样

选中英文 → `⌥A` → 浮窗出现：

- **顶部**是原句，鼠标悬停某个成分时对应文字高亮。
- **中间**是教学树。主干成分平铺在顶层，从句默认折叠成一块，点开才逐层展开——渐进披露，避免长句一上来糊你一脸。
- **底部**是整句中文翻译（结构先到，翻译随后补上）。

## 三条输入路径

| 热键 | 作用 |
| --- | --- |
| `⌥A` | 读取当前选中的英文（Accessibility 优先，失败时模拟 `⌘C` 兜底），拆句 |
| `⌥S` | 框选屏幕区域，用 Apple Vision 在本机 OCR 出文字再拆句（按 `Esc` 取消） |
| `⌥Z` | 重现上一次的结果 |

`Esc` 或点击浮窗外部关闭浮窗。双语材料（英文句夹中文注释）会自动只保留英文句子。

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
- sidecar 每次启动用**随机端口 + 一次性 token** 鉴权，空闲 15 分钟自动退出，下次请求再拉起。
- 返回的树要过一道**完整性校验**（span 严格递增不重叠、节点文本必须逐字等于对应 source token 拼接），过不了的树宁可报错也不显示。

## 环境要求

- macOS 14+
- [uv](https://docs.astral.sh/uv/)（运行 Python sidecar，依赖内联在脚本头部，自动装）
- [Ollama](https://ollama.com/) 且已拉取翻译模型：
  ```bash
  ollama pull hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K
  ```
- 构建 App 需要完整 Xcode（CLT 缺 SwiftUI 宏插件，`swift build` 会报 `StateMacro could not be found`）

## 安装

1. **装句法模型**（一次性，会联网下载 spaCy transformer 权重和 Benepar，启动 App 不会自动下）：
   ```bash
   uv run --script sidecar/server.py --install-models
   ```

2. **构建并安装 App**：
   ```bash
   ./scripts/bundle.sh
   cp -r build/Thorn.app /Applications/
   open /Applications/Thorn.app
   ```
   `bundle.sh` 里用固定的开发者证书哈希签名（让 TCC 授权在重复构建间存活）——换成你自己钥匙串里的证书。

3. **授权**：
   - `⌥A` 需要「辅助功能」权限
   - `⌥S` 需要「屏幕录制」权限（首次会弹窗）

4. 菜单栏图标 → 「设置…」里选一个已安装的 Ollama 翻译模型。

> sidecar 脚本路径默认写死在 `~/xznm/code/Thorn/sidecar/server.py`。仓库不在这个位置就改：
> ```bash
> defaults write com.xvz.thorn sidecarScript /你的路径/sidecar/server.py
> ```

## 隐私

- 运行时除了访问本机 `127.0.0.1` 的 sidecar 和 Ollama，不联网（只有装模型那一步下载权重）。
- `⌥S` 的截图写到 `0700` 临时文件、读完立即删除，不经过全局剪贴板。
- 诊断日志默认关闭；开启后（`defaults write com.xvz.thorn debugLog -bool true`）写到 Application Support、权限 `0600`、不记录捕获的文本。

## 项目结构

```
Sources/Thorn/          Swift 菜单栏 App（热键、浮窗、sidecar 客户端、OCR、翻译）
sidecar/                Python 句法引擎（spaCy + Benepar），FastAPI 服务
Tests/ThornTests/       Swift 单测
scripts/bundle.sh       构建 + 签名 + 组装 .app
docs/parsing-issues.md  句法拆解的已知问题与回归样本
.learnings/LEARNINGS.md 踩坑档案：症状 → 根因 → 解法 → 诊断手法
```

## 一点设计立场

这个项目走过一段弯路：早期让 LLM 直接生成句法结构，反复被小模型「不服从 schema + 破坏结构不变量」坑。最终的结论写在 `.learnings/LEARNINGS.md` 里——**结构交给确定性解析器，翻译交给 LLM，两者别混**。想了解为什么代码是现在这个样子，那个文件比读代码快。
