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

## 2026-07-16 对齐层"分开翻译不行"排查

18. **对齐 bug 的正确诊断路径：拿全新句子过 live 管线，别只跑单测**。34 个纯单测全绿，但 4 句全新句里 1 句严重失灵（subject 释义成"他们拒绝发表这份报告"、两个子块全空）。写探针脚本直连 /parse+/gloss，再写离线脚本 dump 真实 SimAlign pair + 各 sibling 的锚点集，两轮就把根因钉死——比读 1900 行启发式代码快得多。

19. **零权重对齐对（标点→标点）会毒化 sibling 预留集**：`target_scores_for` 曾把 score=0.0 的锚点也存进 dict，源逗号对齐到目标逗号后，该逗号成为其他 sibling 的 cluster barrier，把 complement 的簇从"发表这份报告，直到…"切剩"直到…"，下游子块全空。修复：source_weight≤0 直接跳过。教训：**"存在于 dict"本身就是信号**，即使值为 0——凡是拿 keys 当集合用的下游逻辑都会被零值条目影响。

20. **head-final 启发式必须让位给对齐证据**：中文把英语后置定语从句译成前置"…的"时 head 才后移；但复指译法（"该委员会的成员…，他们拒绝…"）head 留在原位。修复：defer 前比较 head 自身锚点在预留区间前/后的最强分数，best_before > best_after 就不 defer。通用原则：结构启发式和对齐证据冲突时，信证据。

21. **验证被环境卡死时换 import 路径**：权限分类器宕机无法重启 sidecar，但 /parse（未改）可用 + 本地跑 SimAlign + 直接 import 仓库新 alignment.py，照样完成端到端验证。服务进程 stale ≠ 无法验证新代码。

## 2026-07-16 释义分配层整体移除

22. **过拟合层的最优解可能是删除而非重构**：1904 行对齐启发式里 ~600 行是句子指纹修补。用户裁决：本地管线只要"精准拆分 + 整句翻译"，释义分配整层删除。alignment.py 1904→92 行（只留 /parse 的 span 标注），Swift 消费端 ~300 行同步清除。教训：先问"这个子系统的产出值不值它的复杂度"，再问"怎么修"。

23. **左缘引导词剥离的误杀判据是"邻接性"**：is_left_edge_introducer 防 spaCy 把上层 when/if 误挂到下层 xcomp/pcomp，但把真属于 pcomp 宾语从句的 whether/how 也剥掉了（子块里凭空消失）。区分特征：误挂的引导词与剩余子树之间隔着上层从句词（索引有空隙），真引导词紧邻子树首 token。按邻接回补即两全。

24. **pcomp 是被遗忘的从句类型**：contains_clause/np_expand 只认 relcl/acl/advcl/ccomp/csubj，介词的从句补语（"in how well…"、"for why…"）一直没展开。加 is_clausal_pcomp（pcomp+动词性+自带主语）门控后连带修好 "explanation for why…" 类结构；无主语动名词（"in doing so"）保持平铺不误伤。

25. **双语材料复制的英文句常混全角标点，spaCy 英文模型直接挂错依存**："troubles，or so" 里 cc 被吞进介词短语、"or so" 惯用语拆散。修在唯一入口 ParseService.normalizedInput：全角，。、；：？！（）和全角空格转 ASCII；弯引号 ' " 是正常英文排版必须保留。header 文本由 chunk 拼接（ChunkSpanResolver），入口规范化后高亮天然不错位。

26. **修补规则会毁掉本来正确的解析——删规则前先 dump 依存树定罪**：Coincident 倒装句 spaCy 解析全对（appreciation=nsubj、to 挂 importance），拆烂它的是给 BMW 列表句写的 split_false_list_appos_subject 正则（主语含逗号+后跟 the 就硬劈）。诊断路径：怀疑拆分错 → 先 dump spaCy 依存（uv 脚本 10 行）→ 树对则罪在 chunker 后处理规则，树错才是模型问题。本日第三条被处决的指纹规则。

27. **倒装句 spaCy 会把前置成分挂在助动词上，chunk_roots 只收主动词孩子就会产孤儿**："Nor, if…, is management to be blamed" 的 Nor(cc) 和 if-advcl 全挂在 aux 'is' 上，孤儿 token 被就近吞并成巨型连词块。修法（通用非指纹）：谓语组是一个谓词整体，收割 verb_group 每个成员的孩子。ca358c9。

## 2026-07-18 候选选择式融合与 MLX schema 假约束

33. **"模型不服从 schema" 先查运行时是否真的下发了约束**：qwen3.5:4b-mlx 发明键名、范围重叠、残缺 JSON，全被归咎于 4B 能力不足——实际是 Ollama MLX runner 静默忽略 `format`（issues #16563/#17013/#17183，同模型 GGUF 版正常强制），grammar 从头到尾没生效。连带发现 `think:false + format` 失效 bug（#14645）已在 0.31.2/0.32.0 修复（根因：grammar 掩码等 end-of-thinking token，think:false 模板塞空 think 段导致掩码永不激活）。教训：结构化输出崩坏时，最小实验（同 prompt 分别打 GGUF 与 MLX tag）一轮即可分清运行时问题与模型问题，别急着换模型或加提示词。所有被污染时期采的失败数据作废。

32. **几何不变量该"按构造成立"而不是"生成后校验"**：让 LLM 自由输出递归 s/e 范围，同级连续分割这类跨节点算术约束 JSON Schema 表达不了，只能事后整树拒收——错误代价被放大到最大。改为程序从 Benepar 成分 + token 枚举候选树（span/嵌套固定），LLM 只输出 {id, 教学功能, 释义} 扁平选择列表，Swift 按候选树组装：未选缺口用最大候选以 .other 填充、纯标点段吸附邻块。此后模型任何错误都降级为单节点确定性修复（丢弃/降级/清空），死树只剩"零有效 pick"一种。候选枚举是机械规则（无词形触发），不算重新引入指纹补丁。设计稿 docs/candidate-selection-design.md；由 Codex 按稿实现、Claude 审核，跨 agent 交接的关键是设计稿必须自包含（含磁盘现状、禁区、逐条测试要求）。

