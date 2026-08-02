# 句法拆解问题清单

只记录会影响主干、从句归属或嵌套关系的问题。词性、措辞和细粒度标签不进入待修范围。

下面每条的「回归判据」都有一条对应的可执行测试，跑真 spaCy + Benepar：

```bash
uv run --script sidecar/golden_parse_checks.py    # 直接跑：每次约 95 秒，全花在加载模型上
```

该套件不叫 `test_*.py`，因此不会被 `python -m unittest discover -s sidecar` 收走——快测保持零依赖、毫秒级。改动拆句规则后必须跑一次：判据只有能执行才拦得住回归（见 LEARNINGS #42）。

### 用常驻进程跑（推荐）

模型加载约 70 秒且每次 `uv run --script` 都要重付一遍，改一条规则要等好几分钟才知道有没有用。`devrunner.py` 把模型常驻在一个 worker 里，脚本变成客户端：

```bash
# 起一次，之后一直用
tmux new-session -d -s thorn-dev -c sidecar 'uv run --script devrunner.py --serve'

cd sidecar
python3 devrunner.py golden_parse_checks.py            # 95s -> 1.5s
python3 devrunner.py corpus_report.py --constructions  # 150s -> 20s
python3 devrunner.py /tmp/probe.py                     # 一次性探针也走这条路
```

客户端是纯标准库、跑在裸 `python3` 上，不经过 `uv`，否则每次调用又要解一遍环境。

worker **每个 job 都把 sidecar 目录下的模块从 `sys.modules` 里清掉**，让脚本重新从磁盘 import——所以它永远跑的是当前工作区的代码，不会拿一小时前加载的旧规则报绿。唯一常驻的是 `nlp`。这一点是这个设计必须守住的：一个测的是旧代码的绿色套件，比一个慢套件危险得多。

### 快照：唯一看得见「切太碎」的东西

`undersplit.py` 只报**粗卡**——切得不够。没有任何指标报切得太碎，而拆分规则的改动是在这两种失败之间做交易：列表被打散成一串「插入语」、卡片停在孤立介词上、日期在逗号处被切开——这六个缺陷当初**全部**是以「粗卡率下降」的形式出现的。指标说赢了，树其实坏了。

`tree_snapshot.py` 把两个语料库每一句的整棵树冻在 `sidecar/snapshots/` 下：

```bash
cd sidecar
python3 devrunner.py tree_snapshot.py           # 比对，有漂移退出 1
python3 devrunner.py tree_snapshot.py --write   # 逐行看过之后再接受
```

它**不断言树该长什么样**，只断言树没有在没人过目的情况下变过。这里出现 diff 不是失败，是一次待审。改 `chunk_roots` 或 `np_expand` 拆分链之后，先跑它，把每一行读一遍——确认每处改动都是改进，再 `--write` 接受，并把快照和代码放进同一个 commit。

两个语料库地位不同。`constructions` 随代码一起进仓库，所以快照缺失或过期一律算失败（`STALE`，退出 1）；`random` 是 `corpus_report.py --fetch` 从 Wikipedia/arXiv 现抓的，本机没有就跳过。快照头部记了语料的 `corpus-digest`：重抓后语料本身变了，比对会拒绝执行而不是把「语料变了」误报成「引擎变了」。

模型太重，CI 里没有这一步——和 `golden_parse_checks.py` 一样，是提交前的本机纪律。

## 已修复（2026-07-30）

### P-001 `as` 省略从句没有收住后续修饰语

触发句：

> I have discovered, as perhaps Kelsey will after her much-publicized resignation from the editorship of She after a build-up of stress, that ...

当前结果把 `as perhaps Kelsey will` 单独收成状语从句，却把后面的 `after her ... stress` 放回外层。

期望骨架：

```text
I
have discovered
├─ as perhaps Kelsey will [discover]
│  └─ after her ... resignation ... after a build-up of stress
└─ that ...
```

