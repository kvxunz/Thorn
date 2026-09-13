# 句法拆解问题清单

只记录会影响主干、从句归属或嵌套关系的问题。词性、措辞和细粒度标签不进入待修范围。

下面每条的「回归判据」都有一条对应的可执行测试，跑真 spaCy + Benepar：

```bash
uv run --script sidecar/server.py --check-regressions
```

该套件不叫 `test_*.py`，因此不会被 `python -m unittest discover -s sidecar` 收走——快测保持零依赖、毫秒级。改动拆句规则后必须跑一次：判据只有能执行才拦得住回归（见 LEARNINGS #42）。

### 用常驻进程跑（推荐）

模型加载约 70 秒且每次 `uv run --script` 都要重付一遍，改一条规则要等好几分钟才知道有没有用。`devrunner.py` 把模型常驻在一个 worker 里，脚本变成客户端：

```bash
# 起一次，之后一直用
tmux new-session -d -s thorn-dev -c sidecar 'uv run --locked --script server.py --tool devrunner.py -- --serve'

cd sidecar
python3 devrunner.py golden_parse_checks.py            # 95s -> 1.5s
python3 devrunner.py corpus_report.py --constructions  # 150s -> 20s
python3 devrunner.py /tmp/probe.py                     # 一次性探针也走这条路
```

客户端是纯标准库、跑在裸 `python3` 上，不经过 `uv`，否则每次调用又要解一遍环境。

worker **每个 job 都把 sidecar 目录下的模块从 `sys.modules` 里清掉**，让脚本重新从磁盘 import——所以它永远跑的是当前工作区的代码，不会拿一小时前加载的旧规则报绿。唯一常驻的是 `nlp`。这一点是这个设计必须守住的：一个测的是旧代码的绿色套件，比一个慢套件危险得多。

### 快照：唯一看得见「切太碎」的东西

`undersplit.py` 只报**粗卡**——切得不够。没有任何指标报切得太碎，而拆分规则的改动是在这两种失败之间做交易：列表被打散成一串「插入语」、卡片停在孤立介词上、日期在逗号处被切开——这六个缺陷当初**全部**是以「粗卡率下降」的形式出现的。指标说赢了，树其实坏了。

`tree_snapshot.py` 把 `constructions` 语料库每一句的整棵树冻在 `sidecar/snapshots/` 下：

```bash
cd sidecar
python3 devrunner.py tree_snapshot.py           # 比对，有漂移退出 1
python3 devrunner.py tree_snapshot.py --write   # 逐行看过之后再接受
```

它**不断言树该长什么样**，只断言树没有在没人过目的情况下变过。这里出现 diff 不是失败，是一次待审。改 `chunk_roots` 或 `np_expand` 拆分链之后，先跑它，把每一行读一遍——确认每处改动都是改进，再 `--write` 接受，并把快照和代码放进同一个 commit。

语料随代码一起进仓库，所以快照缺失或过期一律算失败（`STALE`，退出 1）。快照头部记了语料的 `corpus-digest`：往 `english_sentence_training.md` 里加句子之后语料本身变了，比对会拒绝执行而不是把「语料变了」误报成「引擎变了」。

曾经还冻过一份 `random` 快照，2026-08-27 删掉了：它的语料只存在于 `/tmp/thorn_corpus.json`，而 `corpus_report.py --fetch` 每次都从 Wikipedia 的 `generator=random` 现抓一批新句子，digest 必然对不上，比对**永远**走「跳过」。它只能被写，不能被读。随机语料的覆盖率测量仍然有效，但那是 `corpus_report.py` 当场抓、当场测的事，不需要冻在仓库里。

真实回归已接入手动触发的 `Live parse regression` 工作流。完整树快照仍在本机比较，
不能用真实回归通过替代快照审阅。当前模块边界见 [解析架构说明](parser-architecture.md)。

### 把纪律变成闸

「记得跑一下」不是机制。装上钩子之后，动了拆句规则却没过快照，提交直接被拒：

```bash
git config core.hooksPath scripts/githooks
```

它不是检查「快照文件有没有跟着改」——**一次正确的重构本来就不该移动任何一棵树**，那样的闸会在最该放行的提交上开火。它是真的去跑一遍比对：worker 在就走 `devrunner`（几十秒），报 unchanged 就放行，有漂移则拒绝并让你逐行读完再 `--write` 接受；worker 不在就拒绝并告诉你怎么起。确实动不了树的改动（改注释、改文档字符串）用 `git commit --no-verify`。

### 请求闸（不需要模型）

`service_checks.py` 测的是句子到达解析器**之前**的那一层：token 鉴权、512 词上限、两个并发槽位的 429、`ValueError → 422` 映射以及失败路径必须归还槽位。

```bash
uv run --locked --script ../scripts/check_sidecar.py
```