## 2026-07-17 云端删除后的混排输入塌方

31. **结构切对了还会在展示层翻车：新的多块拆分必须默认收拢**：分号列举拆成六个插入语项是对的，但拍平到顶层后主干淹没在 17 行里，用户直接开骂。本 app 的展示哲学是渐进披露（从句默认折叠、并列分句收大块）——任何让顶层行数膨胀的新拆分规则，都要包成单块 + children，点开再看。同一课用户教了两次（并列分句一次、列举一次），第三次之前先自查。2a58d6e。

30. **conj 兜底规则"动词的非动词并列项=宾语"会吞掉独立主格**："…returned to Ireland…, my sister, Margaret, dead and gone" 里 spaCy 正确给出 dead=conj(returned)+brother=nsubj(dead)（无动词并列分句），但 chunk 规则的 conj 分支按"head 是动词"一刀切标宾语，26 个 token 成了不及物动词的"宾语"。判据（通用）：非动词 conj 自带 nsubj = 省略 be 的独立主格，新增 "absolute" 角色并按动词头展开（形容词头照走 build_chunks，verb run 即省略的表语）。Swift 未知角色降级 .other，协议前向安全。2114593。

29. **不连续的 conj 成分会被"按连续段拼接"逻辑整体复制**："where they met and married and where I was born" 里 spaCy 把 where(10) 挂到 married(14)，married 子树 {10,14} 被中间 token 切成两段，build_chunks 每段 flush 都触发一次 __coord_clause__ 整体内联 → married 从句拼两次、span 乱序、Swift 校验拒收整树（症状=同一句永远"引擎暂不可用"，而引擎明明是热的）。修法：左缘引导词剥离白名单加 "conj"，且 chunk_roots 的 token 归属和 build_chunks 的子树用同一个 constituent_token_indices 算——两处口径一致才杜绝复制。邻接判据（#23）继续兜住真引导词。诊断路径照旧：探针脚本 dump 依存树+chunk 树，一轮定罪。sidecar/probe_sentence.py 已留作常备工具。

28. **纯英文句法引擎的输入门槛必须按"段"过滤，不能只看全局字母占比**：双语注释材料（"close to 是靠近的意思。15．Economists…"）ASCII 字母占比 85% 轻松过 0.5 门槛，但 spaCy 英文模型吃到汉字后整树报废（economies 成谓语、中文片段全成插入语）。云端 LLM 在时这种输入被它兜住，砍云端后裸奔。修法：按句末标点切段，含 CJK 的段整段丢弃（词汇注释必含中文）、不足三词的碎片丢弃（编号/习语残片），剩余英文句照常拆。全角句点 ．（编号 "15．" 专用）要进规范化表，否则粘连进主语块。6c7045d。

## 2026-07-30 ⌥S 框选 OCR 静默失效排查

34. **`screencapture` 拒绝 `/dev/fd/1` 与 `/dev/stdout` 目标，且失败时 exit 0 + 0 字节**："把 PNG 通过匿名管道直接进内存、不落盘"的设计（`screencapture -i -x -tpng /dev/fd/1` + Pipe）在本机（Darwin 27）根本不成立：screencapture 需要可 seek 的普通文件，对 `/dev/fd/*`、`/dev/stdout` 一律 stderr 报 `cannot write file to intended destination` 并**以退出码 0 返回 0 字节**。代码 `guard terminationStatus == 0, !data.isEmpty else { return nil }` 把这个「成功退出但空输出」判成用户取消，于是每次截图都静默无反应、无日志。修法：写 0700 临时 PNG、读完即 `unlink`（隐私目标退而求其次，像素只在磁盘存在一瞬）。诊断关键：在普通 shell 里原样跑一遍 screencapture 命令看 exit code+字节数+stderr，一次就证伪管道方案——别信「exit 0 == 成功」。

35. **"按了没反应、debugLog 开着却零日志" = 命中了 handler 的静默 return 分支**：`handleOCRHotkey` 只在 OCR 成功后才打日志，失败/取消路径直接 return，而 `⌥A` 的 handler 有入口日志。对照之下「⌥A 有日志、⌥S 全无」就锁定问题在 OCR 入口到成功之间的静默 return，而非热键没注册（再用 `nm` 确认二进制里有 `handleOCRHotkey` 符号排除「代码没编进去」）。教训：每个用户可触发的入口都要有一行入口日志；且**捕获失败必须和主动取消区分**（stderr 有内容=真失败要弹错，stderr 空=Esc 取消才静默），否则一切失败都伪装成"用户取消"。

36. **改完装不上的坑：`open` 不会重启已在运行的 app，`cp` 覆盖不了正在执行的可执行文件**：`bundle.sh && cp -r build/Thorn.app /Applications/ && open …` 看似成功，但旧进程还在跑时 `cp` 覆盖 Mach-O 会 Text file busy（且 `cp -r dir /Applications/` 在目标已存在时是嵌套拷贝而非覆盖），`open` 又只是把旧进程调到前台——结果跑的还是旧二进制。判据：`stat` 已装二进制的 mtime + `strings` 找新符号 + `ps -o lstart` 看进程启动时间，三者对不上就是没装上。修法：先 `osascript -e 'quit app'`/`pkill -x`，再 `rm -rf` 旧 app、`cp -R` 新的、`codesign --verify`，最后 `open`。
