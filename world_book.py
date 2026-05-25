#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
世界书管理器
从 memories_final-d.md 衍生的结构化记忆条目，按关键词触发加载
用于在对话末尾注入角色背景记忆，配合 DeepSeek KV 缓存最大化命中
"""

import json
import logging
import os
import re
from typing import List

logger = logging.getLogger(__name__)


class WorldBook:
    """世界书：按需加载的角色背景记忆"""

    def __init__(self, wb_path: str = "digital_person/world_book.json"):
        self.entries: List[dict] = []
        self._load(wb_path)

    def _load(self, path: str):
        if not os.path.exists(path):
            logger.warning(f"世界书文件不存在: {path}")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = data if isinstance(data, list) else data.get("entries", [])
            logger.info(f"世界书加载完成: {len(self.entries)} 条目")
        except Exception as e:
            logger.error(f"加载世界书失败: {e}")

    def find_matches(self, text: str) -> List[str]:
        """在用户消息中匹配关键词，返回触发条目的内容列表

        Args:
            text: 用户消息文本

        Returns:
            匹配到的世界书条目内容列表
        """
        matched = []
        seen_ids = set()

        for entry in self.entries:
            keys = entry.get("keys", entry.get("keywords", []))
            for key in keys:
                if key and key in text:
                    content = entry.get("content", "")
                    if content and id(content) not in seen_ids:
                        matched.append(content)
                        seen_ids.add(id(content))
                        logger.debug(f"世界书命中: {entry.get('comment', '?')} ← '{key}'")
                    break

        return matched

    def get_context(self, user_message: str, max_entries: int = 5) -> str:
        """获取当前消息触发的世界书上下文

        Args:
            user_message: 用户消息
            max_entries: 最大返回条目数

        Returns:
            格式化的世界书上下文文本，如果没有命中则返回空字符串
        """
        matches = self.find_matches(user_message)
        if not matches:
            return ""

        matches = matches[:max_entries]
        lines = ["[角色相关记忆]"]
        for i, content in enumerate(matches, 1):
            lines.append(f"{i}. {content}")
        return "\n".join(lines)

    def reload(self, path: str = None):
        """重新加载世界书"""
        if path is None:
            path = "digital_person/world_book.json"
        self.entries.clear()
        self._load(path)