`server` 把 torch/spacy/benepar 的 import 推迟进了 `load()`，所以这个套件不加载任何模型，**CI 每次 push 都会跑**。这是有意的：一道只能在那台装了 3.2 GB 权重的机器上验证的鉴权闸，等于一道想起来才验证的闸。

## 已修复（2026-08-04）

### P-005 动词层并列的介词短语被标成宾语

触发句：

> He was troubled first by the noise and later by one thing above all: the fear of being found out.

spaCy 把第二个 `by` 标成 `conj` 挂在**动词** `troubled` 上（不是挂在第一个 `by` 上），于是 `coordinated_prep_conjuncts` 够不到它，它落进 `chunk_roots` 的 `conj` 兜底分支：

```python
roots.append((c, "object" if head.pos_ in ("VERB", "AUX") else "adverbial",
              contains_clause(c)))
```

结果 `later by one thing above all: the fear of being found out.` 被标成 **`[宾语]`**——一个介词短语挂着错误的语法标签教给学习者——而且 `expand=contains_clause(...)=False`，那个冒号补足语也一起被吞成一张 14 词的平卡。

这是 LEARNINGS #30 的同一个坑第三次出现：conj 兜底「动词的非动词并列项 = 宾语」对介词短语同样不成立。判据（通用，非指纹）：conj 到动词的 `ADP`/介词性成分，其角色应当由它自己的形态决定（prep-phrase），而不是由 head 的词性决定。

处理结果：在 conj 兜底之前加一条判据——`ADP` 且自己带 `pobj` 的并列项判成 `prep-phrase`，并走 `expands_as_prep_phrase()`（即 P-006 那条共享谓词）。判据是**结构性**的（#41）：管辖一个 `pobj` 才算介词短语，所以并列的小品词或副词（"gave in and up"）不会误入这条分支，不需要词表。

回归判据：`golden_parse_checks.py::test_p005_coordinated_prep_on_a_verb_is_not_an_object` —— 该并列项 role 为 `prep-phrase` 而非 `object`，与第一个并列项同角色，且冒号补足语单独成子卡。撤掉修复即失败（#43）：role 退回 `object`，children 退回空列表，两条断言各自都有承重。

快照影响（这是它比 P-006 宽的地方，事先说过要单独审）：constructions 与 random 各漂 **1 行**，逐行看过，两条都是改善——被翻的都是被动句的 agent（`by …`），标成「宾语」在被动句里根本不可能成立，而且两条的并列兄弟项本来就已经标着 `prep-phrase`，翻完才自洽。random 那条是维基百科的真实文本，不是我造的句子。

关于影响面的一处更正：修之前的探针只扫了 `sent.root` 的直接子节点，预测 0 处翻转；实际是 2 处，因为真实的两例都藏在更深的从句 head 下面。探针的作用域比它声称的窄——这类预测要么按整棵树扫，要么就别用它当放行依据。

### P-006 并列的第二个介词短语不展开，第一个展开

触发句：

> The decline was driven first by falling demand and then by several modifications, including deficits in staffing and morale.

`chunk_roots` 里介词短语有两条入口：`prep`/`agent` 走主分支，而并列上来的第二个介词（spaCy 标 `conj`）走 promotion 分支。两处各自写了一份「要不要展开」的判据，promotion 那份**少了四条 fence 判据**，于是同一个短语在第一位是分层卡、在第二位是一行 12 词的平卡。

附带发现：promotion 分支里的 `is_adverbial_complex_prep(conjunct)` 是**死调用**——该谓词第一行就是 `if prep.dep_ not in ("prep", "agent"): return False`，而 conjunct 的 dep 恒为 `conj`。

处理结果：两处合并为 `expands_as_prep_phrase()`，两个调用点变成同一个表达式，不会再各自漂移。死调用保留在共享谓词里（而不是特判掉），以维持两处字面一致；让并列的 `because of` 也判成状语是另一个问题，需要它自己的句子。

回归判据：`golden_parse_checks.py::test_coordinated_prep_expands_like_a_first_position_one` —— 并列项展开、逗号补足语单独成子卡、且不拍平到顶层。按内容寻址（#44），撤掉修复即失败（#43）。

两个语料库（constructions 246 + random 200）**均无漂移**——这不是「验证通过」，是 LEARNINGS #47：这两个语料里一句这种构式都没有，快照对它无话可说。证据来自探针句，不是来自语料。要真正**测量**这个构式，得让 `corpus_report.py --fetch` 抓到带 fence 的并列介词短语。

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
- `⌥S`：调用系统区域截图，把 PNG 落到 0700 临时目录后读入内存并立即删除，再由 Apple Vision 在本机 OCR；按 Esc 静默取消。（`screencapture` 拒绝管道目标且失败时 exit 0 + 0 字节，见 LEARNINGS #34。）
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
