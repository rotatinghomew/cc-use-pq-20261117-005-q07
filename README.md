# 叙事母题证据台账

这是一个供文学课程与民间叙事研究小组使用的本地分析工具。研究者导入有来源说明的故事结构记录，逐条标注判断及其事件依据，再查看标注共识、未决覆盖率和可回溯报告。工具不自动解释文学意义，也不把新闻评论中的解释当作已验证结论。

## 运行

需要 Python 3.11 或更新版本，无第三方依赖。

从项目根目录运行：

```sh
PYTHONPATH=src python -m story_patterns.cli demo --database /tmp/story-patterns.sqlite3 --fixture fixtures/demo.json
```

也可分别使用 `import`、`decide` 与 `report` 子命令处理 JSON 文件。每个故事修订版包含来源、角色顺序及连续事件；每项判断必须引用该修订版中的事件。批次标识支持安全重试，标注标识与标注员序号不可覆盖既有内容。

支持包含故事对象的 JSON 数组或逐行 NDJSON 导入；这两种格式需使用 `--batch-id`。`queue` 展示未评、待补共识、分歧及已达共识的样本，并列出尚未被判断引用的事件。`report` 同时给出标注员两两一致率及事件证据覆盖率；这些是描述性指标，不替代人工解释。报告以内容指纹保存，可用 `export --report-id ... --format json|csv --output ...` 输出；默认拒绝覆盖现有文件，显式 `--force` 才替换。`audit` 检查 SQLite 内部与外键完整性。

每个故事修订可以声明 `branch`（缺省为 `main`）与 `parents`（缺省为同故事上一序号的线性父修订；显式空列表表示无父修订）。同一父修订的多个子修订即分叉，含多个父修订的修订即汇合，目录由此记录真实的版本 DAG 而非假定的线性链。显式声明的父修订必须已存在于目录或同批次中；未声明时的线性缺号仍由 `lineage` 报告。`branches` 展示每个故事的分支、分叉点、汇合点、分支末端的最近共同祖先与生命周期标记；`search --revision-policy tips` 列出每个分支的末端修订（`latest` 仍只取全局最大序号），`search --branch` 按分支过滤。判断与仲裁可附带 `branch` 字段，系统会校对其与目标修订的实际分支一致。`report`、`queue`、`compare` 均支持 `--branch` 限定范围；报告的 `branch_structure` 一节与 `compare` 的 `branch_breakdown` 会标明每组数字引用的是哪一支。

编辑可用 `mark-branch` 记录分支生命周期标记：`merged`（须指明目标分支与汇合修订，且必须与目录中已记录的父子结构一致）或 `retired`（不再采用）。标记只增不改：被汇合或弃用的分支及其修订、判断全部保留，可审计；重复提交同一标记返回 `already_recorded`，同一标识的不同内容会被拒绝。`audit` 同时复核修订边与分支标记是否和不可变文档一致。

导入前可以用 `preview` 汇总每条记录的校验错误，不写数据库；正式导入仍坚持整批事务。`lineage` 展示已录入的修订版本与缺失序号。`compare` 按传统标签分层输出描述性比例、共识数与覆盖率；不同分组的分母可能不同，结果不作因果或总体推断。

`manifest` 汇总导入批次、故事修订和来源引用。保存报告还包含读者剔除敏感性检查，提示结论是否依赖某位读者；该诊断不等同于置信区间。报告可导出为 Markdown (`--format md`) 供课程讨论。

`audit` 除 SQLite 外键和数据库完整性检查外，也会复核故事文档与索引列、导入批次摘要、标注证据、仲裁摘要及已保存报告的内容指纹是否一致。修订对比沿父修订边进行，标出角色、顺序、来源和事件内容变化，并注明每条边属于线性延续、分叉还是汇合；每个版本独立标注，系统不把旧版判断自动复制到新版。

报告列出最新有效读者的逐标签投票数和每位读者覆盖的修订数；被后续序号取代的旧判断仍保留在 `history`，但不会重复进入统计。

若独立标注存在分歧，编辑可用 `adjudicate` 提交单独的处理记录。它要求引用当前修订事件与简短理由，不覆盖任何读者投票；报告并列保留独立共识、最终采用标签及仲裁依据。`history` 可查看一位读者此前的判断和所有仲裁版本。

报告分别统计“平行型/加害型”判断和最小者结局判断。`unclear` 与 `unknown` 不进入对应投票，但覆盖表会保留同意、分歧和样本不足数量。报告列出参与故事修订及判断编号，便于复核。数据库仅保存在用户指定的本地路径。

演示文件完全由本地合成材料构成，并非新闻报道或已出版故事的原文。`fixtures/demo.json` 演示基本流程；`fixtures/branching.json` 演示分叉—再汇合—普通线性修订共存的场景：两个异本从同一校订本分叉、汇合校订本收录两支、残卷异本被标记弃用但保留记录，同时演示重复导入与重复判断的幂等返回。

```sh
PYTHONPATH=src python -m story_patterns.cli demo --database /tmp/story-patterns-branch.sqlite3 --fixture fixtures/branching.json
```

## 检查

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src
PYTHONPATH=src python -m story_patterns.cli demo --database /tmp/story-patterns-check.sqlite3 --fixture fixtures/demo.json
PYTHONPATH=src python -m story_patterns.cli demo --database /tmp/story-patterns-branch.sqlite3 --fixture fixtures/branching.json
```
