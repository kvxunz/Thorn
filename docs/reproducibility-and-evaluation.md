# 依赖锁定、模块拆分与独立评测

## 本轮交付边界

本轮实现运行依赖锁定、结构模块进一步拆分、外部人工校正语料评测，以及可复跑的
性能基准。不添加翻译缓存、不改变串行翻译流程、不切换模型。
这些改动还需另行提交及安装，不能把源码验证等同于已安装 App 更新。

## 5. 依赖与模型锁定

- `sidecar/server.py.lock` 固定直接及传递依赖、下载地址、SHA-256，包含 96 个包条目
  （含平台条件，并非每个平台安装全部包）。直接依赖采用之前验证过的版本；锁定后
  重新运行了完整真实解析回归和旧快照。
- `scripts/check_sidecar.py.lock` 固定 11 个轻量 CI 工具及传递依赖；普通 CI 不必安装
  Torch 或模型。Swift Package 没有第三方包依赖，因此无需空的 `Package.resolved`。
- Python 选择固定为 3.11.14，uv 验证版本为 0.11.22。App、安装脚本、开发工具入口、
  CI 均使用 `--locked`。依赖声明与锁文件不一致时拒绝运行，而不是改写签名包。
- `model-lock.json` 固定 Benepar 五个文件的 SHA-256，在安装后及模型加载前验证。
  spaCy 模型 3.7.3 的 wheel 哈希由运行锁文件记录。
- 默认 HY-MT2 Q6_K 的 Ollama 清单摘要在安装助手中验证，防止相同标签静默漂移。
  不强制覆盖用户在设置中选择的其他翻译模型，不自动删除或重新下载已有权重。
- 锁文件、Python 版本文件、模型清单随 App 携带。隔离运行测试检查真实解析、
  运行目录不被写入、旧锁不能被悄悄更新。

锁文件解决的是应用 Python 运行包及开发检查工具的可复现性，不是整个操作系统的
字节级可复现构建：Xcode、macOS SDK、签名身份、uv/Ollama 可执行程序与第三方 sdist
构建工具链仍是外部前提。外部权重即使保持同名，哈希不符也必须停下来审查，不能
为了继续运行而自动“接受新哈希”。

