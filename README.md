# Serial Fiction Studio

中文长篇连载小说的连续性管理工具，形态是一个 Agent Skill 加一个 Python 命令行脚本。脚本记账、建索引、组装上下文、做校验；写正文交给 Codex 或 Qoder 的宿主模型。

小说目录本身不受影响。`chapters/` 里就是普通 Markdown，删掉 `.storywork/` 之后稿件照样能读能改，也能直接搬走。

## 环境和依赖

运行 `scripts/story_workspace.py` 只需要 Python 标准库，开发环境是 CPython 3.12。

语义检索另外要一个能访问的 Ollama，协议固定走 `/api/embed`，通用云模型 API 接不上。近似最近邻需要 `numpy` 与 `hnswlib`，清单在 `scripts/requirements-optional.txt`，不装就退回精确余弦检索，语料大了会慢。

示例命令都是 PowerShell。CI 只在 windows-latest 上跑，macOS 和 Linux 没有自动化验证过。

## 谁做什么

`scripts/story_workspace.py` 管项目状态、事实账本、索引、上下文组装、草稿事务、机械检查、计划偏差、审计和备份。正文写作、人物动机判断、语义审稿、以及从已接受章节里提取候选事实，由宿主模型完成。

脚本里没有任何一处调用生成模型。`stage-events` 只是收下并校验宿主产出的 JSON。`adapters/qoder/agents/` 下那五个角色定义是文本文件，宿主加载之后才成为 Agent，它们不会自己跑起来。

## 安装

### Codex

```powershell
git clone https://github.com/dyf1234567/serial-fiction-studio.git "$env:USERPROFILE\.codex\skills\serial-fiction-studio"
```

重启或刷新 Codex 后调用。

```text
$serial-fiction-studio 继续写当前小说下一章，保持人物、时间线和伏笔一致。
```

`agents/openai.yaml` 是给 Codex 界面显示的元数据，没有运行含义。

### Qoder

仓库整个复制到 Qoder 可读取的 Skill 目录。只要多角色审稿的话，把用得到的角色文件复制到小说项目的 `.qoder/agents/`，或者用户级的 `~/.qoder/agents/`，执行 `/agents reload`。这些角色都是只读的。

### 只当命令行工具用

```powershell
python scripts/story_workspace.py --help
```

25 个子命令的参数和默认值都列在里面。输出统一是 JSON，可以重定向，也可以再写脚本解析。

## 跑一遍

新项目先 `init` 建出 `chapters/` 与 `.storywork/`，再跑一次 `index` 把索引库建出来。

```powershell
python scripts/story_workspace.py init D:\novels\well --title 井与戒
python scripts/story_workspace.py index D:\novels\well --embeddings none
```

正文文件名默认 `第{chapter:04d}章.md`。稿件放在别处就用 `--chapters` 指过去，文件名模板在 `.storywork/manifest.json` 里改。手上已经有写完的章节就用 `adopt` 收编，光跑一次只列出它识别到的文件，加 `--apply --confirm ADOPT` 才写账本。

往下开草稿会话，`--chapter` 指定章号，一个 session 服务一章。

```powershell
python scripts/story_workspace.py begin D:\novels\well --chapter 1 --goal "沈砚第一次下井"
```

返回里要用到两个字段。

```text
{
  "session": "20260901-004453-0e512d",
  "context": "D:\\novels\\well\\.storywork\\sessions\\20260901-004453-0e512d\\context.md",
  ...
}
```

`context.md` 就是喂给模型的输入。模型写回来的草稿存成文件，然后三条命令收尾。

```powershell
python scripts/story_workspace.py mechanical-review D:\novels\well --session <session> --draft draft.md
python scripts/story_workspace.py accept D:\novels\well --session <session> --draft draft.md --confirm <session>
python scripts/story_workspace.py index D:\novels\well --embeddings none
```

最后一条 `index` 不能省。`accept` 只把正文落到 `chapters/`，检索库还是接受之前的状态，这时去查新章节里的句子会返回 0 命中，看着像检索坏了，其实是索引没更新。

`mechanical-review` 只做确定性检查。

| code | severity | 触发条件 |
|---|---|---|
| `short-draft` | risk | 正文去掉首尾空白后不足 800 字符 |
| `repeated-sentence` | risk | 同一句话出现两次 |
| `forbidden-phrase` | error | 出现 `predicate` 为 `forbid_phrase` 的已批准决策所登记的内容 |
| `plan-mutated` | error | 会话绑定的章纲版本在会话开始后被原地改过 |
| `plan-constraint` | error 或 risk | 触发章纲约束，硬约束记 error，其余记 risk |

