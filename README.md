# Telegram 角色扮演聊天机器人

基于 OpenAI 兼容 API 的通用角色扮演聊天机器人框架，支持自定义人格、长期记忆、心情系统。

支持 DeepSeek / OpenAI / Groq / 本地模型（Ollama / vLLM / LM Studio）等任何兼容接口。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

**推荐方式 — 交互式引导：**

```bash
python setup.py
```

按提示依次输入 API Key、API 地址、模型名称、Telegram Bot Token，并编辑你的角色人格文件。

**手动方式：**

复制 `config.example.yaml` 为 `config.yaml`，编辑 `llm` 部分填入 API Key / base_url / model，再编辑 `digital_person/persona_final-d.md` 编写你的角色设定。

### 3. 运行

```bash
python main.py
```

## 全部命令

| 命令 | 说明 |
|------|------|
| `/suggest` | 并行 3 路 LLM 生成候选**用户**回复，按钮选择 |
| `/start` | 开始使用 |
| `/mood` | 查看机器人当前心情（含进度条） |
| `/continue` | 机器人独自继续生成下一条回复 |
| `/regenerate` | 重新生成上一轮回复并删除原回复 |
| `/clear` | 清除当前对话历史（提供"总结并清除"按钮，自动 compact 后清除） |
| `/clear_memories` | 清除所有长期记忆（需二次确认） |
| `/list_memories` | 列出长期记忆 |
| `/delete_memory <N>` | 删除指定记忆（无参数显示按钮翻页版） |
| `/thinking` | 设置思考模式（无参数显示按钮版，high/max/off） |
| `/compact` | 日记视角总结自上次 clear 以来的对话 |
| `/compact list` | 翻页查看历史日记（点击标题查看详情，可删除） |
| `/help` | 显示帮助信息 |
| `/status` | 4-tab 仪表盘（运行概况 / 数据统计 / 最近对话 / 心情） |

## 自定义角色

### 人格文件

`digital_person/persona_final-d.md` — 编写你的角色设定，包括：
- 基本信息（姓名、年龄、性格）
- 语言风格（短句、动作()表示、语气词）
- 核心规则（角色一致性、情感真实）
- 背景故事、兴趣爱好
- 与用户的关系

### 世界书

`digital_person/world_book.json` — 关键词触发的背景记忆，例如：
```json
[
  {
    "keywords": ["生日", "纪念日"],
    "content": "用户的生日是5月22日",
    "priority": 5
  }
]
```

## 支持的 LLM 服务商

`config.yaml` 中修改 `llm` 部分即可切换：

**DeepSeek：**
```yaml
llm:
  api_key: "sk-xxxxx"
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
```

**OpenAI：**
```yaml
llm:
  api_key: "sk-xxxxx"
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
```

**Groq：**
```yaml
llm:
  api_key: "gsk_xxxxx"
  base_url: "https://api.groq.com/openai/v1"
  model: "llama-3.3-70b-versatile"
```

**本地模型（Ollama）：**
```yaml
llm:
  api_key: "ollama"          # Ollama 不需要真实 key，填任意值即可
  base_url: "http://localhost:11434/v1"
  model: "qwen2.5:14b"
```

## 核心功能

- **长期记忆**：AI 自动判断值得记住的内容（重要性阈值 ≥ 7）
- **心情系统**：5 维情绪（开心/想念/精力/生气/性欲），懒加载时间衰减
- **文爱检测**：独立 ArousalJudge API，状态机自主进入/退出
- **编辑功能**：回复消息直接编辑，后续对话自动重新生成；状态机快照自动回滚
- **思考模式**：high / max / off 三档，按钮切换（需模型支持）
- **KV 缓存优化**：persona 固定在 messages[0] 保证缓存命中

### 日记总结（Compact）
- `/compact` — LLM 读取自上次 clear 以来的所有对话，从角色视角写一篇日记（100-300 字）
- `/compact list` — 翻页按钮列表，点击查看详情，可删除
- `/clear` 命令集成了自动 compact 提示

### 升级版 /status 仪表盘
- 4 个切换 tab：运行概况 / 数据统计 / 最近对话 / 心情
- 运行概况：运行时间、今日/总计消息、成功率、**平均响应时间**
- 心情：5 维进度条 + 文爱状态

## 文件说明

```
├── setup.py                  # 首次配置引导
├── main.py                   # 入口
├── telegram_bot.py           # Telegram 机器人核心
├── llm_client.py             # LLM API 客户端（OpenAI 兼容）
├── prompt_engine.py          # 提示词引擎（KV 缓存优化）
├── memory_db.py              # SQLite 数据库
├── ai_memory_manager.py      # AI 记忆管理 + 性欲判断
├── world_book.py             # 世界书关键词匹配
├── config.yaml               # 配置文件
├── config.example.yaml       # 配置模板
├── digital_person/
│   ├── persona_final-d.md    # 角色人格设定（可自定义）
│   └── world_book.json       # 世界书记忆条目
├── start_bot.bat / start.ps1 # 启动脚本
└── data/                     # 持久化数据
```

## 注意事项

- 机器人需要能访问 Telegram API 和你的 LLM 服务地址
- 配置文件中的 API 密钥请妥善保管，不要提交到 Git
- `memory.db` 存储所有对话历史，请注意隐私保护
