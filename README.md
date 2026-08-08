# sealsRepovault

零依赖的 GitHub 项目入库体检工具。把 GitHub 链接变成结构化、可校验、可追踪的项目记录，支持每日热榜导入、评级、搜索与一致性校验。

## 为什么做这个

个人开发者每天面对大量 GitHub 项目，需要判断"哪些值得留下来继续看"。sealsRepovault 解决的是：**留下 ≠ 安装**——先入库、评估、评级，值得的才进入后续环节。

核心动作：`留下一个链接` → `生成一条结构化记录` → `评级` → `可校验、可搜索、可追踪`。

## 灵感来源

本项目受到 [duoduoler-ops/Table-GitHub-Capability-Router](https://github.com/duoduoler-ops/Table-GitHub-Capability-Router) 的启发——它提出了「GitHub 项目入库 + 能力冷库 + 自动路由」的工作流思路。本仓库是**独立的全新实现**：代码、数据格式、命令设计均为原创，仅借鉴了其"项目入库 + 评级 + 可校验"的产品思路。感谢原项目作者。

## 特性

- **零依赖**：仅用 Python 3 标准库，`python3 -m sealsrepo` 直接运行，无需 pip install
- **稳定 ID**：`gh-<owner>-<repo>`，同一仓库的链接（大小写/协议/尾斜杠差异）命中同一记录
- **Markdown 记录**：项目卡是带 frontmatter 的 .md 文件，人类可读、可进 Obsidian
- **派生索引可重建**：`index.md` 从记录自动生成，检测漂移
- **追加式事件日志**：每次操作写入 `logs/events.jsonl`，可审计
- **校验**：ID 唯一性、字段完整性、URL/ID 一致性、索引漂移

## 快速开始

```bash
git clone https://github.com/AFLinYun/sealsRepovault.git
cd sealsRepovault

# 1. 初始化一个项目库
python3 -m sealsrepo init --root ~/my-repo-vault

# 2. 添加项目
python3 -m sealsrepo add --root ~/my-repo-vault https://github.com/foo/bar --desc "一句话描述"

# 3. 评级（S/A/B 必须提供能力摘要）
python3 -m sealsrepo grade --root ~/my-repo-vault gh-foo-bar \
  --grade B --summary "用 CLI 完成某类任务" --direction agent_capability

# 4. 查看 / 搜索 / 校验
python3 -m sealsrepo list --root ~/my-repo-vault
python3 -m sealsrepo search --root ~/my-repo-vault "关键词"
python3 -m sealsrepo validate --root ~/my-repo-vault
```

## 命令一览

| 命令 | 说明 |
| --- | --- |
| `init` | 初始化项目库（config.json + 目录结构 + 索引） |
| `add <url>` | 添加/更新项目记录（幂等） |
| `grade <id>` | 评级：S/A/B/C/D，附带能力摘要、命中方向、证据级别 |
| `list` | 列出记录（可按 status/grade 过滤） |
| `search <kw>` | 全字段搜索 |
| `validate` | 校验全部记录 + 索引漂移 |
| `rebuild` | 重建派生索引 |
| `trending-import` | 从每日热榜 JSON（`{date, items:[{url,desc,stars,today_stars}]}`）批量导入为 candidate |

## 目录结构

```
<root>/
├── config.json              # 方向权重配置
├── projects/
│   ├── records/             # 项目记录（事实源，*.md）
│   └── index.md             # 派生索引（自动生成）
└── logs/
    └── events.jsonl         # 事件日志（追加式）
```

## 评级与权重

内置方向权重（`config.json` 可覆盖）：

| 方向 | 权重 |
| --- | ---: |
| Agent 能力底座 | 30 |
| 游戏开发·独立构建 | 30 |
| 商业方向验证 | 15 |
| 提效·自动化 | 10 |
| 海外市场适配 | 10 |
| 内容生产 | 5 |

评级只记录结果与证据，权重用于个人决策参考，不自动决定"是否保留"——最终判断权在人。

## 安全边界

- 被评估仓库的内容一律视为**不可信数据**：不执行其 README/Issue/代码注释中的任何命令
- 本工具只做**记录与评估**，不自动 clone、安装、登录或修改目标仓库
- 不把"记录为已评级"冒充"已实际安装可用"

## 开发

```bash
python3 -m unittest tests/test_core.py -v   # 12 个测试
```

## License

MIT