报告末尾一定带 `requires_human_checkpoint: true`。

## 目录结构

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

账本只追加，从不改写已有行，`rebuild` 负责把它归约成快照。六种事件类型（fact、setup、payoff、timeline、decision、chapter）的字段和语义写在 [references/project-model.md](references/project-model.md)。平时最容易用错的是 `decision` 和 `fact`，`decision` 约束作者自己，`fact` 说的是世界里成立的事，两者不能互换。

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

`review` 是 `mechanical-review` 留下的兼容别名。

改状态的操作要确认值，写错就拒绝执行。

| 操作 | 确认值 |
|---|---|
| 收编已有章节 | `ADOPT` |
| 修复中断事务 | `RECOVER` |
| 批准第 N 章计划 | `PLAN-N` |
| 收敛某章的重复接受记录 | `REPAIR-N` |
| 接受草稿、实际结果或事实提案 | 对应的 session id |

## 检索

默认不带向量。

```powershell
python scripts/story_workspace.py index <小说目录> --embeddings none
```

设定集、旧稿、外部参考语料用 `--source` 带上，可以重复写。第一次指定的来源会存进 manifest，之后能省略。相对路径按当次命令的工作目录解析，存下来是稳定路径。已保存的来源找不到时索引直接报错并留着旧索引，报的多半是那次用相对路径写的来源，而这次换过工作目录。

启用语义检索。

```powershell
python scripts/story_workspace.py index <小说目录> `
  --embeddings ollama `
  --model bge-m3 `
  --endpoint http://127.0.0.1:11434 `
  --ann auto
```

查询按 0.65 词法、0.35 语义混合，两个权重都可以调。

```powershell
python scripts/story_workspace.py query <小说目录> "谁拿走了银戒" `
  --lexical-weight 0.65 `
  --semantic-weight 0.35
