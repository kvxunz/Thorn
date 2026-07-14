# Learnings — Thorn

## 2026-07-13 首次可用版本调试

1. **CLT 工具链缺 SwiftUI 宏插件**：`swift build` 报 `StateMacro could not be found`。修复：`DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift build`（已固化进 scripts/bundle.sh）。

2. **codesign 同名证书歧义会静默毁掉 TCC**：钥匙串有两个 "DocR Dev"，`codesign --sign "DocR Dev"` 报 ambiguous，app 退回 ad-hoc linker-signed，每次构建 cdhash 变化导致辅助功能授权反复失效。修复：用证书 SHA-1 哈希签名 + 脚本里 `codesign --verify` 强制校验。

3. **TCC 陈旧记录**：换签名后设置里开关切换无效（旧记录绑旧签名），且存在重复记录。修复：`tccutil reset Accessibility com.xvz.thorn` 清掉后重新授权。

4. **NSHostingView 内容居中裁剪症状**：浮窗只显示中间几行、头尾不见 = window frame 小于 SwiftUI 内容尺寸，SwiftUI 居中放置导致上下均匀裁掉。修复：放弃 GeometryReader preference 上报，改为 Combine 监听状态变化后 `contentView.fittingSize` + `setFrame`。

5. **UserDefaults 残留状态坑**：用户在设置里切到未配置的"自定义端点"，之后所有请求发向空 URL 报"unsupported URL"。修复：端点未配置时抛明确错误。

6. **提示词粒度需双向约束**：只说"别切碎"会过度合并（整个主句一块）。有效写法：主干成分各自成块 + clause-* 仅限含主谓的真从句 + 禁纯标点块 + 给一个完整 few-shot 例子。

## 2026-07-13 Readest（Tauri）取词排查

7. **Tauri 应用复制是"清空→写入"两步**，剪贴板 changeCount +2。轮询 changeCount 逮到第一步读到空串。修复：检测到变化后再等 150ms 读。诊断手法：独立 swift 脚本注入 ⌘C 并打印 changeCount 前后值，+2 即实锤两步写。

8. **模拟 ⌘C 前必须等修饰键物理松开**：热键 ⌥D 触发时 ⌥ 还按着，合成事件叠加成 ⌘⌥C 被应用忽略。轮询 `CGEventSource.flagsState(.hidSystemState)` 直到干净。

9. **web 内核应用选中文本不在 AX 焦点元素上**：挂在 AXWebArea 后代；Readest 的 epub iframe 甚至完全不暴露选区（AX 树里无 AXSelectedText），只能走剪贴板兜底。已加 AX 树深度遍历（depth 12，每层限 40 子节点）作中间层。

10. **诊断脚本可从有辅助功能权限的宿主进程直接跑**：`swift /tmp/xxx.swift` 继承宿主 TCC 信任（AXIsProcessTrusted=true），可注入按键、扫 AX 树，比在 app 里加日志迭代快得多。

## 2026-07-14 Sub2API 云端接入

11. **Sub2API（Wei-Shaw/sub2api）是 Responses 协议网关**：Codex 订阅转 API。老版本（v0.1.103）非流式 `/v1/responses` 有 bug：status=completed、output_tokens 有计数但 `output` 数组为空（流式聚合丢内容）。升级到 v0.1.15x 修复。诊断关键：usage 有 token 计数但 output 空 = 网关聚合 bug，不是模型问题。

12. **"模型返回为空"类错误要先 dump 原始响应体**：在解析失败分支记录 raw body（截断 6000 字符），一轮就定位；别猜格式。

14. **结构不变量靠代码修复，不靠提示词堆规则**：给 30B 模型加"父块文本=子块拼接"规则后，它反而开始过度拆解（a+decision）且不变量照破。解法：提示词只描述理想输出，代码里加 repair 层（越界子块提升为兄弟、无从句的琐碎展开剪除、修不好的树宁可丢弃）。规则数量与小模型服从率成反比。

15. **无边框 NSPanel 缩放裁切类 bug 的统一根因**：窗口被允许缩到比 SwiftUI 内容最小布局还小 → 内容溢出被窗口矩形硬裁（圆角变直角、文字切半）。clipShape 治不了。正解：`windowWillResize` 回调里用 `NSHostingController.sizeThatFits(in: CGSize(width: W, height: 1))` 实时钳制下限；且**布局里每个文字都必须 fixedSize(vertical) 声明刚体**——任何一个可压缩 Text 都会让 sizeThatFits 谎报最小值。内容异步长大后还要再 enforce 一次。

16. **SwiftUI frame(maxHeight:) 是"贪婪上限"不是"内容封顶"**：VStack 会把可用空间给到 maxHeight 满格，短内容下面全是空气。想按内容封顶用 lineLimit（文本）或精确 ideal。

17. **本地 LLM 批量结构化输出要用键值对不用平行数组**：让 qwen 按序输出 N 条 glosses 数组，N>15 时计数必错整包报废。改成 `{"n":3,"g":"…"}` 键值对 + 宽容对齐（对上多少用多少），成功率质变。

13. **few-shot 例句不能和真实输入太像**：例句与输入几乎相同时，模型直接照抄例句文本，把输入里例句没有的词（extremely）吞掉。例句要结构同构、措辞完全无关，并显式加"chunk text 必须逐字来自输入句"规则。验证手段：拼接所有 chunk text 与原句做覆盖对比。