回归判据：两个 `after` 短语都留在 `as` 从句内部，不与主句成分并列。

处理结果：当依存分析把尾部短语误挂到主句、但 Benepar 的紧邻 SBAR 明确把它收入省略从句时，以从句边界为准。真实模型回归已通过。

### P-002 并列动名词主语被拆成错误的小句

触发片段：

> that abandoning the doctrine of "juggling your life", and making the alternative move into downshifting brings ...

当前结果把 `and making` 吞进前一个宾语，又把名词 `move` 当成谓语，生成 `the alternative / move / into downshifting` 小句。

期望骨架：

```text
that
├─ 主语
│  ├─ abandoning the doctrine of "juggling your life"
│  ├─ and
│  └─ making the alternative move into downshifting
├─ brings
├─ with it
└─ far greater rewards ...
```

回归判据：两个动名词短语组成同一个主语；`the alternative move` 保持名词短语，不生成主谓小句。

处理结果：使用 Benepar 的并列 VBG 边界把两个动名词短语收成一个主语分支，不再依据错误的 `move=VERB` 依存边生成伪从句。真实模型回归已通过。

### P-003 `for` 引出的第二个主句没有形成独立层级

触发片段：

> ..., for, however farfetched and unreasonable their principles may seem today, it is possible that ...

当前结果把 `for`、`however ... today` 和 `it is possible ...` 全部放在顶层，无法看出让步从句属于 `for` 引出的第二个主句。

期望骨架：

```text
第一主句
for
└─ 第二主句
   ├─ however ... may seem today
   └─ it is possible
      └─ that ...
```

回归判据：`however` 从句与 `it is possible ...` 同属 `for` 引出的第二个主句，第一主句保持独立。

处理结果：解释性 `for` 后存在完整主谓骨架时，将 `for`、让步从句和第二主句收进同一“分句”分支。真实模型回归已通过。

### P-004 两句连选时被并成一个伪倒装谓语

触发文本（一次选中两句）：

> Indeed and he will. The boy who wants to know something about the grace, elegance and beauty of Euclid can go nowhere but up

当前结果把第一句句尾的 `will.` 当成倒装助动词，与第二句的主语和 `can go nowhere but` 归组成一个横跨句号的“谓语”，两个句子融成一棵错误的树。

期望骨架：

```text
Indeed / and / he / will.        （第一句，各成分独立）
The boy who ... Euclid           （第二句主语）
can go nowhere but               （第二句谓语）
up                               （状语）
```

回归判据：任何谓语归组（倒装、并列）都不得跨越以 `.` `!` `?` `;` `:` 结尾的块。

处理结果：`teaching_tree.py` 的 `_group_subject_aux_inversion` 与 `_group_coordinated_predicates` 在归组前检查前一块是否以句子/分句终结符收尾（merge_tiny 会把尾部标点粘到前块上，因此这是可靠的边界信号），是则拒绝归组。单测 + 真实模型探针均通过。

## 运行链路已修复（2026-07-30）

### R-001 插入性介词短语后的逗号丢失，导致整句被拒绝

触发句：

> The railroad industry as a whole, despite its brightening fortunes, still does not earn enough to cover the cost of the capital it must invest to keep up with its surging traffic.

该句可以被 spaCy 和 Benepar 正常解析，但生成教学树时没有覆盖 `despite ... fortunes` 后面的逗号。完整性校验报错：

```text
ValueError: teaching tree does not cover token range 11:12
```

原截图中的 `brightening fortuning fortunes` 也会复现同一问题，说明故障与重复单词无关。

回归判据：插入性介词短语两侧的标点均被相邻节点覆盖，整句能够返回结构树。

处理结果：单一介词短语子树也会接回解析范围外、但紧邻的标点；铁路例句已能完整返回结构树。

### R-002 单句解析错误被误报为 Benepar 未安装

