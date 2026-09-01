# Serial Fiction Studio

中文长篇连载小说的连续性管理 Skill，附带一个确定性的 Python 命令行工具。它把项目当前状态记在小说目录旁的账本里，每次开写前由脚本把账本压成一份有字符上限的上下文包，交给 Codex、Qoder 这类宿主模型起草正文。

正文始终是普通 Markdown 文件。它可以脱离本工具阅读、编辑、用 git 管理，也可以整体搬走。

## 职责划分

| 承担方 | 负责内容 |
|---|---|
| `scripts/story_workspace.py` | 项目状态、事实账本、词法与向量索引、上下文组装、草稿事务、机械检查、计划偏差、审计、备份 |
| 宿主模型 | 写正文、判断人物动机、语义审稿、从已接受章节提取事实 |

脚本不调用任何生成模型。`stage-events` 接收并校验宿主模型产出的 JSON，本身不做生成。`adapters/qoder/agents/` 下的文件是只读审稿角色定义，宿主加载之后才成为实际 Agent，不会自行在后台运行。

## 环境要求

| 项目 | 说明 |
|---|---|
| Python | 开发与测试均在 CPython 3.12，运行时只依赖标准库 |
| 语义检索 | 可选。需要可访问的 Ollama，embedding 协议固定为 `/api/embed`，通用云模型 API 接不上 |
| 近似最近邻 | 可选。`numpy` 与 `hnswlib`，清单见 `scripts/requirements-optional.txt`，缺失时退回精确余弦检索 |
| 平台 | 示例命令为 PowerShell。CI 覆盖 windows-latest，其他平台未做自动化验证 |

## 安装

### Codex

```powershell
git clone https://github.com/dyf1234567/serial-fiction-studio.git "$env:USERPROFILE\.codex\skills\serial-fiction-studio"
```

重启或刷新 Codex 后调用。

```text
$serial-fiction-studio 继续写当前小说下一章，保持人物、时间线和伏笔一致。
```

`agents/openai.yaml` 是 Codex 展示用的界面元数据，不需要单独运行。

### Qoder

把整个仓库复制到 Qoder 可读取的 Skill 目录。只需要多角色审稿时，把 `adapters/qoder/agents/` 下需要的角色复制到小说项目的 `.qoder/agents/`，或者用户级的 `~/.qoder/agents/`，再执行 `/agents reload`。这些角色全部只读，改写正文与项目状态的只有协调者。

### 不接宿主，直接当 CLI 用

```powershell
python scripts/story_workspace.py --help
```

`--help` 下列出 25 个子命令、全部参数与默认值。不熟悉某个操作时先看它，输出都是 JSON，可以直接重定向或交给脚本解析。

## 快速开始

### 1. 建项目与索引

```powershell
python scripts/story_workspace.py init D:\novels\well --title 井与戒
python scripts/story_workspace.py index D:\novels\well --embeddings none
```

`init` 建出 `chapters/` 与 `.storywork/`。正文文件名默认 `第{chapter:04d}章.md`，目录位置用 `--chapters` 指定，文件名模板写在 `.storywork/manifest.json` 里。已有稿件用 `adopt` 收编，先不带参数预览，确认后再加 `--apply --confirm ADOPT`。

### 2. 开一次草稿会话

```powershell
python scripts/story_workspace.py begin D:\novels\well --chapter 1 --goal "沈砚第一次下井"
```

```text
{
  "session": "20260901-004453-0e512d",
  "context": "D:\\novels\\well\\.storywork\\sessions\\20260901-004453-0e512d\\context.md",
  "retrieved": 0,
  ...
}
```

把 `context.md` 交给模型写草稿，草稿存成文件。

### 3. 检查、接受、重建索引

```powershell
python scripts/story_workspace.py mechanical-review D:\novels\well --session <session> --draft draft.md
python scripts/story_workspace.py accept D:\novels\well --session <session> --draft draft.md --confirm <session>
python scripts/story_workspace.py index D:\novels\well --embeddings none
```

