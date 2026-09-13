# 外部差异审阅与修复边界

本轮由助手对 94 条差异逐项查看原句、目标关系和实际 spaCy token 依存。
这不是独立人工复核。原始报告 `reports/external-ewt.json` 保留不改，不能将归一化后
的得分改善称为引擎准确率提升。

## 已确认并修复的评测问题

UD 并列通常挂在首项，spaCy 可形成链。例如 alcohol → caffeine → sugar → fat。
原评测只查直接边，将同一并列组内的后续成员误报为失败。外部评测现在使用已经存在
的 Coordination.head/members 归一化首项边，保留原始边；开发集默认仍严格检查直接边。
不会把任意两个同组成员都视为直接边，不更改生产结构树。

## 其余分类与处理

- 存在句：place、much、charges、places、talent、surprises 在模型里是 attr，UD 是
  nsubj；不能为提高分数把全部表语重标成主语。
- 小句/宾语控制：find food better、have us reporting、want you to go、make forum a
  place、wanted you to know、let me say 的 nsubj+ccomp 与 UD obj+xcomp 不一致；
  需要明确标注体系转换，不应向生产图重复添加对象。
- 姓名与专名：Rohan Davey、Hu Jintao、Wei Ligang、Mike Griffin、John Donovan、
  al-Qaeda，以及 New Zealand、International Fund、Sunni Muslim 等中心与词性约定
  不同。不能把所有 compound 强制改成 amod 或更换所有专名中心。
- 介词引导的非谓语：about avoiding、With going、for fixing、in visiting、despite
  followed、for dealing、on what was found 在模型里经过 prep/pcomp 路径，UD 可直接
  连接到内容词；关系链的语义映射需要另行定义。
- 补足语：named Olly、grow older、looked great、looks cool 的 oprd/acomp 与 xcomp
  是体系差异，不是缺失该成分。
- 分词/不定式：much to do、places to buy、people to work 的 relcl/acl 不同；仅凭
  词形替换会破坏真正的关系从句，暂不强改。
- 分词歧义、修饰挂载：like music loud、participation to make、Catalog ready、
  Wholesale Price List、counter Microsoft Search using Encarta、condemning/announcing/
  calling 等需保留语境歧义并人工裁决。已看到后者并列实际挂到 issued，不属于并列链
  表示误报，不能靠归一化强行通过。
- 引语与句界：asks、worry、know 的根差异涉及 parataxis、标点与分句；cooked 被
  识别为形容词补足语。没有足够证据把所有引语、省略或形容词都改作主根。
- 不规范文本：defunctc ompany、job opening、life like、a plenty、any one、缺谓语
  的并列列表等涉及词性和分词错误；按具体拼写硬编码会过拟合。
- 80's 与 80 + 's 是对齐问题，仍计入失败；200–250、you guys、believe him 等也有
  数值范围、称呼中心、标注约定差异，需要人工核对，不删除评分目标。

逐条证据由本轮诊断取得；分类没有将尚未解决的项标记为修复。需要更广泛反例和人工
裁决后才能安全修改生产语法规则。新盲标入口见 `blind-annotation.md`。