`Sidecar.structure(for:)` 会把非 200 响应、解码失败和结构校验失败统一折叠为 `nil`；`ParseService` 随后把所有这类失败显示成“本地句法引擎暂不可用”。因此，R-001 实际返回的 422 被错误描述成模型未安装。

回归判据：模型启动失败、服务不可达和单句 422/500 使用不同错误信息；单句失败能够显示服务端返回的具体原因。

处理结果：Swift sidecar 客户端改为类型化错误；不可用、繁忙、422 句子错误、非法响应及结构校验失败分别提示。

### R-003 Swift 与 sidecar 重复处理破折号，生成零长度来源 token

触发句：

> The grand mediocrity of today—everyone being the same ...—means that ...
>
> While warnings are often appropriate and necessary--the dangers of drug interactions, for example--and many are required ...
>
> This development--and its strong implication for US politics ...--has enthroned ...

三句使用网页原始文本直接调用 sidecar 时均能返回完整结构。应用侧 `normalizedInput` 先把破折号改成两侧带空格的形式，sidecar 的 `prepare_parse_text` 又在破折号两侧插入解析空格，形成双空格。spaCy 随后产生无法映射回原文的空白 token，报错：

```text
ValueError: parser token has no source text
```

`off- spring` 页内断词不是本次失败原因。

回归判据：破折号无空格、单侧空格和双侧空格三种输入都能建立非零长度的来源映射；上述三句均能从应用入口返回结构树。

处理结果：Swift 保留原始破折号；sidecar 独占 parser view 的补空格操作，并对已有空格保持幂等。三条截图例句及三种空格形态均已加入回归。

## 新增输入路径

- `⌥A`：Accessibility 读取选中文字，失败后以模拟 `⌘C` 兜底。
- `⌥S`：调用系统区域截图，以匿名管道把 PNG 直接送入内存，再由 Apple Vision 在本机 OCR；按 Esc 静默取消。
- 两条路径共用 `normalizedInput` 与英文抽取、长度和语言比例校验，不上传截图或识别文本。
- OCR 图像由系统 `screencapture` 写入创建时设为权限 `0700` 的临时目录中的单次 PNG，读入内存后立即删除，不经过全局剪贴板；诊断日志位于用户 Application Support，权限为 `0600`，且不记录捕获文本。

## 本轮通过样本

以下样本的主干、从句归属和嵌套关系可以保留，细粒度标签不作为修复项：

- `Last year Mitsuo Setoyama ... raised eyebrows when he argued that ...`：已展示的外层结构通过，`that` 从句内部尚未展开复核。
- `Apart from the fact that ... no regular advertiser dare promote a product that ...`
- `The notion is that people have failed to detect the massive changes which have happened in the ocean because ...`：系表主干、表语从句、`which` 定语从句及 `because` 原因从句的归属正确。
- `One more reason not to lose sleep over the rise in oil prices is that, unlike the rises in the 1970s, ...`：长主语内部的不定式修饰、系表主干及 `that` 表语从句的嵌套正确。
- `This, for those as yet unaware of such a disadvantage, refers to discrimination against those whose surnames ...`：主干、插入性介词结构及 `whose` 定语从句归属正确。
- `From the beginning of our history, says Hofstadter, our democratic and populist urges have driven us to reject anything that ...`：前置状语、报道插入语与恢复后的主干关系正确，`that` 定语从句归属正确。
- `The true enemies of science, argues Paul Ehrlich of Stanford University, a pioneer of environmental studies, are those who ...`：主干未被报道插入语打断，`who` 定语从句及其内部的分词后置结构嵌套正确。
- `The test of any democratic society ... lies not in how well ... but in whether ..., however ...`：`not in ... but in ...` 并列骨架、两个嵌套从句及末尾 `however` 让步从句的归属正确。
- `But, for a small group of students, professional training might be the way to go since ..., all other factors being equal, ...`：主句、`since` 原因从句及其内部独立主格插入结构的归属正确。
