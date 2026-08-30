# Serial Fiction Studio

面向 Codex 的中文长篇小说工作流技能。它把小说正文与可重建的项目记忆分开管理，用事件账本、快照、检索、草稿事务和人工检查点维持人物、时间线、设定与伏笔的一致性。

## 能做什么

- 接管已有小说或初始化新项目
- 维护追加式事实账本和当前状态快照
- 使用 SQLite FTS5 检索；可选接入本地 embedding 与 HNSW 语义索引
- 生成紧凑写作上下文，而不是把整本小说塞进提示词
- 通过 `begin → review → accept` 草稿事务避免未经确认就改写正文
- 提取章节事件并经人工批准后写入 canon
- 管理轻量章纲、场景结果、节奏追踪和计划偏差
- 执行章节、分卷及全书审计
- 提供 Codex 主技能定义和 Qoder 只读审稿 Agent 定义
- 创建和校验可移植项目备份

## 安装

把整个目录复制或克隆到 Codex skills 目录：

```powershell
git clone https://github.com/dyf1234567/serial-fiction-studio.git "$env:USERPROFILE\.codex\skills\serial-fiction-studio"
```

重启或刷新 Codex 后，可直接说：

```text
$serial-fiction-studio 继续写当前小说下一章，保持人物、时间线和伏笔一致。
```

技能会按任务读取 `references/` 中相应工作流。确定性项目操作由 `scripts/story_workspace.py` 完成：

```powershell
python scripts/story_workspace.py --help
```

## 可选语义检索

基础模式只依赖 Python 标准库与 SQLite FTS5。安装以下依赖后可启用本地 HNSW 向量索引：

```powershell
pip install -r scripts/requirements-optional.txt
```

Embedding 服务是可选外部能力。项目可以只用 FTS5，也可以连接本地 Ollama 等兼容方案；索引可随时从正文重建，不应提交到 Git。

## Qoder 多 Agent

`adapters/qoder/agents/` 包含五个只读审稿角色：连续性、人物与因果、结构与节奏、文风、重大剧情红队。将这些定义按 Qoder 的 Agent 配置方式导入即可。它们只返回带证据的审稿意见；主 Agent 仍是唯一写作者和状态修改者。

## 数据边界

本仓库只发布技能本身，不包含：

- 小说正文或用户项目
- `.storywork/` 运行状态
- 作者语料和风格包
- SQLite、HNSW 或 embedding 索引
- 自动备份和生成的上下文包

详见 [PROVENANCE.md](PROVENANCE.md)。公开可见不等于获得使用、修改或再分发授权；本仓库当前未附加开源许可证。

## 验证

```powershell
python -m unittest discover -s scripts -p "test_*.py"
```

