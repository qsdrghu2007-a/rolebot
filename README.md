# RoleBot — Telegram 角色扮演聊天机器人 <br><sub>Telegram Roleplay Chatbot</sub>

一个基于 OpenAI 兼容 LLM 的 Telegram 角色扮演框架。自定义人格、长期记忆、5维心情系统、世界书、对话编辑、日记总结 —— 配置即用。

*A Telegram roleplay chatbot powered by any OpenAI-compatible LLM. Custom persona, long-term memory, 5D mood engine, world book, conversation editing, diary summaries — zero code required.*

支持 DeepSeek / OpenAI / Groq / 本地模型（Ollama / vLLM / LM Studio）。

---

## 快速开始 · Quick Start

### 1. 安装依赖 · Install

```bash
pip install -r requirements.txt
```

### 2. 配置 · Configure

**推荐 / Recommended — 交互式引导 / Interactive Setup：**

```bash
python setup.py
```
支持中英双语 · *Bilingual setup wizard (中文 / English)*

**手动 / Manual：**

复制 `config.example.yaml` 为 `config.yaml`，编辑 `llm` 部分填入 API Key / base_url / model，再编辑 `digital_person/persona_final-d.md` 编写你的角色设定。

*Copy `config.example.yaml` to `config.yaml`, fill in your `llm` settings, then edit `digital_person/persona_final-d.md` to define your character.*

### 3. 运行 · Run

```bash
python main.py
```

---

## 命令 · Commands

| 命令 | 说明 |
|------|------|
| `/suggest` | 并行 3 路 LLM 生成候选**用户**回复 · *Generate 3 candidate replies for you* |
| `/start` | 开始使用 · *Start the bot* |
| `/mood` | 查看当前心情（含进度条） · *View mood with progress bars* |
| `/continue` | 独自继续生成下一条 · *Bot continues on its own* |
| `/regenerate` | 重新生成上轮回复 · *Regenerate last reply* |
| `/language` | 切换语言（中文/English） · *Switch language (中文/English)* |
| `/clear` | 清除对话历史（可选 compact） · *Clear history (with optional summary)* |
| `/clear_memories` | 清除所有长期记忆 · *Clear all long-term memories* |
| `/list_memories` | 列出长期记忆 · *List memories* |
| `/delete_memory <N>` | 删除指定记忆 · *Delete a memory by number* |
| `/thinking` | 思考模式 high/max/off · *Set thinking intensity* |
| `/compact` | 日记视角总结对话 · *Summarize chat as a diary entry* |
| `/compact list` | 翻页查看历史日记 · *Browse diary history* |
| `/help` | 显示帮助 · *Show help* |
| `/status` | 4-tab 仪表盘 · *Status dashboard* |

---

## 支持的 LLM · Supported Providers

**任何 OpenAI 兼容 API 均可使用**，以下是常见配置示例。*Any OpenAI-compatible API works. Below are common examples.*

修改 `config.yaml` 中的 `llm` 部分即可切换。*Just change the `llm` section in `config.yaml`.*

| Provider | `base_url` | `model` |
|----------|-----------|---------|
| **DeepSeek** | `https://api.deepseek.com` | `deepseek-v4-flash` |
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| **Ollama** | `http://localhost:11434/v1` | `qwen2.5:14b` |
| **任意兼容服务** · *Any compatible API* | `https://你的服务地址` | `你的模型名` |

> ollama 不需要真实 API Key，填任意值即可。*For Ollama, use any string as api_key (e.g. `ollama`).*

---

## 核心功能 · Core Features

