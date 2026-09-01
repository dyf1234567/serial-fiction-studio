# 连载小说工作室（Serial Fiction Studio）

写到第三百章，那枚戒指在谁手里，模型的答法会跟着变。把整本书贴进上下文，先撞预算；只贴人物小传和设定摘要，它又会写出第十二章里没有的事。这个 Skill 管的是中间这一层。正文始终是你目录里的普通 Markdown，项目记忆写在 `.storywork/ledger.jsonl`，只追加不覆盖，`rebuild` 把账本归约成当前快照，每次开写前由脚本压成一份有上限的上下文包交给宿主模型。

下面的数字来自本机 Python 3.12 的一次真实运行。换一棵树数字会变，上限不会。测试树有 300 章，账本里存着 1203 条事实。在这棵树上跑 `begin`，上下文包 14240 字符，带进 8 段原文，同一份快照连跑两次产出的文件逐字节相同；上下文包预算固定 24000 字符，装不下的事实按章节范围截断，报告里写清省略了多少条。

## 快速开始

```powershell
python scripts/story_workspace.py init D:\novels\well --title 井与戒
python scripts/story_workspace.py index D:\novels\well --embeddings none
python scripts/story_workspace.py begin D:\novels\well --chapter 1 --goal "沈砚第一次下井"
```

`init` 建出 `chapters/` 与 `.storywork/`。正文文件名默认 `第{chapter:04d}章.md`，目录位置用 `--chapters` 换，文件名模板写在 manifest 里，直接改那一行。`begin` 打印两样东西，session 编号和 `.storywork/sessions/<session>/context.md` 的路径。把那份 context.md 交给模型写草稿，存成文件，再走检查和接受。

```powershell
python scripts/story_workspace.py mechanical-review D:\novels\well --session <session> --draft draft.md
python scripts/story_workspace.py accept D:\novels\well --session <session> --draft draft.md --confirm <session>
python scripts/story_workspace.py index D:\novels\well --embeddings none
```

`accept` 之后重跑一次 `index`，新章节才进检索库。这条我在空项目上验过，先索引后接受时查 `井口的风` 命中 0 段，重跑索引之后命中 1 段。

`mechanical-review` 只做确定性检查。少于 800 字符报 `short-draft`，重复句报 `repeated-sentence`，正文里出现已批准决策中的 `forbid_phrase` 也报出来，末尾固定带 `requires_human_checkpoint`。这段草稿好不好，仍然要人看。

## 分工边界

脚本这边负责项目状态、事实账本、词法与向量索引、上下文组装、草稿事务、机械检查、计划偏差、审计和备份。写作、人物动机判断、语义审稿和章节事实提取交给 Codex、Qoder 这类宿主模型。

`adapters/qoder/agents/` 里的文件是只读审稿角色定义，宿主加载之后才成为实际 Agent，它们不会自己在后台运行。`stage-events` 接收并校验宿主模型产出的 JSON，本身不调用任何生成模型。

## 安装

### Codex

```powershell
git clone https://github.com/dyf1234567/serial-fiction-studio.git "$env:USERPROFILE\.codex\skills\serial-fiction-studio"
```

重启或刷新 Codex 之后直接说这句。

```text
$serial-fiction-studio 继续写当前小说下一章，保持人物、时间线和伏笔一致。
```

`agents/openai.yaml` 给 Codex 展示 Skill 名称、简介和默认调用提示，属于界面元数据，不用单独运行。

### Qoder

把整个仓库复制到 Qoder 可读取的 Skill 目录。只想要多角色审稿时，把 `adapters/qoder/agents/` 里需要的角色复制到小说项目的 `.qoder/agents/`，或者用户级的 `~/.qoder/agents/`，再执行 `/agents reload`。这些角色全部只读，动正文和改状态的只有协调者一个。

## 检索

默认索引不带向量。

```powershell
python scripts/story_workspace.py index <小说目录> --embeddings none
```

