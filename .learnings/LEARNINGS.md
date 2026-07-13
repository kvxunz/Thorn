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
