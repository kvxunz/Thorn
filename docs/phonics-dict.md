# 拼读词典数据格式（Resources/phonics-en.tsv）

单词输入路径（选中一个单词按 `⌥A`/`⌥S`）查询的本地词典。由
`scripts/build_phonics_dict.py` 离线生成：CMUdict 0.7b → 内嵌的 m2m 风格
EM 字素-音素对齐器（前向-后向 DP，纯标准库）→ maximal-onset 音节化 →
ARPAbet→IPA 映射 → 按字节序排序输出。约 12.5 万词条、7.3MB。

## 行格式

每行三个字段，制表符分隔，按词条字节序（`LC_ALL=C sort`）排序，运行时
mmap 后做行级二分查找（`PhonicsService.lookupLine`）：

```text
word<TAB>ipa<TAB>syllables
```

示例：

```text
about	əˈbaʊt	[a:ə].ˈ[b:b|ou:aʊ|t:t]
thorn	ˈθɔːrn	ˈ[th:θ|o:ɔː|r:r|n:n]
station	ˈsteɪʃən	ˈ[s:s|t:t|a:eɪ].[ti:ʃ|o:ə|n:n]
```

- 音节之间用 `.` 分隔；音节前缀 `ˈ`（主重音）/`ˌ`（次重音）可选。
- 每个音节是 `[chunk|chunk|…]`，chunk 为 `字素:IPA`。
- 词条全小写；撇号为 ASCII `'`；字素只含 `[a-z'-]`，因此 `:` `|` `[` `]`
  `.` 作为分隔符无歧义。

## 完整性不变量

生成端和消费端（`PhonicsService.parseEntry`）各校验一次，过不了宁可丢弃
（词条落回运行时的规则近似拆分）：

1. 所有 chunk 字素按序拼接必须逐字等于词条本身；
2. 每个源音素恰好被一个 chunk 覆盖、顺序不变（生成端校验）。

## 对齐器要点

EM 单元形状刻意收窄，避免联合归一化偏爱大单元（曾产出 `ab:əb` 这类
非教学块）：

- 1–2 个字母 → 1 个音素（辅音/元音二合字母：th、ea）；
- 1 个字母 → 2 个音素（x→ks、u→juː、o→wʌ）；
- 1 个字母 → 静音（魔法 e、gh），Viterbi 解码后并入前一 chunk——
  更长的教学字素（igh、ough）由此涌现，无需放宽单元上限。

## 重新生成

```bash
uv run --script scripts/build_phonics_dict.py            # 全量重建（约 2 分钟）
uv run --script scripts/build_phonics_dict.py --self-check  # 校验现有文件
```

词典未收录的词（CMUdict 无收录的新词/生僻词）运行时走
`PhonicsService.heuristicSplit` 规则近似拆分：贪心最长匹配的字素表 +
魔法 e + 开音节分组，不猜发音，浮窗标注「近似拆分」。

词典路径可用 `defaults write com.xvz.thorn phonicsDict /路径/phonics-en.tsv`
覆盖（同 sidecar 脚本的约定）。
