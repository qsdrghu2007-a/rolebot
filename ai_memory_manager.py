#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 驱动的长期记忆管理器
让 LLM 自己判断什么值得记住
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from llm_client import DeepSeekClient

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Optional[dict]:
    """从文本中提取 JSON 对象"""
    if not text or not text.strip():
        return None

    t = text.strip()

    # 1. 直接解析
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # 2. 查找最外层的 {...} 对（处理嵌套和跨行）
    start = t.find('{')
    if start >= 0:
        # 从开头找配对的 }
        depth = 0
        end = -1
        for i in range(start, len(t)):
            if t[i] == '{':
                depth += 1
            elif t[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > start:
            try:
                return json.loads(t[start:end+1])
            except json.JSONDecodeError:
                pass

    # 3. 尝试提取代码块 ```json ... ```
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', t, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    return None


@dataclass
class MemoryDecision:
    """记忆决策结果"""
    should_remember: bool
    memory_type: str  # personal, preference, event, emotion, fact, none
    content: str
    importance: int  # 1-10
    reason: str
    mood_changes: dict = None  # {"happiness": 1, "missing": -1} 等
    
    def __post_init__(self):
        if self.mood_changes is None:
            self.mood_changes = {}


class AIMemoryManager:
    """AI 驱动的记忆管理器"""

    MEMORY_TYPES = ["personal", "preference", "event", "emotion", "fact"]

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-chat"):
        """
        初始化记忆管理器

        Args:
            api_key: DeepSeek API 密钥
            base_url: API 基础 URL
            model: 用于判断记忆的模型（可以用轻量级模型降低成本）
        """
        self.client = DeepSeekClient(api_key, base_url)
        self.model = model

    def _build_judge_prompt(self, user_message: str, conversation_context: str = "") -> List[dict]:
        """构建判断是否要记住的 prompt"""

        system_prompt = """你是一个严格的记忆管理助手。判断用户消息是否包含值得**长期**记住的信息。

核心原则：长期记忆只存重要、持久、可复用的信息。临时情绪、一次性抱怨、日常寒暄一律不存。

**用户明确要求记忆（最高优先级，覆盖所有其他规则）**：
当用户消息中包含"记住"、"记一下"、"帮我记住"、"别忘了"、"备注"、"记下来"、"存一下"等主动要求记忆的关键词时，说明用户**明确希望**保存某条信息。此时：
- must_remember 必须为 true，should_remember 必须为 true
- 无论内容类型（即使按普通标准不值得记），都必须提取核心信息并保存
- importance 设为 9（默认）或 10（如果你判断是极其重要的事）
- content 字段提炼用户要求记住的核心信息，使用第三人称简洁陈述
- 如果是"反指令"（"别记住"、"不用记"、"别记了"、"不用记住"、"删除关于...的记忆"），则正常判断

值得记住的信息（高门槛）：
- 个人信息：姓名、年龄、生日、住址、学校、工作、联系方式、家庭构成等
- 稳定偏好：长期喜欢的食物、颜色、音乐、电影、游戏、品牌、兴趣爱好等
- 重要事件：具体日期/时间的计划、约定、纪念日、考试日期、出差安排等
- 重大情感：持续的心理状态、重大人生事件引起的情绪（失恋、升职、亲人离世）、长期压力源
- 重要事实：对决策有影响的信息（过敏、疾病、预算限制、设备型号等）

**不值得记住的信息（多数情况）**：
- 日常寒暄、问候（"你好"、"在吗"、"拜拜"）
- 临时请求（"帮我查个东西"、"翻译一下"）
- 无意义闲聊（"今天天气不错"、"哈哈"）
- **一次性情绪抱怨**："今天好累"、"作业好多"、"压力好大"、"烦死了"等——这些是一次性宣泄，不存
- **短暂身体不适**："头疼"、"肚子饿"、"没睡好"——临时状态，不存
- **已重复过多次的信息**——已经知道，无需重复存

**情感状态判断标准**：
- 重要性≥7才存：重大生活变故、确诊心理疾病、持续两周以上的情绪问题
- 不存（重要性1-3）：日常抱怨、一次性吐槽、短暂不开心、工作/学习疲劳

**重要性评分标准**：
- 1-3：不存入（临时、琐碎、一次性）
- 4-6：中等（有一定参考价值，但不够重要）
- 7-8：重要（对未来对话有持续参考价值）
- 9-10：非常重要（核心个人信息、重大事件）

关键：content 字段必须是指向用户的第三人称简洁陈述，去除冗余词语。

**示例（应该存）**：
用户说"我和你说我喜欢喝奶茶" → content: "用户喜欢喝奶茶", importance: 6, should_remember: true
用户说"我叫小明，今年18岁，在北大读书" → content: "用户名为小明，18岁，北京大学学生", importance: 9, should_remember: true
用户说"下周三是我生日" → content: "用户下周三生日", importance: 7, should_remember: true
用户说"我有花粉过敏，春天特别严重" → content: "用户有花粉过敏，春季严重", importance: 7, should_remember: true
用户说"我被确诊抑郁症一年了" → content: "用户确诊抑郁症约一年", importance: 9, should_remember: true

**示例（不应该存）**：
用户说"最近工作压力好大啊" → should_remember: false, reason: "一次性抱怨，非持续性问题"
用户说"今天作业好多，手都写酸了" → should_remember: false, reason: "临时状态，无长期价值"
用户说"（抱抱" → should_remember: false, reason: "日常互动，无实质信息"
用户说"我明天要交报告" → should_remember: false, reason: "临时事件，非重要约定"

输出格式（必须是合法JSON）：
{
    "should_remember": true/false,
    "memory_type": "personal/preference/event/emotion/fact/none",
    "content": "第三人称简洁陈述，去除冗余",
    "importance": 1-10,
    "reason": "为什么记住/不记住，用严格标准判断",
    "mood": {
        "happiness": -2到2,
        "missing": -2到2,
        "anger": -2到2,
        "energy": -2到2
    }
}

mood 字段说明：根据用户消息推断它对bot心情的即时影响（不是用户自己的心情）。
- happiness: 用户说了开心/暖心/表白的话 +1到+2，用户冷漠/敷衍/吵架 -1到-2
- missing: 用户表达想念 +1到+2，用户回来/聊天很开心/被满足了 -1到-2，无相关则 0
- anger: 用户说了让你（bot）生气的话 +1到+2，道歉/哄你 -1到-2
- energy: 用户消息很有活力/兴奋 +1到+2，用户抱怨/沉闷 -1到-2
- 日常寒暄或中性消息全部填 0"""

        user_prompt = f"""用户消息："{user_message}"

{conversation_context}

请判断是否要记住这条消息。只输出 JSON，不要其他内容。"""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    def judge_memory(self, user_message: str, recent_messages: List[str] = None) -> MemoryDecision:
        """
        判断是否应该记住这条消息

        Args:
            user_message: 用户消息
            recent_messages: 最近几条对话（可选，用于上下文理解）

        Returns:
            MemoryDecision 对象
        """
        # 0. 快速路径：用户明确要求记住
        force_keywords = ["记住", "记一下", "帮我记住", "别忘了", "备注", "记下来", "存一下"]
        force_remember = any(kw in user_message for kw in force_keywords)
        if force_remember:
            force_no_keywords = ["别记住", "不用记", "别记了", "不用记住", "删除记忆", "忘掉"]
            if not any(kw in user_message for kw in force_no_keywords):
                logger.info(f"用户明确要求记忆，跳过 LLM 判断")
                # 清理命令前缀
                clean = user_message
                for kw in sorted(force_keywords, key=len, reverse=True):
                    if clean.startswith(kw):
                        clean = clean[len(kw):].lstrip("，,。. ")
                        break
                return MemoryDecision(
                    should_remember=True,
                    memory_type="fact",
                    content=clean,
                    importance=9,
                    reason="用户明确要求记住"
                )

        # 构建上下文
        context = ""
        if recent_messages:
            context = "最近对话：\n" + "\n".join([f"- {m}" for m in recent_messages[-3:]])

        messages = self._build_judge_prompt(user_message, context)

        try:
            # 使用较低的 temperature 和 max_tokens 降低成本
            response = self.client.chat(
                messages=messages,
                temperature=0.1,  # 低随机性，更确定性的判断
                max_tokens=200,   # JSON 输出不需要太多 token
                model=self.model
            )

            # 从响应中提取 JSON（支持多种格式）
            result = _extract_json(response)
            if result is None:
                logger.warning(f"无法从响应中提取 JSON: len={len(response)} preview={response[:200]}")
                return MemoryDecision(False, "none", "", 1, f"无法提取JSON: {response[:80]}")

            return MemoryDecision(
                should_remember=result.get("should_remember", False),
                memory_type=result.get("memory_type", "none"),
                content=result.get("content", ""),
                importance=min(10, max(1, result.get("importance", 5))),
                reason=result.get("reason", ""),
                mood_changes=result.get("mood", {})
            )

        except Exception as e:
            logger.error(f"记忆判断 API 调用失败: {e}")
            return MemoryDecision(False, "none", "", 1, f"API 错误: {e}")

    def process_message(self, user_id: str, user_message: str,
                       memory_db, recent_messages: List[str] = None) -> tuple:
        """
        处理消息，判断并保存记忆，同时返回心情变化

        Args:
            user_id: 用户 ID
            user_message: 用户消息
            memory_db: 记忆数据库对象
            recent_messages: 最近对话历史

        Returns:
            (saved_content_or_None, mood_changes_dict)
        """
        decision = self.judge_memory(user_message, recent_messages)

        mood = decision.mood_changes or {}

        if not decision.should_remember or not decision.content:
            logger.debug(f"未保存记忆: {decision.reason}")
            return None, mood

        if decision.importance < 7:
            logger.debug(f"未保存记忆: 重要性 {decision.importance} < 7")
            return None, mood

        memory_type = decision.memory_type if decision.memory_type in self.MEMORY_TYPES else "fact"

        memory_db.add_user_memory(
            user_id=user_id,
            memory_type=memory_type,
            content=decision.content,
            importance=decision.importance
        )

        logger.info(f"AI 保存记忆 [{memory_type}, 重要性{decision.importance}]: {decision.content[:50]}...")
        return decision.content, mood

    def judge_memory_async(self, user_message: str, recent_messages: List[str] = None):
        """异步版本的判断（返回 coroutine）"""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            return loop.run_in_executor(pool, self.judge_memory, user_message, recent_messages)


class HybridMemoryManager:
    """混合模式：AI 判断记忆，失败时静默处理"""

    def __init__(self, ai_manager: AIMemoryManager, backup_enabled: bool = False):
        self.ai_manager = ai_manager

    def process_message(self, user_id: str, user_message: str,
                       memory_db, recent_messages: List[str] = None) -> tuple:
        return self.ai_manager.process_message(user_id, user_message, memory_db, recent_messages)


class ArousalJudge:
    """独立的性欲/文爱状态判断器

    只根据最新一条用户消息判断是否处于文爱/性相关状态。
    与记忆判断、主会话完全并行，不阻塞任何操作。
    """

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-v4-flash"):
        self.client = DeepSeekClient(api_key, base_url)
        self.model = model

    def judge_erotic(self, user_message: str) -> bool:
        """判断一条用户消息是否属于文爱/性内容

        返回 True 仅当：明确的性行为描述、dirty talk、文爱中的性场景
        返回 False：亲亲抱抱蹭蹭、事后安抚、普通聊天、任何非性内容
        """
        system_prompt = """你是严格的文爱/性内容检测器。只判断用户消息是否包含**明确**的文爱或性相关内容。

返回 TRUE（是文爱/性内容）：
- 明确的性行为动作描述（如做爱、口交、插入、揉捏性器官等）
- 明确的 dirty talk、性挑逗语言
- 文爱中的性爱场景推进

返回 FALSE（不是文爱/性内容）：
- 普通亲热：亲亲、抱抱、蹭蹭、贴贴、牵手、摸头
- 事后安抚/温存：抱紧、轻抚、聊天、关心
- 撒娇、调情但不涉及性行为
- 任何非性内容的日常对话
- 模糊暗示但不明确的内容

只输出一个单词：true 或 false"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f'用户消息："{user_message}"\n\n只输出 true 或 false：'}
        ]

        try:
            response = self.client.chat(
                messages=messages,
                temperature=0,
                max_tokens=10,
                model=self.model,
                thinking={"type": "disabled"}
            )
            result = response.strip().lower()
            return "true" in result
        except Exception as e:
            logger.warning(f"性欲判断 API 失败: {e}")
            return False


if __name__ == "__main__":
    # 测试
    import os
    import yaml

    # 加载配置
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    manager = AIMemoryManager(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"]["base_url"],
        model=config["llm"].get("model", "deepseek-chat")
    )

    # 测试消息
    test_messages = [
        "你好呀",
        "我和你说我喜欢喝奶茶",
        "我叫小明，今年18岁",
        "下周三是我生日",
        "（抱抱",
        "今天作业好多，手都写酸了",
        "我有花粉过敏，春天特别严重",
        "帮我查一下天气",
        "最近工作压力好大啊",
    ]

    for msg in test_messages:
        decision = manager.judge_memory(msg)
        print(f"\n消息: {msg}")
        print(f"  记住: {decision.should_remember}")
        print(f"  类型: {decision.memory_type}")
        print(f"  内容: {decision.content}")
        print(f"  重要性: {decision.importance}")
        print(f"  理由: {decision.reason}")