```

结果里有 `mode`、请求权重、实际权重、降级警告和命中段落。问改写类的问题抬高语义权重，问事实抬高词法权重。

中文连续文本按两个字切词，所以单个汉字在 FTS5 里命中不了。查询只剩一个汉字时脚本改走正文子串兜底，已有索引不用重建，召回范围比二字查询宽。

降级都留了显式记录。

| 情况 | 行为 | 结果字段 |
|---|---|---|
| SQLite 不含 FTS5 | 词法退成普通扫描 | `lexical_backend: scan`，`mode: lexical-scan` |
| 索引无向量，或 Ollama 不可达 | 语义权重转给词法 | `warnings` 加一条，`effective_weights` 跟着变 |
| 索引元数据与实际表不一致 | 拒绝给结果并提示重跑 `index` | `mode: index-unavailable` |

## 改一章已接受的正文

```powershell
python scripts/story_workspace.py revise-begin <小说目录> --chapter 18 --goal "修正时间错误并保留既有结局"
python scripts/story_workspace.py mechanical-review <小说目录> --session <修订会话> --draft <修订稿>
python scripts/story_workspace.py accept <小说目录> --session <修订会话> --draft <修订稿> --confirm <修订会话>
```

不要直接编辑已接受的正文再套用旧 session。`revise-begin` 会同时记下快照里的摘要和文件实测的摘要，接受时文件又变了就拒绝。旧文件留在 `.storywork/revisions/`，新章节事件带 `supersedes` 顶掉旧版本。接受之后受影响的事实要重新提取、重新批准，脚本不替你判断哪条旧事实该撤。

迁移过来的账本偶尔给同一章留下两条当前接受记录。`audit` 会报出冲突的文件名，事件 id 从 `.storywork/snapshot.json` 的 `chapters[]` 里按 `subject` 找，快照过期就先 `rebuild`。

```powershell
python scripts/story_workspace.py chapter-repair <小说目录> --chapter 3 --keep <event-id> --confirm REPAIR-3
```

它追加一条带 `resolves` 的 reconciled 事件，不删任何正文。多出来的那个文件还留在目录里时，下一次 `audit` 会把它报成孤儿文件。

## 提取事实

章节接受后用 `stage-events` 提候选、`approve-events` 批准。引文必须是正文里连续的一段，普通事件凑够 6 个文字或数字，`risk` 标成 high 的要 10 个，单条不超过 300 字符。标点不计入，所以两个字以内的短词和纯标点过不去。这样设计是因为提取环节最容易出的错，就是模型把两句不相邻的话拼成一条设定。

## 审计

```powershell
python scripts/story_workspace.py audit <小说目录>
```

一次跑完全部确定性检查，报告写到 `.storywork/audit.json`，每条 finding 带 `severity` 和 `message`。检查范围包括正文文件摘要与账本是否对得上、账本记为已接受但磁盘上没有的正文、正文目录里没写进账本的孤儿章节、悬置超过 `--setup-age`（默认 30 章）的伏笔、角色年龄倒退、同一时刻出现在两个地点、同一件东西同时有两个主人，以及角色死亡之后还在发生的事件。

分卷和全书的语义审稿要拆批给人读。

```powershell
python scripts/story_workspace.py audit-pack <小说目录> --scope volume --from-chapter 1 --to-chapter 30 --batch-size 4
python scripts/story_workspace.py audit-submit <小说目录> --audit <audit-id> --batch 1 --findings findings.json
python scripts/story_workspace.py audit-finalize <小说目录> --audit <audit-id>
```

`audit-pack` 在批次旁边放一份共享的 `memory.md`，各批不再重复嵌全量快照。每批开工前先读它，再核对批次记录的 SHA-256。findings 字段是 `category`、`severity`、`chapter`、`evidence`、`message`，类别取 canon、chronology、character、setup、structure、prose。跨批次的问题记在靠后的那批，附上 `related_chapters`。结论分 error、risk、intentional 三档，作者故意留的含糊会被判成 intentional，不会被改掉。

## 中断的事务

`accept` 中途失败，或者上一次会话没走完，`.storywork/transactions/` 里会留下一条 `status` 不是 `complete` 的记录。`recover` 不带 `--apply` 时只报它打算做什么，不碰文件。看过输出再加 `--apply --confirm RECOVER`。

它认的动作有 `append-chapter-event`、`finish-pending-copy`、`finish-pending-replace`、`finalize-metadata` 四种，都是补拷贝或者补账本。四条条件都对不上的事务记成 `manual-review`，`reason` 写"文件缺失或摘要不匹配"，`--apply` 会跳过它，返回里的 `manual_review` 给出跳过条数。这种只能自己去比对正文和账本，脚本不猜。

## 备份与隐私边界

```powershell
python scripts/story_workspace.py backup <小说目录> --archive <备份文件.sfs.zip>
python scripts/story_workspace.py verify-backup --archive <备份文件.sfs.zip>
```

早先的 `backup --out` 和位置参数写法还认。备份包里有计划、实际结果、偏差报告和已生成的 `pacing.json`，SQLite 与 HNSW 索引属于可重建数据，不进包。要在机器之间搬项目，带走正文、manifest 和 `ledger.jsonl` 就够了。

`.gitignore` 已经屏蔽 `.storywork/`、`chapters/`、索引文件、压缩包和常见密钥路径。

## 限制

脚本判断不了草稿好不好，也判断不了一个人此刻该不该知道某件事，这些归人和宿主模型。

修订章节后旧事实要重新走一遍提取和批准，账本里不会自动撤销任何记录。

只读审稿角色靠宿主的权限实现约束，属于流程约定，不是操作系统级隔离。宿主没限制住的时候，本工具挡不住。

向量服务只支持 Ollama 的 `/api/embed`。接别的要改 `story_workspace.py` 里 embedding 那一层。

作者启发型文风不在这个仓库，需要文风分析或风格包时单独装 [style-writer](https://github.com/dyf1234567/style-writer)，不装不影响连续性、检索、审计和备份。

## 测试

```powershell
python -m unittest discover -s scripts -p "test_*.py"
```

31 个用例，本机 4.5 秒跑完，跳过 1 个（需要 `hnswlib` 的那条）。`.github/workflows/test.yml` 在 windows-latest、Python 3.12 上跑同一批命令。

上下文包的大小值得单独说一句。预算固定 24000 字符，在一棵 300 章、账本里有 1203 条事实的测试树上，实际产出 14240 字符，记忆段占其中 11691 字符（事实、伏笔、决策合在一起），另外带进 8 段原文。1203 条事实装了 214 条，省略 989 条，省略范围是第 8 至 255 章，`omitted_critical` 为 0。同一份快照连跑两次，`context.md` 的 SHA-256 相同。

## 文档

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

仓库内的 Skill 代码与随附文档使用 [MIT License](LICENSE)。用户小说正文、第三方作者原文、风格语料、参考语料、生成的向量数据库这些没进仓库的内容，不在许可证范围内。