`accept` 之后必须重跑一次 `index`，新章节才会进入检索库。在空项目上验证过这个顺序的影响，先索引后接受时查询 `井口的风` 命中 0 段，重跑索引后命中 1 段。

`mechanical-review` 只做确定性检查，产出如下几类 finding。

| code | severity | 触发条件 |
|---|---|---|
| `short-draft` | risk | 草稿正文去掉首尾空白后不足 800 字符 |
| `repeated-sentence` | risk | 同一句话在草稿中出现两次 |
| `forbidden-phrase` | error | 正文出现 `predicate` 为 `forbid_phrase` 的已批准决策中所登记的内容 |
| `plan-mutated` | error | 会话绑定的章纲版本在会话开始后被原地修改 |
| `plan-constraint` | error 或 risk | 触发章纲约束，硬约束记 error，其余记 risk |

报告末尾固定带 `requires_human_checkpoint: true`。草稿是否合格仍由人判断。

## 项目结构

```text
novel-root/
|-- chapters/                    已接受的正文
`-- .storywork/
    |-- manifest.json            书名、路径、检索设置
    |-- ledger.jsonl             只追加的账本
    |-- snapshot.json            rebuild 归约出的当前状态
    |-- library.sqlite3          可重建的词法与向量索引
    |-- sessions/                草稿事务、上下文包、审稿报告
    `-- revisions/               修订前的正文备份
```

账本只追加不覆盖，`rebuild` 把它归约成快照。账本与快照的完整字段说明见 [references/project-model.md](references/project-model.md)。

事件类型有六种。`fact` 是当前位置、阵营、伤势、持有、身份或规则这类断言，`setup` 是未兑付的伏笔，`payoff` 通过 `subject` 指名要解决的事件 id，`timeline` 是带序或带时点的 occurrence，`decision` 是作者约束而不是世界内事实，`chapter` 记录某一章的接受、修订或收敛。

## 命令

| 组 | 命令 |
|---|---|
| 项目与账本 | `init` `record` `adopt` `rebuild` `chapter-repair` |
| 索引与检索 | `index` `query` |
| 草稿事务 | `begin` `revise-begin` `mechanical-review` `accept` `recover` `review` |
| 事实提取 | `stage-events` `approve-events` |
| 章纲与节奏 | `plan-set` `outcome-set` `deviation` `pacing` |
| 审计 | `audit` `audit-pack` `audit-submit` `audit-finalize` |
| 备份 | `backup` `verify-backup` |

`review` 是 `mechanical-review` 的兼容别名，执行同样的确定性检查，不代表任何语义判断。

会改状态的操作各要一个确认值，写错就拒绝执行。

| 操作 | 确认值 |
|---|---|
| 收编已有章节 | `ADOPT` |
| 修复中断事务 | `RECOVER` |
| 批准第 N 章计划 | `PLAN-N` |
| 收敛某章的重复接受记录 | `REPAIR-N` |
| 接受草稿、实际结果或事实提案 | 对应的 session id |

## 检索

默认索引不带向量。

```powershell
python scripts/story_workspace.py index <小说目录> --embeddings none
```

设定集、旧稿、外部参考语料用 `--source` 带上，可以重复指定。

```powershell
python scripts/story_workspace.py index <小说目录> `
  --source <设定集目录> `
  --source <参考语料目录> `
  --embeddings none
```

第一次指定的来源写进项目 manifest。相对路径按当次命令的工作目录解析，存下来即为稳定路径，之后可省略 `--source`。已保存的来源找不到时索引报错并保留旧索引，不会静默清空。

启用语义检索。

```powershell
python scripts/story_workspace.py index <小说目录> `
  --embeddings ollama `
  --model bge-m3 `
  --endpoint http://127.0.0.1:11434 `
  --ann auto
```

查询默认按 0.65 词法、0.35 语义混合。

```powershell
python scripts/story_workspace.py query <小说目录> "谁拿走了银戒" `
  --lexical-weight 0.65 `
  --semantic-weight 0.35
