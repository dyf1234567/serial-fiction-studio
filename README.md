# 连载小说工作室（Serial Fiction Studio）

这是一个面向 Codex 的中文长篇小说工作流 Skill。它把正文与可重建的项目记忆分开管理，通过事件账本、状态快照、检索、草稿事务和人工确认点，降低人物、时间线、设定与伏笔在长篇创作中的漂移。

## 能力边界

Skill 自身负责确定性工作：项目状态、事实账本、词法与向量索引、上下文组装、草稿事务、机械检查、计划偏差、审计和备份。

写作、人物动机判断、语义审稿和事实提取由 Codex、Qoder 等宿主模型完成。`adapters/qoder/agents/` 中的文件是只读审稿角色定义，需要由 Qoder 加载后才会成为实际 Agent；它们不是独立运行的后台程序。`stage-events` 只接收并校验宿主模型产生的 JSON，不自行调用生成模型。

## 主要功能

- 初始化新项目或接管已有小说
- 维护追加式 canon 账本与当前状态快照
- 使用 FTS5、普通词法扫描和可选 embedding 检索
- 生成紧凑写作上下文，避免每次加载整本小说
- 通过 `begin → mechanical-review → accept` 管理草稿事务
- 经人工批准后提取章节事实、时间线与伏笔变化
- 管理轻量章纲、场景结果、节奏和计划偏差
- 执行章节、分卷与全书审计
- 创建并校验可移植备份

## 安装

### Codex

```powershell
git clone https://github.com/dyf1234567/serial-fiction-studio.git "$env:USERPROFILE\.codex\skills\serial-fiction-studio"
```

重启或刷新 Codex 后可直接说：

```text
$serial-fiction-studio 继续写当前小说下一章，保持人物、时间线和伏笔一致。
```

`agents/openai.yaml` 是 Codex 用来展示 Skill 名称、简介和默认调用提示的界面元数据，不是可执行 Agent，也不需要用户单独运行。

### Qoder

把整个仓库复制到 Qoder 可读取的 Skill 目录；如果只需要多角色审稿，可将 `adapters/qoder/agents/` 中所需角色复制到小说项目的 `.qoder/agents/`（项目级）或 `~/.qoder/agents/`（用户级），然后执行 `/agents reload`。这些定义均为只读审稿角色，协调者仍是唯一写作者和状态修改者。

## 检索模式

默认索引不调用 embedding：

```powershell
python scripts/story_workspace.py index <小说目录> --embeddings none
```

需要同时索引设定集、旧稿或外部参考语料时，可重复使用 `--source`：

```powershell
python scripts/story_workspace.py index <小说目录> `
  --source <设定集目录> `
  --source <参考语料目录> `
  --embeddings none
```

首次指定的来源会写入项目 manifest。相对路径在本次命令中按当前工作目录解析后保存为稳定路径；以后可省略 `--source`。若已保存的来源不存在，索引会报错并保留旧索引，不会静默清空。

优先使用 SQLite FTS5。若当前 Python 的 SQLite 不包含 FTS5，Skill 会自动降级为普通词法扫描，并在结果中返回 `lexical_backend: scan`。

启用语义检索：

```powershell
python scripts/story_workspace.py index <小说目录> `
  --embeddings ollama `
  --model bge-m3 `
  --endpoint http://127.0.0.1:11434 `
  --ann auto
```

当前 embedding 协议是 Ollama `/api/embed`。`--endpoint` 可以指向本机或远程 Ollama，但不是通用云模型 API。`--ann auto` 在安装 `numpy` 和 `hnswlib` 时使用 HNSW，否则使用精确余弦检索。

查询示例：

```powershell
python scripts/story_workspace.py query <小说目录> "谁拿走了银戒" `
  --lexical-weight 0.65 `
  --semantic-weight 0.35
```

查询结果会明确返回检索模式、请求权重、实际权重、降级警告和命中内容。如果没有向量或 Ollama 暂时离线，语义权重会自动转交给词法检索，不再静默失效。

如果索引元数据与实际 SQLite 表不一致，查询会明确返回降级或 `index-unavailable`，并提示重新运行 `index`，不会把空结果伪报为正常 FTS5 查询。

## 审稿说明

```powershell
python scripts/story_workspace.py mechanical-review <小说目录> `
  --session <会话编号> `
  --draft <草稿文件>
```

`mechanical-review` 只检查篇幅、禁用短语、冻结计划是否被修改、计划约束和重复句，不包含人物、因果、连续性或文风的语义判断。旧命令 `review` 仍作为兼容别名保留。

需要语义审稿时，应由宿主模型阅读草稿；用户明确要求多 Agent 时，可加载连续性、人物与因果、结构与节奏、文风和重大剧情红队等只读角色。

## 可选文风集成

作者启发型文风不包含在本仓库中。需要文风分析或风格包时，可单独安装 [style-writer](https://github.com/dyf1234567/style-writer)。缺少它不会影响本 Skill 的连续性、检索、审计与备份功能。

## 确认令牌

不同写操作使用不同确认值，以降低误操作风险：

| 操作 | 确认值 |
|---|---|
| 收编已有章节 | `ADOPT` |
| 修复中断事务 | `RECOVER` |
| 批准第 N 章计划 | `PLAN-N` |
| 接受草稿、实际结果或事实提案 | 对应 session id |

## 备份

新命令统一使用 `--archive`：

```powershell
python scripts/story_workspace.py backup <小说目录> --archive <备份文件.sfs.zip>
python scripts/story_workspace.py verify-backup --archive <备份文件.sfs.zip>
```

旧的 `backup --out` 和位置参数形式仍可使用。

备份包含计划、实际结果、偏差报告和已生成的 `pacing.json`；SQLite/HNSW 检索索引仍属于可重建数据，不进入备份。

## 数据边界

公开仓库不应包含小说正文、`.storywork/`、作者语料、SQLite/HNSW 索引、上下文包或个人备份。索引属于可重建数据；正文、manifest 和事件账本才是可移植事实来源。

## 许可证

本仓库中的 Skill 代码与随附文档使用 [MIT License](LICENSE)。该许可证不覆盖用户小说正文、第三方作者原文、风格语料、参考语料、生成的向量数据库或其他未包含在本仓库中的内容。

## 验证

```powershell
python -m unittest discover -s scripts -p "test_*.py"
```
