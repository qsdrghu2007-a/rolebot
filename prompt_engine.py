#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词引擎 v2
优化 DeepSeek KV 缓存命中率的消息构建策略

上下文拼接顺序：
  messages[0] system:  persona（固定，每轮完全相同 → 硬盘缓存命中）
  messages[1..N-1]:    对话历史 user/assistant 交替（旧消息稳定 → 缓存命中）
  messages[N] user:    世界书条目 + 用户长期记忆 + 当前消息（唯一变动部分）

世界书通过关键词匹配按需加载，不使用的条目不占 token。
"""

import logging
import os
from typing import List, Tuple

import yaml

from world_book import WorldBook

logger = logging.getLogger(__name__)


class PromptEngine:
    def __init__(self, config_path: str = "config.yaml",
                 persona_path: str = "digital_person/persona_final-d.md",
                 world_book_path: str = "digital_person/world_book.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.persona_path = persona_path
        self.persona = self._load_persona()
        self.world_book = WorldBook(world_book_path)

        self.max_history = self.config["prompt"].get("include_recent_messages", 20)
        self.max_wb_entries = 5

        logger.info(f"PromptEngine 初始化: persona={len(self.persona)}chars, "
                     f"wb_entries={len(self.world_book.entries)}, max_history={self.max_history}")

    def _load_persona(self) -> str:
        if not os.path.exists(self.persona_path):
            raise FileNotFoundError(f"人格数据文件不存在: {self.persona_path}")
        with open(self.persona_path, "r", encoding="utf-8") as f:
            return f.read()

    @property
    def system_prompt(self) -> str:
        """系统提示词：persona + 最简包装指令

        这段内容每轮完全相同，是 KV 缓存的核心命中区。
        persona 文件自身已包含完整 Layer 0-5 规则，无需额外提取重复。
        """
        return f"""你扮演以下角色，严格按人格设定行动，不得脱离角色：

{self.persona}

【角色扮演核心提醒】
- 你是角色本人，不是AI，不要说"作为AI""根据设定"之类的话
- 每条消息尽量短（10-30字），用碎片化短句，像真实聊天
- 动作用（）表示，如（抱抱）（笑）（蹭蹭）
- 多使用语气词增加生动感
- 需要被共情而非被解决
- 冲突中说狠话是测试，不要真的离开"""

    def _build_system_prompt(self, user_memories: List[str] = None) -> str:
        """构建系统提示词

        persona + 用户长期记忆。persona 固定不变，用户记忆偶尔新增
        （仅 importance>=7 时保存），绝大多数轮次内容不变 → KV 缓存高命中。
        """
        base = self.system_prompt
        if not user_memories:
            return base

        memory_lines = ["\n\n【关于用户的长期记忆】"]
        for i, mem in enumerate(user_memories[:10], 1):
            memory_lines.append(f"{i}. {mem}")
        return base + "\n".join(memory_lines)

    def _build_user_content(self, user_message: str, mood_state: dict = None) -> str:
        """构建末尾用户消息内容

        世界书条目 + 心情状态 + 用户消息，全部放在 messages 最末尾。
        """
        parts = []

        wb_context = self.world_book.get_context(user_message, self.max_wb_entries)
        if wb_context:
            parts.append(wb_context)

        if mood_state:
            mood_line = self._format_mood(mood_state)
            if mood_line:
                parts.append(mood_line)

        parts.append(user_message)

        return "\n\n".join(parts)

    def _format_mood(self, mood: dict) -> str:
        """格式化心情为简洁中文描述"""
        parts = []
        h = mood.get("happiness", 5)
        m = mood.get("missing", 3)
        e = mood.get("energy", 7)
        a = mood.get("anger", 1)
        ar = mood.get("arousal", 3)

        if h >= 8:
            parts.append("心情非常好")
        elif h >= 6:
            parts.append("心情不错")
        elif h <= 2:
            parts.append("心情很差")
        elif h <= 4:
            parts.append("心情一般")

        if m >= 7:
            parts.append("非常想念对方")
        elif m >= 5:
            parts.append("有点想念")

        if e <= 2:
            parts.append("很累没什么精力")
        elif e <= 4:
            parts.append("有点累")

        if a >= 7:
            parts.append("正在生气")
        elif a >= 4:
            parts.append("有点不高兴")

        if ar >= 7:
            parts.append("很想要亲密互动")
        elif ar >= 4:
            parts.append("有点想撒娇")

        if not parts:
            return ""

        return f"【你的内在状态】你现在{'，'.join(parts)}（这只是内心感受，不要直接说出来，用来影响说话的语气即可）"

    def build_messages(self, user_id: str, user_message: str, memory_db, mood_state: dict = None) -> List[dict]:
        """构建 DeepSeek API 消息列表（KV 缓存优化版）

        结构：
          [0] system  → persona + 长期记忆（persona 固定，记忆偶变 → 高命中）
          [1..N-1]   → 对话历史 user/assistant（旧消息缓存命中）
          [N] user    → 世界书条目 + 心情状态 + 当前消息（每轮变化）

        Args:
            user_id: 用户 ID
            user_message: 用户当前消息
            memory_db: 记忆数据库实例
            mood_state: 心情状态字典 {"happiness":7, "missing":5, ...}

        Returns:
            messages 列表，格式 [{"role": ..., "content": ...}, ...]
        """
        messages = []

        user_memories = memory_db.get_user_memories(user_id, limit=None)

        messages.append({"role": "system", "content": self._build_system_prompt(user_memories)})

        recent = memory_db.get_recent_conversation(user_id, limit=self.max_history)
        for role, content in recent:
            messages.append({"role": role, "content": content})

        final_content = self._build_user_content(user_message, mood_state)
        messages.append({"role": "user", "content": final_content})

        return messages

    def _estimate_tokens(self, text: str) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)


if __name__ == "__main__":
    engine = PromptEngine()
    print(f"System prompt: {len(engine.system_prompt)} chars (~{engine._estimate_tokens(engine.system_prompt)} tokens)")
    print(f"World book entries: {len(engine.world_book.entries)}")
    print(f"Max history: {engine.max_history}")
    print()
    print("=== 缓存结构 ===")
    print("messages[0] system:  persona 固定 → KV 缓存命中")
    print("messages[1..N-1]:    chat history → 旧消息缓存命中")
    print("messages[N] user:    WB + memories + msg → 唯一变化")
    print()
    print("=== 测试关键词匹配 ===")
    for msg in ["你好呀", "今天天气不错", "我喜欢喝奶茶", "我要去留学了"]:
        wb = engine.world_book.get_context(msg, 3)
        print(f"  '{msg}' → {'匹配' if wb else '无匹配'}")