```

结果里带 `mode`、请求权重、实际权重、降级警告和命中段落。改写类问题抬高语义权重，问事实抬高词法权重。检索命中只当证据读，设定以账本为准。

中文连续文本按两个字切词，单个汉字在 FTS5 里命中不了。查询只剩一个汉字时，脚本改走正文子串兜底，已有索引不需要重建，召回范围比二字查询宽。

各种缺依赖的情况都留下显式记录。

| 情况 | 行为 | 结果字段 |
|---|---|---|
| 当前 Python 的 SQLite 不含 FTS5 | 词法退成普通扫描 | `lexical_backend: scan`，`mode: lexical-scan` |
| 索引无向量，或 Ollama 不可达 | 语义权重整体转交词法 | `warnings` 一条说明，`effective_weights` 同步变化 |
| 索引元数据与实际表不一致 | 明确报降级并提示重跑 `index` | `mode: index-unavailable` |

## 改已接受的章节

```powershell
python scripts/story_workspace.py revise-begin <小说目录> --chapter 18 --goal "修正时间错误并保留既有结局"
python scripts/story_workspace.py mechanical-review <小说目录> --session <修订会话> --draft <修订稿>
python scripts/story_workspace.py accept <小说目录> --session <修订会话> --draft <修订稿> --confirm <修订会话>
```

直接改已接受的正文再套用旧 session 是不行的。`revise-begin` 容得下文件在事务之外被改过，它会同时记录快照里的摘要和文件实测的摘要，接受时文件再次变化就拒绝。修订前的文件留在 `.storywork/revisions/`，新的章节事件带 `supersedes` 顶掉旧版本，同一章不会留下两条当前记录。接受之后要重新提取受影响的事实并走人工批准，脚本不替你判断哪条旧事实该撤。

迁移过来的账本偶尔会给同一章留下两条当前接受记录。`audit` 报出冲突的正文文件名，事件 id 从 `.storywork/snapshot.json` 的 `chapters[]` 里按 `subject` 取，快照过期就先跑 `rebuild`。

```powershell
python scripts/story_workspace.py chapter-repair <小说目录> --chapter 3 --keep <event-id> --confirm REPAIR-3
```

这条命令追加一条带 `resolves` 的 reconciled 事件，其他正文文件一个都不删。多余文件名还留在正文目录时，下一次 `audit` 会把它报成孤儿文件，归档或删除由作者决定。

## 事实提取

章节接受之后提取候选事件，走 `stage-events` 与 `approve-events`。校验是硬性的。

| 约束 | 取值 |
|---|---|
| `evidence` 必须来自正文 | 必须是连续引文，不接受拼接 |
| 普通事件最短引文 | 6 个有效文字或数字 |
| `risk: high` 事件最短引文 | 10 个有效文字或数字 |
| 单条 `evidence` 上限 | 300 字符 |

有效字符指去掉标点与空白后的文字和数字，纯标点或两个字以内的短词过不了。

## 审计

```powershell
python scripts/story_workspace.py audit <小说目录>
```

`audit` 一次跑完全部确定性检查，报告写到 `.storywork/audit.json`，每条 finding 带 `severity` 与 `message`。检查项覆盖这几类。

- 正文文件摘要与账本完整性
- 账本记为已接受、磁盘上找不到的正文
- 正文目录里没写进账本的孤儿章节
- 悬置超过 `--setup-age`（默认 30 章）的伏笔
- 角色年龄倒退、同一时刻出现在两个地点、同一件东西同时有两个主人
- 角色死亡之后仍在发生的事件

分卷和全书的语义审稿要拆成批次交给人读。

```powershell
python scripts/story_workspace.py audit-pack <小说目录> --scope volume --from-chapter 1 --to-chapter 30 --batch-size 4
python scripts/story_workspace.py audit-submit <小说目录> --audit <audit-id> --batch 1 --findings findings.json
python scripts/story_workspace.py audit-finalize <小说目录> --audit <audit-id>
```

`audit-pack` 在批次旁边写一份有界的共享 `memory.md`，各批次不再重复嵌全量快照。每批开工前先读它，再核对批次里记录的 SHA-256。findings 字段是 `category`、`severity`、`chapter`、`evidence`、`message`，类别取 canon、chronology、character、setup、structure、prose。跨批次的问题记在靠后的那批并列出 `related_chapters`。结论分 error、risk、intentional 三档，作者故意留下的含糊不自动改。

## 备份与数据边界

```powershell
python scripts/story_workspace.py backup <小说目录> --archive <备份文件.sfs.zip>
python scripts/story_workspace.py verify-backup --archive <备份文件.sfs.zip>
```

旧的 `backup --out` 与位置参数写法仍然识别。备份包含计划、实际结果、偏差报告和已生成的 `pacing.json`。SQLite 与 HNSW 索引属于可重建数据，不进包。正文、manifest 和事件账本是可移植的事实来源。

`.gitignore` 已经屏蔽 `.storywork/`、`chapters/`、索引文件、压缩包和常见密钥路径。公开仓库不应包含小说正文、作者语料、索引、上下文包或个人备份。

## 实测数据

下表数字来自本机 CPython 3.12 的一次运行，对象是一棵 300 章、账本内含 1203 条事实的测试树。换一棵树绝对值会变，上限不会变。

| 项 | 实测值 |
|---|---|
| 上下文包预算 | 24000 字符 |
| 上下文包实际产出 | 14240 字符，其中记忆段 11691 字符 |
| 事实入选 | 1203 条中带入 214 条，省略 989 条，省略范围第 8 至 255 章 |
| 关键事实省略 | 0 条 |
| 附带原文段落 | 8 段 |
| 同一快照连跑两次 | 产出的 `context.md` SHA-256 相同 |
| 单字查询 `井` | 命中 5 段，0.12 秒 |

被省略的事实在 `begin` 输出的 `memory_context` 里按章节范围报出来，`omitted_critical` 单独列出，不会出现悄悄丢掉关键设定的情况。

## 已知限制

- 草稿质量、人物动机、伏笔兑现时机由人判断，机械检查只报确定性命中。
- 修订章节后旧事实需要重新提取并批准，脚本不自动撤销任何一条账本记录。
- 只读审稿角色是流程约定，依赖宿主的权限实现，不是操作系统级隔离。
- 语义检索只支持 Ollama 的 `/api/embed`，接其他向量服务需要改代码。
- CI 只在 windows-latest 与 Python 3.12 上跑，其他平台按用户报告处理。
- 作者启发型文风不在本仓库，需要文风分析或风格包时单独安装 [style-writer](https://github.com/dyf1234567/style-writer)。缺少它不影响连续性、检索、审计和备份。

## 测试与 CI

```powershell
python -m unittest discover -s scripts -p "test_*.py"
```

本机 31 个用例，4.5 秒跑完，1 个跳过，跳过的是需要 `hnswlib` 的那条。GitHub Actions 的 `test.yml` 在 windows-latest、Python 3.12 上执行同一批命令，`main` 最近一次 run 为 success。

## 文档地图

| 文件 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | 宿主模型加载的入口，含十条不可违反的不变式 |
| [references/project-model.md](references/project-model.md) | 目录布局与账本事件结构 |
| [references/drafting-loop.md](references/drafting-loop.md) | 准备、起草、审稿、接受、修订 |
| [references/memory-extraction.md](references/memory-extraction.md) | 章节接受后如何提出状态更新 |
| [references/retrieval.md](references/retrieval.md) | 索引、向量、可移植性 |
| [references/audits.md](references/audits.md) | 章节、分卷、全书三级检查 |
| [references/planning.md](references/planning.md) | 章纲、场景卡、实际结果与偏差、节奏 |
| [references/recovery.md](references/recovery.md) | 中断事务恢复与备份 |
| [references/multi-agent-editorial.md](references/multi-agent-editorial.md) | 多角色审稿模式与 Qoder 角色定义 |

## 许可证

仓库内的 Skill 代码与随附文档使用 [MIT License](LICENSE)。许可证不覆盖用户小说正文、第三方作者原文、风格语料、参考语料、生成的向量数据库，以及其他未进入本仓库的内容。