| 功能 Feature | 说明 Description |
|---|---|
| **长期记忆** Long-term memory | AI 自动判断值得记住的内容（阈值 ≥ 7） · *Auto-judges what's worth remembering* |
| **心情系统** Mood engine | 5 维情绪（开心/想念/精力/生气/性欲）含时间衰减 · *5D mood with time-based decay* |
| **文爱检测** Arousal state machine | 独立判断器 + 2-in/3-out 状态机 + 消息级快照 · *Separate judge + state machine + per-message snapshots* |
| **编辑功能** Message editing | 回复即可编辑，后续自动重生成 + 状态机快照回滚 · *Reply to edit, auto-regenerate, state machine rolls back* |
| **世界书** World book | 关键词触发角色背景记忆 · *Keyword-triggered character lore injection* |
| **日记总结** Diary summaries | LLM 从角色视角写日记（`/compact`） · *Bot writes diary entries from character POV* |
| **思考模式** Thinking mode | high / max / off 三档 · *Three intensity levels* |
| **双语支持** Bilingual | `/language` 切换中英文界面 · *Switch between Chinese/English UI* |
| **KV 缓存优化** Cache optimization | persona 固定在 messages[0] 保证高命中率 · *Fixed persona prefix for high KV cache hit rate* |

---

## 自定义角色 · Custom Character

### 人格文件 · Persona File

`digital_person/persona_final-d.md` — 包含以下部分 / *contains these sections*：

- **基本信息** · *Basic info*：名字、年龄、性格 · *name, age, personality*
- **语言风格** · *Speech style*：短句、动作 () 表示、语气词 · *short sentences, actions in (), filler words*
- **核心规则** · *Core rules*：角色一致性、情感真实 · *stay in character, authentic emotions*
- **背景故事** · *Backstory*：经历、创伤、成就 · *history, traumas, achievements*
- **兴趣爱好** · *Hobbies*
- **与用户的关系** · *Relationship with user*

> 写得越详细，角色辨识度越高。建议至少 200 字。*The more detailed, the better. 200+ characters recommended.*

### 世界书 · World Book

`digital_person/world_book.json` — 关键词触发的背景记忆 / *keyword-triggered lore*：

```json
[
  {
    "keywords": ["生日", "birthday"],
    "content": "用户的生日是5月22日 / User's birthday is May 22",
    "priority": 5
  }
]
```

---

## 文件说明 · Project Structure

```
├── setup.py                  # 双语配置引导 · Bilingual setup wizard
├── main.py                   # 入口 · Entry point
├── telegram_bot.py           # 机器人核心 · Bot core
├── llm_client.py             # LLM API 客户端 · OpenAI-compatible client
├── prompt_engine.py          # 提示词引擎 · Prompt engine (KV cache optimized)
├── memory_db.py              # SQLite 数据库 · Database
├── ai_memory_manager.py      # AI 记忆管理 + 性欲判断 · Memory + arousal judge
├── world_book.py             # 世界书 · World book matcher
├── config.example.yaml       # 配置模板 · Config template
├── digital_person/
│   ├── persona_final-d.md    # 角色人格设定 · Character persona
│   └── world_book.json       # 世界书记忆 · World book entries
├── start_bot.bat / start.ps1 # 启动脚本 · Start scripts
└── data/                     # 持久化数据 · Persistent data
```

---

## 注意事项 · Notes

- 需要能访问 Telegram API 和你的 LLM 服务地址 · *Requires access to Telegram API and your LLM endpoint*
- API 密钥请妥善保管，勿提交到 Git（`.gitignore` 已排除 `config.yaml`） · *Keep API keys private — `config.yaml` is gitignored*
- `memory.db` 包含所有对话历史，注意隐私 · *memory.db stores all conversations — handle with care*

## 更多文档 · More Docs

- [维护指南（中文）](维护指南.md)
- [Maintenance Guide (English)](MAINTENANCE.md)

---

`telegram-bot` `chatbot` `roleplay` `character-ai` `ai-girlfriend` `ai-companion` `virtual-character` `persona` `personality` `llm` `openai-compatible` `deepseek` `gpt` `local-llm` `ollama` `mood-system` `long-term-memory` `world-book` `lorebook` `diary` `sqlite` `python` `self-hosted` `bilingual` `中文` `角色扮演` `虚拟女友` `AI伙伴` `心情系统` `长期记忆` `世界书` `日记总结`
