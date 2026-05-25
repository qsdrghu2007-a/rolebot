#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Chatbot — First-time Setup Wizard
Telegram 聊天机器人 — 首次配置引导

Run this script to interactively configure your bot.
运行此脚本交互式配置你的机器人。
"""

import os
import sys
import yaml

CONFIG_PATH = "config.yaml"
EXAMPLE_PATH = "config.example.yaml"
PERSONA_PATH = "digital_person/persona_final-d.md"

# ── Translations ──────────────────────────────────────────────
T = {}

T["zh"] = {
    "banner":          "  Telegram 角色扮演机器人 — 配置引导",
    "banner_en":       "  Telegram Roleplay Bot — Setup Wizard",
    "detect_need":     "config.yaml 已存在且已配置。是否重新配置？(y/N): ",
    "skip":            "跳过配置。运行 python main.py 启动机器人。",
    "intro":           "接下来需要配置必需信息和若干可选信息。\n",
    "step1_title":     "【第 1 步】LLM API 配置",
    "step1_desc":      "本机器人支持任何 OpenAI 兼容 API，包括：",
    "step1_providers": "  - DeepSeek:  https://platform.deepseek.com/api_keys\n  - OpenAI:    https://platform.openai.com/api-keys\n  - Groq:      https://console.groq.com/keys\n  - 本地模型 (Ollama / vLLM / LM Studio 等)",
    "api_key_prompt":  "  API Key",
    "base_url_prompt": "  API 地址",
    "model_prompt":    "  模型名称",
    "model_ref":       "  常用模型参考:",
    "model_list":      "    DeepSeek:  deepseek-chat / deepseek-v4-flash / deepseek-reasoner\n    OpenAI:    gpt-4o / gpt-4o-mini\n    Groq:      llama-3.3-70b-versatile / mixtral-8x7b-32768\n    本地:      任意模型名（Ollama 已有模型或 vLLM 部署的模型）",
    "step2_title":     "【第 2 步】Telegram Bot 配置",
    "step2_desc":      "  1. 在 Telegram 搜索 @BotFather\n  2. 发送 /newbot 创建机器人\n  3. 复制获得的 Bot Token",
    "bot_token_prompt":"  Bot Token",
    "admin_prompt":    "  管理员用户ID（可选，多个用逗号分隔，向 @userinfobot 获取）: ",
    "step3_title":     "【第 3 步】角色人格设定",
    "step3_desc1":     "  这是最重要的一步！人格文件决定了机器人的说话风格、性格和背景。",
    "step3_desc2":     "  人格文件位置: {path}",
    "step3_sections":  "  文件包含以下部分，请按你的角色逐一填写：",
    "step3_info":      "  ┌─ 基本信息 ─────────────────────────────\n  │ 名字、年龄、性别、职业、性格特点\n  │ 例如: 名字：小雪 / 年龄：19岁 / 性格：温柔害羞，偶尔傲娇",
    "step3_style":     "  ├─ 语言风格 ─────────────────────────────\n  │ 说话的句式、习惯用词、语气特征\n  │ 例如: 句尾加\"~\"、爱用拟声词、动作用()包裹",
    "step3_rules":     "  ├─ 核心规则 ─────────────────────────────\n  │ 角色的行为底线和互动原则\n  │ 例如: 不跳出角色、生气时话变少、被夸会害羞",
    "step3_background":"  ├─ 背景故事 ─────────────────────────────\n  │ 角色的经历、创伤、成就、重要记忆\n  │ 例如: 从小在孤儿院长大，后来被收养，性格因此独立又缺爱",
    "step3_hobbies":   "  ├─ 兴趣爱好 ─────────────────────────────\n  │ 喜欢什么、讨厌什么、擅长什么\n  │ 例如: 喜欢下雨天、爱喝奶茶、讨厌香菜、擅长画画",
    "step3_relation":  "  ├─ 与用户的关系 ─────────────────────────\n  │ 角色和聊天对象是什么关系\n  │ 例如: 恋人是青梅竹马、朋友是大学同学、师生关系",
    "step3_examples":  "  └─ 说话模板示例 ─────────────────────────\n     不同情绪下的典型回复，帮助AI理解角色语气\n     例如: 生气时→（扭头）不理你了！哼",
    "step3_tip1":      "  [提示] 越详细越好！AI会根据这些设定来扮演角色。",
    "step3_tip2":      "  [提示] 建议至少写200字以上，才能让角色有辨识度。",
    "persona_exists":  "  当前人格文件已有 {size} 字节内容",
    "persona_edit_ask":"  是否现在编辑人格文件？(y/N): ",
    "persona_small":   "  人格文件是模板，只有 {size} 字节，需要填写内容",
    "persona_open_ask":"  是否现在打开编辑？(y/N): ",
    "persona_done":    "  编辑完成后按回车继续...",
    "persona_missing": "  [警告] 未找到人格文件 {path}",
    "persona_later":   "  [提示] 后续随时可用任意文本编辑器修改: {path}",
    "step4_title":     "【第 4 步】世界书（可选）",
    "step4_desc":      "  世界书记忆文件: {path}",
    "step4_detail":    "  你可以编辑此文件添加角色的背景回忆、特殊设定等",
    "step4_ask":       "  是否查看/编辑？(y/N): ",
    "step4_done":      "  编辑完成后按回车继续...",
    "step4_missing":   "  [提示] 没有世界书文件，已跳过",
    "step5_title":     "【第 5 步】访问控制",
    "step5_prompt":    "  白名单用户ID（可选，多个用逗号分隔，留空=所有人可用）: ",
    "done_title":      "【完成】正在写入配置...",
    "done_config":     "  配置已写入 {path}",
    "done_final":      "  配置完成！运行 python main.py 启动机器人",
    "error_required":  "[错误] 此项不能为空",
    "error_apikey":    "API Key 长度太短，请检查",
    "error_token_fmt": "Bot Token 格式应为 数字:字母数字 的形式",
    "error_token_num": "Bot Token 前半部分应为纯数字",
    "cancelled":       "已取消。",
}

T["en"] = {
    "banner":          "  Telegram Roleplay Bot — Setup Wizard",
    "banner_en":       "",
    "detect_need":     "config.yaml exists and appears configured. Reconfigure? (y/N): ",
    "skip":            "Skipping setup. Run python main.py to start the bot.",
    "intro":           "You will now configure the required and optional settings.\n",
    "step1_title":     "[Step 1] LLM API Configuration",
    "step1_desc":      "This bot supports any OpenAI-compatible API:",
    "step1_providers": "  - DeepSeek:  https://platform.deepseek.com/api_keys\n  - OpenAI:    https://platform.openai.com/api-keys\n  - Groq:      https://console.groq.com/keys\n  - Local (Ollama / vLLM / LM Studio etc.)",
    "api_key_prompt":  "  API Key",
    "base_url_prompt": "  API Base URL",
    "model_prompt":    "  Model name",
    "model_ref":       "  Popular models:",
    "model_list":      "    DeepSeek:  deepseek-chat / deepseek-v4-flash / deepseek-reasoner\n    OpenAI:    gpt-4o / gpt-4o-mini\n    Groq:      llama-3.3-70b-versatile / mixtral-8x7b-32768\n    Local:     any model name (existing Ollama model or vLLM deployment)",
    "step2_title":     "[Step 2] Telegram Bot Configuration",
    "step2_desc":      "  1. Search @BotFather on Telegram\n  2. Send /newbot to create a bot\n  3. Copy the Bot Token you receive",
    "bot_token_prompt":"  Bot Token",
    "admin_prompt":    "  Admin user ID (optional, comma-separated, get from @userinfobot): ",
    "step3_title":     "[Step 3] Character Persona",
    "step3_desc1":     "  This is the most important step! The persona file defines the bot's speech style, personality, and background.",
    "step3_desc2":     "  Persona file location: {path}",
    "step3_sections":  "  The file contains the following sections — fill them in for your character:",
    "step3_info":      "  ┌─ Basic Info ────────────────────────────\n  │ Name, age, gender, occupation, personality\n  │ e.g. Name: Luna / Age: 19 / Personality: gentle, shy, occasionally tsundere",
    "step3_style":     "  ├─ Speech Style ──────────────────────────\n  │ Sentence patterns, filler words, tone\n  │ e.g. Ends sentences with \"~\", uses onomatopoeia, actions in ()",
    "step3_rules":     "  ├─ Core Rules ────────────────────────────\n  │ Behavioral boundaries and interaction principles\n  │ e.g. Stays in character, quieter when angry, blushes when praised",
    "step3_background":"  ├─ Backstory ──────────────────────────────\n  │ Character history, traumas, achievements, key memories\n  │ e.g. Grew up in an orphanage, adopted later, independent but craves affection",
    "step3_hobbies":   "  ├─ Interests & Hobbies ───────────────────\n  │ Likes, dislikes, talents\n  │ e.g. Loves rainy days, addicted to milk tea, hates cilantro, good at drawing",
    "step3_relation":  "  ├─ Relationship with User ────────────────\n  │ What's the relationship between the character and you\n  │ e.g. Childhood sweethearts, college friends, teacher-student",
    "step3_examples":  "  └─ Example Dialogues ─────────────────────\n     Typical replies for different emotions, to help the AI understand tone\n     e.g. When angry → (turns away) Hmph! Not talking to you!",
    "step3_tip1":      "  [Tip] The more detailed, the better! The AI acts based on these settings.",
    "step3_tip2":      "  [Tip] At least 200 characters recommended for a recognizable persona.",
    "persona_exists":  "  Persona file currently has {size} bytes of content",
    "persona_edit_ask":"  Edit the persona file now? (y/N): ",
    "persona_small":   "  Persona file is a template with only {size} bytes — needs content",
    "persona_open_ask":"  Open for editing now? (y/N): ",
    "persona_done":    "  Press Enter after editing to continue...",
    "persona_missing": "  [Warning] Persona file not found: {path}",
    "persona_later":   "  [Tip] You can always edit it later: {path}",
    "step4_title":     "[Step 4] World Book (Optional)",
    "step4_desc":      "  World book file: {path}",
    "step4_detail":    "  Edit this file to add character background memories, special settings, etc.",
    "step4_ask":       "  View / Edit? (y/N): ",
    "step4_done":      "  Press Enter after editing to continue...",
    "step4_missing":   "  [Tip] No world book file found — skipped",
    "step5_title":     "[Step 5] Access Control",
    "step5_prompt":    "  Whitelist user IDs (optional, comma-separated, leave blank = allow all): ",
    "done_title":      "[Done] Writing config...",
    "done_config":     "  Config written to {path}",
    "done_final":      "  Setup complete! Run python main.py to start the bot",
    "error_required":  "[Error] This field cannot be empty",
    "error_apikey":    "API key is too short, please check",
    "error_token_fmt": "Bot Token should be in format: digits:alphanumeric",
    "error_token_num": "Bot Token first part should be digits only",
    "cancelled":       "Cancelled.",
}


def _(key, **kwargs):
    s = T[_lang].get(key, key)
    if kwargs:
        s = s.format(**kwargs)
    return s


_lang = "zh"


def print_banner():
    print("=" * 55)
    print(_("banner"))
    if _("banner_en"):
        print(_("banner_en"))
    print("=" * 55)
    print()


def input_required(prompt_key, default="", validator=None):
    while True:
        prompt = _(prompt_key)
        if default:
            val = input(f"{prompt} [{default}]: ").strip()
            if not val:
                return default
        else:
            val = input(f"{prompt}: ").strip()
        if not val:
            print(f"  {_('error_required')}")
            continue
        if validator:
            ok, msg = validator(val)
            if not ok:
                print(f"  {msg}")
                continue
        return val


def validate_api_key(val):
    if len(val) < 10:
        return False, _("error_apikey")
    return True, ""


def validate_bot_token(val):
    parts = val.split(":")
    if len(parts) != 2:
        return False, _("error_token_fmt")
    if not parts[0].isdigit():
        return False, _("error_token_num")
    return True, ""


def load_example_config():
    if os.path.exists(EXAMPLE_PATH):
        with open(EXAMPLE_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "llm": {"api_key": "", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
        "telegram": {"bot_token": "", "allowed_user_ids": [], "enable_group_chat": False,
                     "admin_user_ids": [], "connect_timeout": 30, "read_timeout": 30},
        "memory": {"db_path": "memory.db", "max_history": 150, "max_tokens": 16000},
        "prompt": {"max_prompt_length": 10000, "include_recent_messages": 50,
                   "include_memories": 50, "max_world_book_entries": 5},
        "logging": {"level": "INFO", "file": "bot.log"},
        "advanced": {"temperature": 0.78, "max_tokens_per_response": 1024,
                     "retry_attempts": 3, "timeout_seconds": 30},
    }


def choose_language():
    global _lang
    print("=" * 55)
    print("  选择语言 / Choose Language")
    print("=" * 55)
    print()
    print("  [1]  中文")
    print("  [2]  English")
    print()
    while True:
        choice = input("  请选择 / Enter choice (1/2): ").strip()
        if choice == "1":
            _lang = "zh"
            return
        elif choice == "2":
            _lang = "en"
            return
        print("  请输入 1 或 2 / Please enter 1 or 2")


def main():
    choose_language()
    print()
    print_banner()

    config = load_example_config()
    needs_setup = not os.path.exists(CONFIG_PATH)

    if not needs_setup:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f)
            api_key = existing.get("llm", {}).get("api_key", "")
            bot_token = existing.get("telegram", {}).get("bot_token", "")
            if "your-" in api_key or "your-" in bot_token or not api_key or not bot_token:
                needs_setup = True
        except Exception:
            needs_setup = True

    if not needs_setup:
        ans = input(_("detect_need")).strip().lower()
        if ans != 'y':
            print(_("skip"))
            return
        config = load_example_config()
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

    print(_("intro"))

    # ── Step 1: LLM API ──
    print("─" * 40)
    print(_("step1_title"))
    print(_("step1_desc"))
    print(_("step1_providers"))
    print()

    config["llm"]["api_key"] = input_required(
        "api_key_prompt", config["llm"].get("api_key", ""), validate_api_key
    )

    base_url = input(f"  {_('base_url_prompt')} ({_lang == 'zh' and '默认' or 'default'} {config['llm'].get('base_url', '')}): ").strip()
    if base_url:
        config["llm"]["base_url"] = base_url

    model = input(f"  {_('model_prompt')} ({_lang == 'zh' and '默认' or 'default'} {config['llm'].get('model', '')}): ").strip()
    if model:
        config["llm"]["model"] = model

    print()
    print(_("model_ref"))
    print(_("model_list"))

    # ── Step 2: Telegram ──
    print()
    print("─" * 40)
    print(_("step2_title"))
    print(_("step2_desc"))
    config["telegram"]["bot_token"] = input_required(
        "bot_token_prompt", config["telegram"].get("bot_token", ""), validate_bot_token
    )

    admin = input(_("admin_prompt")).strip()
    if admin:
        config["telegram"]["admin_user_ids"] = [int(x.strip()) for x in admin.split(",") if x.strip().isdigit()]

    # ── Step 3: Persona ──
    print()
    print("─" * 40)
    print(_("step3_title"))
    print()
    print(_("step3_desc1"))
    print(_("step3_desc2", path=PERSONA_PATH))
    print()
    print(_("step3_sections"))
    print()
    print(_("step3_info"))
    print()
    print(_("step3_style"))
    print()
    print(_("step3_rules"))
    print()
    print(_("step3_background"))
    print()
    print(_("step3_hobbies"))
    print()
    print(_("step3_relation"))
    print()
    print(_("step3_examples"))
    print()
    print(_("step3_tip1"))
    print(_("step3_tip2"))
    print()

    if os.path.exists(PERSONA_PATH):
        size = os.path.getsize(PERSONA_PATH)
        if size > 200:
            print(_("persona_exists", size=size))
            ans = input(_("persona_edit_ask")).strip().lower()
            if ans == 'y':
                os.startfile(os.path.abspath(PERSONA_PATH))
                print(_("persona_done"))
                input()
        else:
            print(_("persona_small", size=size))
            ans = input(_("persona_open_ask")).strip().lower()
            if ans == 'y':
                os.startfile(os.path.abspath(PERSONA_PATH))
                print(_("persona_done"))
                input()
    else:
        print(_("persona_missing", path=PERSONA_PATH))

    print(_("persona_later", path=os.path.abspath(PERSONA_PATH)))
    print()

    # ── Step 4: World Book ──
    print("─" * 40)
    print(_("step4_title"))
    wb_path = "digital_person/world_book.json"
    if os.path.exists(wb_path):
        print(_("step4_desc", path=wb_path))
        print(_("step4_detail"))
        ans = input(_("step4_ask")).strip().lower()
        if ans == 'y':
            os.startfile(wb_path)
            print(_("step4_done"))
            input()
    else:
        print(_("step4_missing"))
    print()

    # ── Step 5: Access Control ──
    print("─" * 40)
    print(_("step5_title"))
    allowed = input(_("step5_prompt")).strip()
    if allowed:
        config["telegram"]["allowed_user_ids"] = [int(x.strip()) for x in allowed.split(",") if x.strip().isdigit()]
    print()

    # ── Write Config ──
    print("─" * 40)
    print(_("done_title"))
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        comment = {"zh": "# Telegram 角色扮演机器人配置文件\n# 由 setup.py 生成\n\n",
                   "en": "# Telegram Roleplay Bot Configuration\n# Generated by setup.py\n\n"}
        f.write(comment[_lang])
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(_("done_config", path=CONFIG_PATH))
    print()
    print("=" * 55)
    print(_("done_final"))
    print("=" * 55)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{_('cancelled')}")
        sys.exit(0)