脚本锁使用 [uv 官方的脚本锁机制](https://docs.astral.sh/uv/guides/scripts/#locking-dependencies)。
旧开发脚本已移除重复的依赖声明，统一入口如下：

```bash
uv run --locked --script scripts/check_sidecar.py
uv run --locked --script sidecar/server.py --check-regressions
bash scripts/run-sidecar.sh tree_snapshot.py
bash scripts/run-sidecar.sh probe_sentence.py 'The people waiting outside looked tired.'
bash scripts/run-sidecar.sh devrunner.py --serve
python3 scripts/smoke_sidecar_runtime.py
```

显式升级依赖时修改声明，运行 `uv lock --script sidecar/server.py`，审阅锁文件 diff，
再执行上述检查。不要只改模型摘要来掩盖下载内容变化。

## 6. 大型模块拆分

原 `syntax_assembly.py` 约 1625 行，现在按职责分为：

| 文件 | 职责 | 行数 |
| --- | --- | ---: |
| `syntax_assembly.py` | 不可变结果和句子级编排 | 66 |
| `syntax_boundaries.py` | 归属、边界锚点、阻挡范围 | 148 |
| `syntax_nominal.py` | 名词与介词内部结构 | 447 |
| `syntax_clause.py` | 从句递归与 token 分配 | 687 |
| `syntax_grouping.py` | 并列、解释从句、列举及固定搭配分组 | 298 |

名词分析显式接收从句分析回调，不反向导入从句模块，避免循环依赖。
结构层仍不能运行时导入服务或展示层；类型检查专用引用不视为运行依赖。
模块大小、回调边界和预提交快照门禁均有自动化检查。
此次保持结构规则行为不变，不把机械拆文件宣称为解析准确率提升。

## 7. 外部人工校正标注评测

使用 [UD English EWT](https://github.com/UniversalDependencies/UD_English-EWT)
发布版本 r2.18 的 test split，固定提交
`b7711cce01cdd4f5fcc0a8199b8a50d951b16c0c`。
上游说明基础依存树经过人工校正，主要是单人标注；不使用主要自动生成的 enhanced
dependencies。标注和数据库权利采用 CC BY-SA 4.0，底层文本保留原作者权利。
标注归属 Stanford/UD English EWT contributors；本项目做的转换是下面明确列出的
关系映射及筛选。原始语料不随 App 或仓库再分发，报告中的派生标注信息按相同许可使用。

五种文体各 20 句，共 100 句。筛选仅看原始金标准：8–60 个 token、唯一动词主根、
无 copula、被评分的锚词唯一，按句子 ID 的 SHA-256 排序。
`external_eval_manifest.json` 在第一次模型评估前冻结，记录原文哈希和全部句子 ID。
没有根据解析结果删题、换题或修改期望。

这里只映射可比的基础依存关系：主宾语、内容从句、开放补足语、关系/分词修饰、
状语从句、形容词修饰、并列边。UD 介词挂载与 spaCy 的中心词体系不同，本轮不强行
映射；copula 构式也预先排除。不是全量 LAS/UAS，也不是均匀随机的实际用户句子分布。

| 目标 | 首次评测 | 并列归一化后 | 对齐修复后（当前） |
| --- | ---: | ---: | ---: |
| 有效解析 | 100 / 100 | 100 / 100 | 100 / 100 |
| 主句中心 | 96 / 100 | 96 / 100 | 96 / 100 |
| 主干关系 | 207 / 234 | 207 / 234 | 207 / 234 |
| 修饰/补足挂载 | 158 / 198 | 158 / 198 | 159 / 198 |
| 并列边 | 40 / 62 | 52 / 62 | 52 / 62 |
| 失败记录数 | 94 | 82 | 80 |

三列分别对应 `external-ewt.json`、`external-ewt-normalized.json`、
`external-ewt-aligned.json`。后两列的改善来自**评测侧**的两处修复——并列链归一化到
UD 首项边、`80's` 数字后缀的确定性对齐——不是引擎语法准确率提升。生产结构树未改。
首次评测里那个无法唯一对齐的金标准锚词（`80's`）现已解决；其余 80 条失败保留在
基线报告中，不把解析成功率当作关系正确率。
这些差异可能来自模型错误、标注体系差别或歧义，未经逐项人工审阅不能全归为引擎缺陷。

它是外部人工校正的公开评测，不是本项目新组织的双人盲标，也不能排除模型训练数据
重叠。若要求真正独立的新材料盲标，仍需要真人标注与复核，不能用助手答案替代。

```bash
curl --fail --location https://raw.githubusercontent.com/UniversalDependencies/UD_English-EWT/b7711cce01cdd4f5fcc0a8199b8a50d951b16c0c/en_ewt-ud-test.conllu -o /tmp/ewt.conllu
uv run --locked --script sidecar/server.py --evaluate-external /tmp/ewt.conllu > /tmp/external-ewt.json
python3 scripts/check_external_report.py docs/reports/external-ewt-aligned.json /tmp/external-ewt.json
```

门禁基线是 `external-ewt-aligned.json`，即当前代码的实测结果，CI 用同一份。
`external-ewt.json` 和 `external-ewt-normalized.json` 是它之前的两次记录，保留作为
归一化与对齐修复的证据，不再作为门禁：拿旧报告当基线会让门槛低于现状，
使已修复的失败重新出现时不报警。

评测命令是诊断报告模式：语料/执行错误返回非零，关系不匹配会完整写入报告。
回归门禁另行比较目标数量、语料身份及每条失败，禁止新增失败；不是要求已有错误
全部消失。真实模型 CI 已接入该门禁并上传报告，本轮修改后的远程工作流尚未运行。

## 8. 性能基准

`benchmark.py` 用 3 个全新 Python 子进程，各对 4 类固定句子测量 5 次。
记录模型加载、首次解析、暖解析各阶段、原始采样、median、nearest-rank p95、峰值 RSS，
同时记录全部已安装 Python 包版本、Python/平台、语料与源码指纹。
比较工具拒绝不同语料、平台、解释器、依赖或采样次数的直接比较。

```bash
uv run --locked --script sidecar/server.py --benchmark > /tmp/parser-benchmark.json
python3 scripts/compare_parser_benchmarks.py docs/reports/parser-after.json /tmp/parser-benchmark.json
```

本机顺序测量；before 是提交 `82783bc` 的源文件，前后都使用本轮锁定的同一依赖环境。
before 不带锁文件，因此其报告的 `lock_sha256` 为空，而包版本可逐项比较。
操作系统文件缓存未清空，不宣称是真正断电冷启动；加载时间不含 uv、解释器启动或下载。
不包括 App UI、HTTP、翻译，也未在不同硬件上汇总。

| 中位数 | 拆分前 | 拆分后 |
| --- | ---: | ---: |
| 模型初始化 | 2.411 s | 2.487 s |
| 首次短句解析 | 31.53 ms | 30.71 ms |
| 暖短句 | 27.18 ms | 26.95 ms |
| 暖长句（原测试句） | 52.69 ms | 52.66 ms |
| 峰值 RSS | 3.19 GiB | 3.19 GiB |

结构拆分没有显示明显的暖解析回退，也没有证据证明显著加速。初始化增加约 76 ms，
新版本包含模型完整性校验；小样本顺序测试不能把这点差异全归因于某个函数。
长句约 50 ms 花在模型推理，结构组装约 2 ms，展示投影约 0.25 ms。
后续性能优化应先关注模型加载/推理及内存，不继续为微小收益拆规则或增加翻译缓存。

原始报告：`reports/parser-before.json`、`reports/parser-after.json`，以及三次外部评测
`reports/external-ewt.json`、`reports/external-ewt-normalized.json`、
`reports/external-ewt-aligned.json`（最后一份是门禁基线）。