要把设定集、旧稿或外部参考语料一起索引，`--source` 可以重复写。

```powershell
python scripts/story_workspace.py index <小说目录> `
  --source <设定集目录> `
  --source <参考语料目录> `
  --embeddings none
```

第一次指定的来源会写进项目 manifest。相对路径按当次命令的工作目录解析，存下来就是稳定路径，往后可省略 `--source`。已保存的来源找不到时，索引报错并留着旧索引，不会静默清空。

词法检索优先用 SQLite FTS5。当前 Python 的 SQLite 不含 FTS5 时自动降级成普通扫描，结果里返回 `lexical_backend: scan`。

启用语义检索走 Ollama。

```powershell
python scripts/story_workspace.py index <小说目录> `
  --embeddings ollama `
  --model bge-m3 `
  --endpoint http://127.0.0.1:11434 `
  --ann auto
```

embedding 协议固定是 Ollama 的 `/api/embed`。`--endpoint` 指向本机或远端 Ollama 都行，通用云模型 API 接不上。装了 `numpy` 和 `hnswlib` 时 `--ann auto` 用 HNSW，否则退回精确余弦检索。

查询默认按 0.65 词法、0.35 语义混合。

```powershell
python scripts/story_workspace.py query <小说目录> "谁拿走了银戒" `
  --lexical-weight 0.65 `
  --semantic-weight 0.35
