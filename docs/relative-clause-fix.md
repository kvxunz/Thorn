# 限定关系从句与名词补语归属修正

## 本轮范围

- `syntax_structure.relative_role` 判断 VBG 独立结构时，先排除带限定助动词的从句。过去式、现在式、情态助动词均检查；完成进行时保留其限定性。
- `syntax_clause` 对直接带 `relcl` / `acl` 的名词性补语保留父节点，关系从句和内容从句不再与其所属名词平铺。未将所有补语强制增加层级。
- 用户蜜蜂例句的主干保持主语、谓语、补语；内容从句归入 message，零关系词从句归入 one，而不是插入语。
- 新增进行时、完成进行时、显式关系词、前置介词、真正插入语、独立结构状语和宾语内容从句回归检查。
- 审阅并更新现有 246 句快照中的 13 处差异：只调整名词补语的父子归属及相应标点边界，不将快照通过视为语法正确率。

## 网上输入与复现

来源：[标注为 Cambridge IELTS 4 General Training Test 2 的第三方转录](https://engnovate.com/ielts-reading-tests/cambridge-ielts-04-general-training-reading-test-2/)。出版社样章下载超时，未完成逐字版本核对；不得称为出版社核验语料或独立人工金标。

选取五个完整句子，长度分别为 29、27、24、32、37 个空格分词，涉及嵌套关系从句、条件结构、倒装、非限定修饰和非谓语结构。难度未经过独立评级；这批输入不是全面准确率评测。

网页蜜蜂句与用户输入有词汇差别，测试保留网页原句。为避免重新分发原文，HTML 仅存本地临时目录，仓库只保存选择器与句子哈希。

```sh
curl -fL --max-time 45 https://engnovate.com/ielts-reading-tests/cambridge-ielts-04-general-training-reading-test-2/ -o /private/tmp/thorn-cambridge4.html
"$MODEL_PYTHON" scripts/ielts_sentence_probe.py /private/tmp/thorn-cambridge4.html
```

脚本要求每个选择器唯一匹配，并检查非空解析、依存图诊断、顶层 token 完整且不重复；蜜蜂句另外检查关系从句角色及名词父节点。五句这些检查均通过，不代表其他四句的全部修饰关系已人工验收。

完整语法校正仍受上游模型质量限制；本轮不引入翻译缓存，不改变翻译串行策略。源码验证与 App 安装是不同交付步骤。

`MODEL_PYTHON` 必须指向已安装 sidecar 依赖及模型的 Python 环境；`run-sidecar.sh` 的工具白名单不接受任意 scripts 路径。

后续扩大语料的结果与未解决项见 [雅思批量评测](ielts-corpus-evaluation.md)。此页五句结果仅描述最初的定点验证，不代表当前全部评测范围。