```

查询结果会写清 mode、请求权重、实际权重、降级警告和命中段落。索引里没有向量、或者 Ollama 临时连不上，语义权重整体转交给词法检索，同时留下一条警告。改写类的问题抬高语义权重，问事实抬高词法权重。检索命中当证据读，设定仍以账本为准。

中文连续文本默认按两个字切词，单个汉字在 FTS5 里因此命中不了。查询只剩一个汉字时，脚本改走正文子串兜底，已有索引不必重建就能用，召回范围比二字查询宽。同一棵 300 章的树上查 `井`，兜底召回 5 段，用了 0.12 秒。

索引元数据与实际 SQLite 表对不上时，查询会明确返回降级或 `index-unavailable`，并提示重跑 `index`，不会把空结果当成一次正常查询报给你。

## 修订已接受的章节

```powershell
python scripts/story_workspace.py revise-begin <小说目录> --chapter 18 --goal "修正时间错误并保留既有结局"
python scripts/story_workspace.py mechanical-review <小说目录> --session <修订会话> --draft <修订稿>
python scripts/story_workspace.py accept <小说目录> --session <修订会话> --draft <修订稿> --confirm <修订会话>
```

不要直接改已接受的正文，再套用旧 session。`revise-begin` 容得下文件在事务之外被改过，它会同时记录快照里的摘要和文件实测的摘要；接受时文件又变了，就拒绝。修订前的文件留在 `.storywork/revisions/`，新的章节事件带 `supersedes` 顶掉旧版本，同一章不会留下两条当前 canon。接受之后要重新提取受影响的事实并走人工批准，脚本不替你猜哪条旧事实该撤。

提取出来的 evidence 必须是正文里连续的话，普通事件至少 6 个有效文字或数字，高风险事件至少 10 个，纯标点和两个字以内的短词过不去。

## 收敛旧项目的重复记录

迁移过来的账本，偶尔会给同一章留下两条当前接受记录。`audit` 报出冲突的文件名，事件 id 要去 `.storywork/snapshot.json` 的 `chapters[]` 里拿，按 `subject` 对上要保留的那条，快照过期就先跑 `rebuild`。

```powershell
python scripts/story_workspace.py chapter-repair <小说目录> --chapter 3 --keep <event-id> --confirm REPAIR-3
```

这条命令追加一条带 `resolves` 的 reconciled 事件，其他正文文件一个都不删。不同文件名还留在正文目录时，下一次 `audit` 会把它报成孤儿文件，归档还是删掉由你决定。

## 审计

`audit` 一次跑完全部确定性检查，报告写到 `.storywork/audit.json`，findings 每项带 severity 和 message。

```powershell
python scripts/story_workspace.py audit <小说目录>
```

检查项覆盖这几类。

- 正文文件摘要与账本完整性。
- 账本记为已接受、磁盘上却找不到的正文。
- 正文目录里没写进账本的孤儿章节。
- 悬置超过 `--setup-age`（默认 30 章）的伏笔。
- 角色年龄倒退，同一时刻出现在两个地点，同一件东西同时有两个主人。
- 角色死亡之后还在发生的事件。

分卷和全书的语义审稿要拆成批次交给人读。

```powershell
python scripts/story_workspace.py audit-pack <小说目录> --scope volume --from-chapter 1 --to-chapter 30 --batch-size 4
python scripts/story_workspace.py audit-submit <小说目录> --audit <audit-id> --batch 1 --findings findings.json
python scripts/story_workspace.py audit-finalize <小说目录> --audit <audit-id>
```

`audit-pack` 在批次旁边写一份有界的共享 `memory.md`，各批次不再重复嵌全量快照。每批开工前先读它，再核对批次里记录的 SHA-256。压缩报告提示漏了关键项时，改用定向检索或完整 snapshot 补查。findings 的字段是 `category`、`severity`、`chapter`、`evidence`、`message`，类别取 canon、chronology、character、setup、structure、prose。跨批次的问题记在靠后的那批里，并列出 `related_chapters`。结论分成 error、risk、intentional 三档，作者故意留的含糊不要自动改。

## 命令一览

`--help` 里 25 个子命令。

| 组 | 命令 |
|---|---|
| 项目与账本 | `init` `record` `adopt` `rebuild` `chapter-repair` |
| 索引与检索 | `index` `query` |
| 草稿事务 | `begin` `revise-begin` `mechanical-review` `accept` `recover` `review` |
| 事实提取 | `stage-events` `approve-events` |
| 章纲与节奏 | `plan-set` `outcome-set` `deviation` `pacing` |
| 审计 | `audit` `audit-pack` `audit-submit` `audit-finalize` |
| 备份 | `backup` `verify-backup` |

`review` 是 `mechanical-review` 的兼容别名，跑同样的确定性检查。

## 确认令牌

会改状态的操作各要一个不同的确认值。

| 操作 | 确认值 |
|---|---|
| 收编已有章节 | `ADOPT` |
| 修复中断事务 | `RECOVER` |
| 批准第 N 章计划 | `PLAN-N` |
| 收敛某章的重复接受记录 | `REPAIR-N` |
| 接受草稿、实际结果或事实提案 | 对应的 session id |

## 备份与数据边界

```powershell
python scripts/story_workspace.py backup <小说目录> --archive <备份文件.sfs.zip>
python scripts/story_workspace.py verify-backup --archive <备份文件.sfs.zip>
```

旧的 `backup --out` 和位置参数写法仍然认。备份包里装计划、实际结果、偏差报告和已生成的 `pacing.json`，SQLite 与 HNSW 索引属于可重建数据，不进包。正文、manifest 和事件账本才是可移植的事实来源。

公开仓库不应包含小说正文、`.storywork/`、作者语料、索引、上下文包或个人备份。

## 文风集成

作者启发型文风不在这个仓库里。需要文风分析或风格包时，单独安装 [style-writer](https://github.com/dyf1234567/style-writer)。缺它不影响连续性、检索、审计和备份。

## 测试

```powershell
python -m unittest discover -s scripts -p "test_*.py"
```

本机 31 个用例，4.5 秒跑完，1 个跳过，跳过的只有需要 hnswlib 那条。GitHub Actions 在 windows-latest、Python 3.12 上跑同一批命令，`main` 最近一次 run 为 success。

## 许可证

仓库里的 Skill 代码与随附文档使用 [MIT License](LICENSE)。许可证不覆盖用户小说正文、第三方作者原文、风格语料、参考语料、生成的向量数据库，以及其他没进本仓库的内容。
