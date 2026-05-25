#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram机器人核心模块
处理Telegram消息收发和对话流程
基于python-telegram-bot v20.x
"""

import asyncio
import logging
import time
import traceback
from collections import deque
from datetime import datetime
from typing import Dict, Optional

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest
from telegram.error import TimedOut, NetworkError
import tenacity

from prompt_engine import PromptEngine
from llm_client import LLMManager
from memory_db import MemoryDB
from ai_memory_manager import AIMemoryManager, HybridMemoryManager, ArousalJudge

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, config: dict):
        """初始化Telegram机器人

        Args:
            config: 配置字典
        """
        self.config = config
        self.prompt_engine = PromptEngine(
            config_path="config.yaml",
            persona_path="digital_person/persona_final-d.md",
            world_book_path="digital_person/world_book.json"
        )
        self.llm_manager = LLMManager(config)
        self.memory_db = MemoryDB(config["memory"]["db_path"])

        # AI 记忆管理器（让 LLM 自己判断什么值得记住）
        self.ai_memory_manager = HybridMemoryManager(
            AIMemoryManager(
                api_key=config["llm"]["api_key"],
                base_url=config["llm"]["base_url"],
                model=config["llm"].get("model", "deepseek-chat")
            ),
            backup_enabled=True
        )

        # 性欲/文爱独立判断器
        self.arousal_judge = ArousalJudge(
            api_key=config["llm"]["api_key"],
            base_url=config["llm"]["base_url"],
            model="deepseek-v4-flash"
        )

        # Telegram相关
        self.bot_token = config["telegram"]["bot_token"]
        self.allowed_user_ids = config["telegram"].get("allowed_user_ids", [])
        self.enable_group_chat = config["telegram"].get("enable_group_chat", False)
        self.connect_timeout = config["telegram"].get("connect_timeout", 30)
        self.read_timeout = config["telegram"].get("read_timeout", 30)
        self.proxy_url = config["telegram"].get("proxy_url")  # 可选代理

        # 应用实例
        self.application = None

        # 消息处理队列（防止重复处理）- 使用deque自动限制大小
        self.processed_messages = deque(maxlen=1000)

        # 追踪每个用户最后一条 bot 回复的 message_id（用于 /regenerate 删除废弃消息）
        self._bot_reply_ids = {}
        self._bot_db_ids = {}  # user_id -> bot 回复的 DB id

        # /suggest 候选回复临时存储
        self._suggestions = {}  # user_id -> [reply1, reply2, reply3]

        # 统计信息
        self.stats = {
            "total_messages": 0,
            "successful_responses": 0,
            "failed_responses": 0,
            "start_time": datetime.now(),
            "total_response_time": 0.0,
            "today_messages": 0,
            "today_date": datetime.now().strftime("%Y-%m-%d"),
        }

        logger.info("Telegram机器人初始化完成")
        self.loop = None

    def _is_user_allowed(self, user_id: int) -> bool:
        """检查用户是否被允许使用机器人

        Args:
            user_id: Telegram用户ID

        Returns:
            True如果用户被允许
        """
        if not self.allowed_user_ids:
            # 空列表表示允许所有用户（方便测试）
            # 生产环境建议设置具体的用户ID
            logger.warning(f"allowed_user_ids为空，允许所有用户访问。用户ID: {user_id}")
            return True
        return user_id in self.allowed_user_ids

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令

        发送欢迎消息
        """
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        welcome_msg = """你好呀~ 我是你的AI伙伴！

可以跟我聊天，我会记住重要的事情。
使用 /help 查看可用命令"""
        await update.message.reply_text(welcome_msg)

        # 记录用户
        self.memory_db.update_user_last_seen(str(user_id))

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/help命令

        显示帮助信息
        """
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        help_text = """Telegram机器人帮助

功能：
- 智能对话：基于DeepSeek API的智能对话
- 长期记忆：记住重要的对话内容
- 人格定制：支持自定义角色人格
- 思考模式：开启后模型会先推理再回答，质量更高
- 编辑功能：直接回复某条消息即可编辑该消息，后续对话自动重新生成

可用命令：
/suggest - 生成3条候选回复供你选择
/start - 开始使用机器人
/mood - 查看当前心情
/continue - bot独自继续生成下一条回复
/regenerate - 重新生成上一轮回复（删除旧回复）
/clear - 清除当前对话历史（短期记忆）
/clear_memories - 清除所有长期记忆（警告）
/list_memories - 列出所有长期记忆
/delete_memory <编号> - 删除指定记忆（无参数则显示按钮版翻页列表）
/thinking - 查看/设置思考模式（无参数显示按钮版）
/help - 显示此帮助信息
/status - 显示机器人状态
/compact - 日记视角总结对话 (/compact list 查看历史日记)

直接发送消息即可开始对话！

注意：
- 机器人会记住重要的对话内容
- /clear 只清除当前对话，长期记忆还在
- /clear_memories 会清除所有记住的个人信息、喜好等
- 长期记忆可随时查看和删除单条
- 在群组中默认不响应，除非被@
- 对话数据存储在本地，保护隐私
- 思考模式会增加响应时间，但回复质量更高
"""
        await update.message.reply_text(help_text)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/status命令 — 4-tab 仪表盘"""
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        await self._show_status_tab(update, str(user_id), "overview")

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/clear命令 — 先询问是否总结，再清除对话历史"""
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        since = self.memory_db.get_last_clear_at(str(user_id))
        messages = self.memory_db.get_messages_since_clear(str(user_id), since)
        has_msgs = bool(messages) or self.memory_db.get_recent_conversation(str(user_id), limit=1)
        if has_msgs:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("总结并清除", callback_data="clear:compact"),
                 InlineKeyboardButton("直接清除", callback_data="clear:direct")],
                [InlineKeyboardButton("取消", callback_data="clear:cancel")],
            ])
            await update.message.reply_text("清除前可以先做日记总结，要总结吗？", reply_markup=kb)
        else:
            deleted_count = self.memory_db.clear_user_conversation(str(user_id))
            self.memory_db.record_last_clear(str(user_id))
            if deleted_count > 0:
                await update.message.reply_text(f"已清除 {deleted_count} 条对话历史")
            else:
                await update.message.reply_text("还没有对话历史可以清除~")

    async def clear_memories_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/clear_memories命令

        清除当前用户的长期记忆
        """
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        # 确认消息
        confirm_text = (
            "【警告】这将清除所有长期记忆！\n\n"
            "这包括：\n"
            "• 你的姓名、年龄等个人信息\n"
            "• 你的喜好偏好\n"
            "• 重要事件和约定\n\n"
            "操作不可逆，确定要清除吗？\n"
            "发送 `/confirm_clear_memories` 确认清除"
        )
        await update.message.reply_text(confirm_text, parse_mode='Markdown')

    async def confirm_clear_memories_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/confirm_clear_memories命令 - 确认清除长期记忆"""
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        # 清除长期记忆
        deleted_count = self.memory_db.clear_user_memories(str(user_id))

        if deleted_count > 0:
            await update.message.reply_text(f"喵... 已清除 {deleted_count} 条长期记忆... 以前的记忆已全部清除...")
        else:
            await update.message.reply_text("还没有长期记忆存储")

    async def list_memories_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/list_memories命令 - 列出所有长期记忆"""
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        # 获取所有长期记忆（带ID）
        memories = self.memory_db.get_user_memories_with_id(str(user_id))

        if not memories:
            await update.message.reply_text("还没有长期记忆存储着呢~\n\n发送消息和我聊天，我会记住重要的事情哦~")
            return

        # 格式化记忆列表
        lines = [f"你有 {len(memories)} 条长期记忆：\n"]
        for idx, (mem_id, mem_type, content, importance) in enumerate(memories, 1):
            # 截断过长的内容
            display_content = content[:60] + "..." if len(content) > 60 else content
            type_emoji = {"personal": "[个人]", "preference": "[喜好]", "event": "[事件]", "emotion": "[情感]", "fact": "[事实]"}.get(mem_type, "[其他]")
            lines.append(f"{idx}. {type_emoji} [{mem_type}] {display_content} (重要度:{importance})")

        lines.append("\n提示: 用 `/delete_memory <编号>` 删除单条记忆")

        # 如果消息太长，分段发送
        message = "\n".join(lines)
        if len(message) > 4096:
            # Telegram 单条消息限制 4096 字符
            await update.message.reply_text(message[:4000] + "\n\n...（消息太长，只显示部分）")
        else:
            await update.message.reply_text(message)

    async def delete_memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/delete_memory命令 - 删除指定编号的记忆（无参数时显示按钮版）"""
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        args = context.args
        if not args:
            # 无参数 → 显示按钮版翻页记忆列表
            query_dummy = None
            await self._show_memory_page_via_message(update, user_id)
            return

        if not args[0].isdigit():
            await update.message.reply_text("【错误】请提供记忆编号\n\n用法: `/delete_memory <编号>`\n\n直接输入 `/delete_memory` 可查看按钮版")
            return

        memory_index = int(args[0])
        if memory_index < 1:
            await update.message.reply_text("【错误】编号必须是正整数")
            return

        memories = self.memory_db.get_user_memories_with_id(str(user_id))
        if not memories:
            await update.message.reply_text("还没有长期记忆存储")
            return

        if memory_index > len(memories):
            await update.message.reply_text(f"【错误】编号 {memory_index} 不存在，你只有 {len(memories)} 条记忆\n\n用 `/delete_memory` 查看列表")
            return

        mem_id, mem_type, content, importance = memories[memory_index - 1]

        if self.memory_db.delete_memory_by_id(str(user_id), mem_id):
            display_content = content[:40] + "..." if len(content) > 40 else content
            await update.message.reply_text(f"[已删除] 记忆 #{memory_index}：{display_content}")
        else:
            await update.message.reply_text("【错误】删除失败，请稍后再试")

    async def _show_memory_page_via_message(self, update: Update, user_id: int):
        """通过 update.message 发送记忆按钮列表（首次展示）"""
        uid = str(user_id)
        memories = self.memory_db.get_user_memories_with_id(uid)

        if not memories:
            await update.message.reply_text("还没有长期记忆存储着呢~\n\n发送消息和我聊天，我会记住重要的事情哦~")
            return

        total = len(memories)
        per_page = 10
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = 1

        start = (page - 1) * per_page
        end = min(start + per_page, total)
        page_memories = memories[start:end]

        lines = [f"长期记忆 ({total} 条，第 {page}/{total_pages} 页):"]
        for i, (mem_id, mem_type, content, importance) in enumerate(page_memories, start + 1):
            short = content[:50] + "..." if len(content) > 50 else content
            type_emoji = {"personal": "[个人]", "preference": "[喜好]", "event": "[事件]",
                          "emotion": "[情感]", "fact": "[事实]"}.get(mem_type, "[其他]")
            lines.append(f"{i}. {type_emoji} [{mem_type}] {short} (重要度:{importance})")

        text = "\n".join(lines)

        button_rows = []
        for i, (mem_id, mem_type, content, importance) in enumerate(page_memories, start + 1):
            short = content[:30]
            button_rows.append([InlineKeyboardButton(
                f"删除 #{i}: {short}", callback_data=f"delmem:{mem_id}:{page}"
            )])

        nav_row = []
        nav_row.append(InlineKeyboardButton("📄 1/1", callback_data="noop"))
        if total_pages > 1:
            nav_row.append(InlineKeyboardButton("下一页 ▶", callback_data="delmem_page:2"))
        button_rows.append(nav_row)

        kb = InlineKeyboardMarkup(button_rows)
        await update.message.reply_text(text, reply_markup=kb)

    async def thinking_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/thinking命令 - 查看或设置思考模式

        用法:
            /thinking         - 查看当前状态和可用子命令
            /thinking off     - 关闭思考模式
            /thinking high    - 开启思考模式，强度为 high
            /thinking max     - 开启思考模式，强度为 max
        """
        user = update.effective_user
        user_id = user.id

        if not self._is_user_allowed(user_id):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        args = context.args
        if not args:
            current = self.llm_manager.get_thinking_status()
            status_text = f"当前: {'开启' if current['enabled'] else '关闭'}"
            if current['enabled']:
                status_text += f" (强度: *{current['effort']}*)"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("高强度思考", callback_data="think:high"),
                 InlineKeyboardButton("最大强度", callback_data="think:max")],
                [InlineKeyboardButton("关闭思考", callback_data="think:off")],
            ])
            await update.message.reply_text(status_text, reply_markup=kb, parse_mode='Markdown')
            return

        sub = args[0].lower()

        if sub == "high":
            self.llm_manager.set_thinking(enabled=True, effort="high")
            await update.message.reply_text("开启思考模式 [强度: *high*] | `/thinking max` 可切换为最大强度\n\n> 模型回复会更加细致，但响应时间更长", parse_mode='Markdown')
        elif sub == "max":
            self.llm_manager.set_thinking(enabled=True, effort="max")
            await update.message.reply_text("开启思考模式 [强度: *max*] | `/thinking high` 可切换为高强度\n\n> 最大化思考强度，回复质量最高，但响应时间最长", parse_mode='Markdown')
        elif sub == "off":
            self.llm_manager.set_thinking(enabled=False)
            await update.message.reply_text("关闭思考模式 | `/thinking high` 或 `/thinking max` 可重新开启", parse_mode='Markdown')
        else:
            await update.message.reply_text("未知参数。用法:\n`/thinking high` - 高强度思考\n`/thinking max` - 最大强度思考\n`/thinking off` - 关闭思考", parse_mode='Markdown')

    async def regenerate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/regenerate命令 - 重新生成上一轮回复并删除废弃消息"""
        user = update.effective_user
        user_id = str(user.id)

        if not self._is_user_allowed(int(user_id)):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        last_user_msg = self.memory_db.get_last_user_message(user_id)
        if not last_user_msg:
            await update.message.reply_text("没有可以重新生成的消息~ | 先发条消息给我吧")
            return

        # 删除旧一轮对话（DB）
        self.memory_db.delete_last_conversation_pair(user_id)

        # 删除旧 bot 回复（Telegram）
        old_msg_id = self._bot_reply_ids.pop(user_id, None)
        if old_msg_id:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=old_msg_id
                )
            except Exception:
                pass

        # 发送"正在思考"提示
        try:
            await update.message.chat.send_action(action="typing")
        except Exception:
            pass

        # 重新生成
        try:
            messages = self.prompt_engine.build_messages(user_id, last_user_msg, self.memory_db, self._get_mood_state(user_id))
            start_time = time.time()
            response = self.llm_manager.generate_response(messages)
            elapsed_time = time.time() - start_time
            logger.info(f"重新生成响应耗时: {elapsed_time:.2f}s")
            self._release_missing_if_expressed(user_id, response)

            self.memory_db.add_message(user_id, "user", last_user_msg)
            bot_db_id = self.memory_db.add_message(user_id, "assistant", response)

            sent_msg = await update.message.reply_text(response)
            self._bot_reply_ids[user_id] = sent_msg.message_id
            if bot_db_id:
                self._bot_db_ids[user_id] = bot_db_id
                self.memory_db._update_tg_msg_id(bot_db_id, sent_msg.message_id)
            logger.info(f"重新生成回复 [{user.full_name}]: {response[:50]}...")

            self.stats["successful_responses"] += 1
            self._track_response(elapsed_time)
            self.stats["total_messages"] += 1

            asyncio.create_task(self._process_memory_async(user_id, last_user_msg))
        except Exception as e:
            logger.error(f"重新生成消息失败: {e}", exc_info=True)
            error_msg = f"重新生成出错了: {str(e)}"
            try:
                await update.message.reply_text(error_msg)
            except Exception:
                pass
            self.stats["failed_responses"] += 1

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本消息

        Args:
            update: Telegram更新对象
            context: 上下文对象
        """
        # 检查是否是群组消息
        chat_type = update.effective_chat.type
        is_group = chat_type in ["group", "supergroup"]

        # 如果在群组中但未启用群组聊天，且没有被@，则忽略
        if is_group and not self.enable_group_chat:
            if not update.message.text.startswith('@'):
                # 检查是否@了机器人
                if update.message.entities:
                    for entity in update.message.entities:
                        if entity.type == "mention":
                            mention = update.message.text[entity.offset:entity.offset+entity.length]
                            if mention == f"@{context.bot.username}":
                                break
                    else:
                        return  # 没有@机器人，忽略
                else:
                    return

        user = update.effective_user
        user_id = str(user.id)

        # 检查用户权限
        if not self._is_user_allowed(int(user_id)):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        # 获取消息文本
        message_text = update.message.text
        msg_id = update.message.message_id

        # 移除可能的@mention
        if is_group and update.message.entities:
            for entity in update.message.entities:
                if entity.type == "mention":
                    mention = message_text[entity.offset:entity.offset+entity.length]
                    if mention == f"@{context.bot.username}":
                        # 移除@mention
                        message_text = message_text.replace(mention, "").strip()
                        break

        if not message_text:
            return

        # 防止重复处理
        if msg_id in self.processed_messages:
            return

        self.processed_messages.append(msg_id)

        logger.info(f"收到消息 [{user.full_name}]: {message_text}")

        # 更新统计
        self.stats["total_messages"] += 1

        # 如果是回复消息 → 编辑模式
        if update.message.reply_to_message:
            await self._handle_edit(update, context, user_id, message_text, user.full_name)
            return

        # 发送"正在思考"提示（非关键，超时不阻塞）
        try:
            await update.message.chat.send_action(action="typing")
        except Exception:
            pass

        # 异步处理消息
        await self._process_message(user_id, message_text, user.full_name, update, context)

    async def _process_message(self, user_id: str, user_message: str, nickname: str,
                               update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理消息（异步版本）

        Args:
            user_id: 用户ID（字符串）
            user_message: 用户消息
            nickname: 用户昵称
            update: Telegram更新对象
            context: 上下文对象
        """
        try:
            user_msg_id = update.message.message_id

            # 0. 应用时间衰减并获取当前心情
            mood_state = self._get_mood_state(user_id)

            # 1. 构建消息列表
            messages = self.prompt_engine.build_messages(user_id, user_message, self.memory_db, mood_state)

            # 2. 调用LLM生成响应
            start_time = time.time()
            response = self.llm_manager.generate_response(messages)
            elapsed_time = time.time() - start_time

            logger.info(f"生成响应耗时: {elapsed_time:.2f}s")
            self._release_missing_if_expressed(user_id, response)

            # 3. 存储对话历史
            user_msg_db_id = self.memory_db.add_message(user_id, "user", user_message, telegram_msg_id=user_msg_id)
            bot_db_id = self.memory_db.add_message(user_id, "assistant", response)
            self._bot_db_ids[user_id] = bot_db_id

            # 4. AI 判断并保存重要记忆（异步，不阻塞回复）
            asyncio.create_task(self._process_memory_async(user_id, user_message))
            # 5. 性欲/文爱状态判断（异步，不阻塞回复）
            asyncio.create_task(self._process_arousal_async(user_id, user_message, user_msg_db_id))

            # 6. 发送响应
            sent_msg = await update.message.reply_text(response)
            self._bot_reply_ids[user_id] = sent_msg.message_id

            # 回填 bot 回复的 telegram_msg_id 到 DB
            if bot_db_id:
                self.memory_db._update_tg_msg_id(bot_db_id, sent_msg.message_id)

            logger.info(f"回复 [{nickname}]: {response[:50]}...")

            # 更新统计
            self.stats["successful_responses"] += 1

        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)
            error_msg = f"出错了: {str(e)}，请稍后再试"

            try:
                await update.message.reply_text(error_msg)
            except Exception as send_error:
                logger.error(f"发送错误消息失败: {send_error}")

            self.stats["failed_responses"] += 1

    async def _process_memory_async(self, user_id: str, user_message: str):
        """异步处理记忆判断和保存（不阻塞主响应）

        Args:
            user_id: 用户ID
            user_message: 用户原始消息（只判断这条，不包含本轮bot回复）
        """
        try:
            # 获取最近对话作为上下文（排除本轮对话，只取之前的）
            # 注意：本轮用户消息和bot回复已在 _process_message 中存入数据库
            # 所以这里取 limit=5 但跳过最新的2条（用户消息+助手回复）
            recent = self.memory_db.get_recent_conversation(user_id, limit=5)
            # 跳过本轮对话（最后两条：用户消息和助手回复）
            if len(recent) >= 2:
                recent = recent[:-2]
            recent_messages = [msg for _, msg in recent]

            # 调用 AI 判断是否需要保存记忆（只传入用户消息）
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.ai_memory_manager.process_message,
                user_id, user_message, self.memory_db, recent_messages
            )

            if result:
                saved, mood_deltas = result
                if saved:
                    logger.info(f"AI 记忆已保存: {saved[:50]}...")
                if mood_deltas:
                    self._apply_mood_changes(user_id, mood_deltas)
                    logger.info(f"心情变化: {mood_deltas}")

        except Exception as e:
            logger.warning(f"AI 记忆处理失败（非关键）: {e}")

    async def _process_arousal_async(self, user_id: str, user_message: str,
                                     user_msg_db_id: int = None):
        """异步处理性欲/文爱状态机（不阻塞主响应）

        调用独立 ArousalJudge API 判断最新用户消息是否为文爱内容，
        驱动进入/退出状态机，并控制 arousal 值。
        将本次判定后的状态快照写入 conversations 表（用于编辑后恢复）。
        """
        try:
            is_erotic = await asyncio.get_event_loop().run_in_executor(
                None, self.arousal_judge.judge_erotic, user_message
            )

            state = self.memory_db.get_erotic_state(user_id)

            if not state["active"]:
                if is_erotic:
                    state["count_enter"] += 1
                    if state["count_enter"] >= 2:
                        state["active"] = True
                        state["count_enter"] = 0
                        state["count_exit"] = 0
                        mood = self.memory_db.get_user_mood(user_id)
                        mood["arousal"] = 10
                        self.memory_db.set_user_mood(user_id, mood)
                        logger.info(f"进入文爱模式: arousal=10")
                else:
                    state["count_enter"] = 0
            else:
                if not is_erotic:
                    state["count_exit"] += 1
                    if state["count_exit"] >= 3:
                        state["active"] = False
                        state["count_enter"] = 0
                        state["count_exit"] = 0
                        mood = self.memory_db.get_user_mood(user_id)
                        mood["arousal"] = 0
                        self.memory_db.set_user_mood(user_id, mood)
                        logger.info(f"退出文爱模式: arousal=0")
                else:
                    state["count_exit"] = 0

            self.memory_db.save_erotic_state(user_id, state)

            # 写入 conversation 行快照
            if user_msg_db_id is not None:
                self.memory_db.set_arousal_snapshot(
                    user_msg_db_id, state["active"],
                    state["count_enter"], state["count_exit"]
                )

        except Exception as e:
            logger.warning(f"性欲状态判断失败（非关键）: {e}")

    async def _handle_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                           user_id: str, reply_text: str, nickname: str):
        """处理回复编辑消息

        用户回复某条消息 = 编辑该消息内容，然后删除之后的所有消息。
        编辑用户消息时重置文爱快照并恢复状态机；
        如果编辑后最后一条是用户消息则重新生成 bot 回复。
        """
        replied_msg = update.message.reply_to_message
        replied_tg_id = replied_msg.message_id

        db_msg = self.memory_db.get_message_by_tg_id(replied_tg_id)
        if not db_msg:
            await update.message.reply_text("找不到要编辑的消息记录~ 可能太久了，不支持编辑")
            return

        db_id = db_msg["id"]
        original_role = db_msg["role"]

        # 编辑用户自己的消息 → 旧 arousal 判定作废
        if original_role == "user":
            self.memory_db.reset_arousal_snapshot(db_id)

        # 编辑该消息内容
        self.memory_db.edit_message_content(db_id, reply_text)

        # 删除该消息之后的所有消息（和附着在上面的快照一起）
        deleted_tg_ids = self.memory_db.delete_messages_from_id(db_id + 1, user_id)

        # 恢复文爱状态机到编辑点之前
        prev_active, prev_enter, prev_exit = self.memory_db.get_last_arousal_snapshot_before(user_id, db_id)
        self.memory_db.save_erotic_state(user_id, {
            "active": prev_active,
            "count_enter": prev_enter,
            "count_exit": prev_exit,
        })

        # 从 Telegram 删除被清除的 bot 消息
        chat_id = update.effective_chat.id
        for tg_id in deleted_tg_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=tg_id)
            except Exception:
                pass

        # 清除旧的追踪信息
        self._bot_reply_ids.pop(user_id, None)
        self._bot_db_ids.pop(user_id, None)

        # 判断编辑后最后一条消息是否为用户消息，是则需要重新生成 bot 回复
        remaining = self.memory_db.get_conversation_from_id(user_id, db_id)
        if not remaining:
            await update.message.reply_text("编辑完成，但对话记录似乎出了问题~")
            return

        last_role = remaining[-1][0]
        regenerate_done = False

        if last_role == "user":
            user_msg_content = remaining[-1][1]
            # 临时删除该条消息，避免 build_messages 重复读取
            self.memory_db.delete_message_by_id(db_id)

            try:
                await update.message.chat.send_action(action="typing")
            except Exception:
                pass

            try:
                messages = self.prompt_engine.build_messages(user_id, user_msg_content, self.memory_db, self._get_mood_state(user_id))
                start_time = time.time()
                response = self.llm_manager.generate_response(messages)
                elapsed_time = time.time() - start_time
                logger.info(f"编辑后重新生成耗时: {elapsed_time:.2f}s")
                self._release_missing_if_expressed(user_id, response)

                user_msg_db_id = self.memory_db.add_message(user_id, "user", user_msg_content,
                                                            telegram_msg_id=update.message.message_id)
                bot_db_id = self.memory_db.add_message(user_id, "assistant", response)
                if bot_db_id:
                    self._bot_db_ids[user_id] = bot_db_id

                sent_msg = await update.message.reply_text(response)
                if bot_db_id:
                    self.memory_db._update_tg_msg_id(bot_db_id, sent_msg.message_id)
                self._bot_reply_ids[user_id] = sent_msg.message_id

                logger.info(f"编辑后回复 [{nickname}]: {response[:50]}...")
                self.stats["successful_responses"] += 1
                regenerate_done = True

                # 编辑的是用户自己的消息 → 对新内容重新做 arousal 判断
                if original_role == "user":
                    asyncio.create_task(self._process_arousal_async(user_id, user_msg_content, user_msg_db_id))

            except Exception as e:
                logger.error(f"编辑后重新生成失败: {e}", exc_info=True)
                # 恢复已删除的用户消息
                self.memory_db.add_message(user_id, "user", user_msg_content,
                                           telegram_msg_id=update.message.message_id)
                await update.message.reply_text(f"编辑后重新生成出错: {e}")
                return

        # 输出当前对话结构摘要
        summary_lines = []
        if regenerate_done:
            all_msgs = self.memory_db.get_conversation_from_id(user_id, db_id)
        else:
            all_msgs = remaining

        for i, (role, content) in enumerate(all_msgs):
            prefix = "你说" if role == "user" else "bot说"
            short = content[:80] + "..." if len(content) > 80 else content
            summary_lines.append(f"  {prefix}: {short}")

        if not summary_lines:
            return

        summary = "当前对话结构:\n" + "\n".join(summary_lines[-20:])
        if len(all_msgs) > 20:
            summary += f"\n...（共 {len(all_msgs)} 条，只显示最近 20 条）"

        await update.message.reply_text(summary)

    def _apply_mood_decay(self, user_id: str):
        """时间衰减：根据距上次更新时长调整心情"""
        mood = self.memory_db.get_user_mood(user_id)
        info = self.memory_db.get_user_info(user_id)
        updated_str = None
        if info and info.get("settings") and isinstance(info["settings"], dict):
            updated_str = info["settings"].get("mood_updated")

        hours = 0
        if updated_str:
            try:
                last = datetime.strptime(updated_str, "%Y-%m-%d %H:%M")
                hours = (datetime.now() - last).total_seconds() / 3600
            except Exception:
                pass

        if hours < 0.1:
            return mood

        # 衰减系数
        mood["happiness"] = max(0, min(10, mood["happiness"] - hours * 0.1))
        mood["missing"] = max(0, min(10, mood["missing"] + hours * 0.15))
        mood["anger"] = max(0, min(10, mood["anger"] - hours * 0.3))
        mood["arousal"] = max(0, min(10, mood["arousal"] + hours * 2.0))

        # energy: 越高精力越好，越低越累。按当前时间段模拟
        hour_of_day = datetime.now().hour
        if 7 <= hour_of_day < 10:
            mood["energy"] = max(0, min(10, mood["energy"] + 0.5))  # 早晨恢复
        elif 22 <= hour_of_day or hour_of_day < 6:
            mood["energy"] = max(0, min(10, mood["energy"] - 1))    # 深夜衰减
        else:
            mood["energy"] = max(0, min(10, mood["energy"] - hours * 0.1))  # 缓慢衰减

        self.memory_db.set_user_mood(user_id, mood)
        return mood

    def _apply_mood_changes(self, user_id: str, deltas: dict):
        """应用 AI 返回的心情变化量"""
        if not deltas:
            return
        mood = self.memory_db.get_user_mood(user_id)
        changed = False
        for key in ("happiness", "missing", "anger", "energy"):
            d = deltas.get(key, 0)
            if d and abs(d) >= 0.5:
                mood[key] = max(0, min(10, round(mood[key] + d, 1)))
                changed = True
        if changed:
            self.memory_db.set_user_mood(user_id, mood)

    def _get_mood_state(self, user_id: str) -> dict:
        """获取当前心情（含时间衰减），用于注入 prompt"""
        mood = self._apply_mood_decay(user_id)
        return {k: round(v) for k, v in mood.items()}

    def _release_missing_if_expressed(self, user_id: str, response: str):
        """bot 回复中表达了想念 → missing -0.5（一条消息只减一次）"""
        keywords = ["想你", "想念", "好想你", "想你了"]
        if any(kw in response for kw in keywords):
            mood = self.memory_db.get_user_mood(user_id)
            old = mood.get("missing", 3)
            mood["missing"] = max(0, round(old - 0.5, 1))
            self.memory_db.set_user_mood(user_id, mood)
            logger.info(f"表达释放: missing {old} → {mood['missing']}")

    def _track_response(self, elapsed: float):
        """记录响应时间和今日消息数"""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.stats.get("today_date") != today:
            self.stats["today_messages"] = 0
            self.stats["today_date"] = today
        self.stats["today_messages"] += 1
        self.stats["total_response_time"] = self.stats.get("total_response_time", 0) + elapsed

    def _get_avg_response_time(self) -> float:
        total = self.stats.get("successful_responses", 0)
        if total <= 0:
            return 0.0
        return self.stats.get("total_response_time", 0) / total

    @staticmethod
    def _extract_json_safe(text: str) -> dict:
        from ai_memory_manager import _extract_json
        return _extract_json(text) or {}

    async def _do_compact(self, user_id: str, since: str) -> tuple:
        """执行日记总结，返回 (title, content) 或 (None, None)"""
        messages = self.memory_db.get_messages_since_clear(user_id, since)
        if not messages:
            recent = self.memory_db.get_recent_conversation(user_id, limit=200)
            messages = [(r, c) for r, c in recent]
        if not messages:
            return None, None
        chat_text = "\n".join([f"{'用户' if r == 'user' else 'bot'}: {c[:200]}" for r, c in messages[-200:]])
        summary_prompt = f"""你是一个写日记的人工智能角色。请用第一人称"我"的视角，以简洁自然的语气，把下面这段对话记录总结成一篇短小的日记。
要求：1. 100-300字 2. 用自然的日记口吻，像是睡前随手写的 3. 只写日记正文，不要任何前缀标记
对话记录：{chat_text}
同时，请为这篇日记生成一个标题（少于10个字，关键词堆积形式，如"聊了很久很开心"）。
仅输出JSON格式：{{"title": "标题","content": "日记正文"}}"""
        llm_messages = [
            {"role": "system", "content": "你是一个写日记的角色。请严格按照要求输出JSON格式的日记总结。"},
            {"role": "user", "content": summary_prompt}
        ]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self.llm_manager.client.chat,
            llm_messages, 0.5, 512, "deepseek-v4-flash", {"type": "disabled"}
        )
        data = self._extract_json_safe(result)
        title = data.get("title", "日记")[:10]
        content = data.get("content", result[:300])[:500]
        return title, content

    async def _process_compact_async(self, user_id: str, since: str, status_msg):
        try:
            title, content = await self._do_compact(user_id, since)
            if not title:
                await status_msg.edit_text("已没有对话可总结~")
                return
            self.memory_db.create_compact_record(user_id, title, content)
            await status_msg.edit_text(f"日记写好啦！\n\n*{title}*\n\n{content}\n\n`/compact list` 可查看所有日记",
                                       parse_mode='Markdown')
        except Exception as e:
            try:
                await status_msg.edit_text(f"写日记出错了: {e}")
            except Exception:
                pass

    async def _show_compact_page(self, update_or_query, user_id: str, page: int = 1):
        records = self.memory_db.get_compact_records(user_id)
        if not records:
            text = "还没有日记记录~\n使用 `/compact` 生成第一篇日记吧"
            if hasattr(update_or_query, 'message'):
                await update_or_query.message.reply_text(text)
            else:
                await update_or_query.edit_message_text(text)
            return
        per_page = 10
        total = len(records)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = min(start + per_page, total)
        page_records = records[start:end]
        lines = [f"日记列表 ({total} 篇，第 {page}/{total_pages} 页):"]
        for i, (rid, rtitle, rtime) in enumerate(page_records, start + 1):
            lines.append(f"{i}. {rtime[:16]} — {rtitle[:15]}")
        text = "\n".join(lines)
        buttons = []
        for i, (rid, rtitle, rtime) in enumerate(page_records, start + 1):
            buttons.append([InlineKeyboardButton(f"{i}. {rtitle[:20]}", callback_data=f"compact_view:{rid}")])
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀ 上一页", callback_data=f"compact_page:{page - 1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("下一页 ▶", callback_data=f"compact_page:{page + 1}"))
        if nav:
            buttons.append(nav)
        kb = InlineKeyboardMarkup(buttons)
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(text, reply_markup=kb)
        else:
            await update_or_query.edit_message_text(text, reply_markup=kb)

    async def _show_compact_list(self, update_or_query, user_id: str):
        await self._show_compact_page(update_or_query, user_id, 1)

    async def _show_status_tab(self, update_or_query, user_id: str, tab: str):
        tabs = {
            "overview": ("运行概况", self._status_overview),
            "data": ("数据统计", self._status_data),
            "history": ("最近对话", self._status_history),
            "mood": ("心情", self._status_mood),
        }
        label, handler = tabs.get(tab, tabs["overview"])
        text = handler(user_id)
        tab_names = list(tabs.keys())
        btn_row = []
        for key in tab_names:
            if key == tab:
                btn_row.append(InlineKeyboardButton(f"• {tabs[key][0]} •", callback_data="noop"))
            else:
                btn_row.append(InlineKeyboardButton(tabs[key][0], callback_data=f"status:{key}"))
        kb = InlineKeyboardMarkup([btn_row])
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(text, reply_markup=kb)
        else:
            await update_or_query.edit_message_text(text, reply_markup=kb)

    def _status_overview(self, user_id: str) -> str:
        status = self.get_status()
        thinking = self.llm_manager.get_thinking_status()
        if thinking["enabled"]:
            thinking_str = f"开启 (强度: {thinking['effort']})"
        else:
            thinking_str = "关闭"
        today = self.stats.get("today_messages", 0)
        return f"""Bot状态 · 运行概况
运行时间: {status['uptime']}
今日消息: {today} / 总计: {status['total_messages']}
成功率: {status['success_rate']:.1%}
平均响应: {self._get_avg_response_time():.1f}s
数据库: {status['memory_db_size']}
模型: {status['config']['model']}  温度: {status['config']['temperature']}
思考: {thinking_str}"""

    def _status_data(self, user_id: str) -> str:
        stats = self.memory_db.get_memory_stats(user_id)
        types = stats.get("memory_types", {})
        type_lines = "\n".join([f"  {k}: {v}" for k, v in sorted(types.items())]) if types else "  无"
        lc = stats.get("last_clear") or "从未"
        lcp = stats.get("last_compact")
        lcp_str = f"{lcp['title']} ({lcp['time'][:16]})" if lcp else "无"
        return f"""Bot状态 · 数据统计
对话条数: {stats['conversations']}
长期记忆: {stats['memories']}
日记总结: {stats['compacts']}
记忆类型分布:
{type_lines}
上次 clear: {lc}
最近日记: {lcp_str}"""

    def _status_history(self, user_id: str) -> str:
        recent = self.memory_db.get_recent_conversation(user_id, limit=10)
        if not recent:
            return "Bot状态 · 最近对话\n\n暂无对话记录~"
        lines = ["Bot状态 · 最近对话\n"]
        for role, content in recent[-10:]:
            prefix = "你说" if role == "user" else "bot说"
            short = content[:60] + "..." if len(content) > 60 else content
            lines.append(f"  {prefix}: {short}")
        return "\n".join(lines)

    def _status_mood(self, user_id: str) -> str:
        mood = self._get_mood_state(user_id)
        def bar(v): return "█" * (v // 2) + "░" * (5 - v // 2)
        erotic = self.memory_db.get_erotic_state(user_id)
        em_str = "活跃中" if erotic.get("active") else "正常"
        return f"""Bot状态 · 心情
开心: {bar(mood['happiness'])} {mood['happiness']}/10
想念: {bar(mood['missing'])} {mood['missing']}/10
精力: {bar(mood['energy'])} {mood['energy']}/10
生气: {bar(mood['anger'])} {mood['anger']}/10
性欲: {bar(mood['arousal'])} {mood['arousal']}/10
文爱状态: {em_str}"""

    async def compact_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = str(user.id)
        if not self._is_user_allowed(int(user_id)):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return
        args = context.args
        if args and args[0] == "list":
            await self._show_compact_list(update, user_id)
            return
        since = self.memory_db.get_last_clear_at(user_id)
        messages = self.memory_db.get_messages_since_clear(user_id, since)
        if not messages:
            await update.message.reply_text("自上次 /clear 以来还没有对话记录~")
            return
        status_msg = await update.message.reply_text("正在写日记...")
        asyncio.create_task(self._process_compact_async(user_id, since, status_msg))

    async def continue_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/continue命令 - bot自行生成下一条回复，不需要用户发言"""
        user = update.effective_user
        user_id = str(user.id)

        if not self._is_user_allowed(int(user_id)):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        recent = self.memory_db.get_recent_conversation(user_id, limit=10)
        if not recent:
            await update.message.reply_text("还没有对话历史呢~ 先聊几句吧")
            return

        try:
            await update.message.chat.send_action(action="typing")
        except Exception:
            pass

        try:
            continue_prompt = ("（请以你的角色身份，基于以上对话的上下文和当前心情，自然地继续对话。"
                               "你是在对用户说话，不是代用户发言。不要重复刚才说过的话，不要切换到用户视角）")
            messages = self.prompt_engine.build_messages(user_id, continue_prompt, self.memory_db, self._get_mood_state(user_id))
            start_time = time.time()
            response = self.llm_manager.generate_response(messages)
            elapsed_time = time.time() - start_time
            logger.info(f"继续对话生成耗时: {elapsed_time:.2f}s")
            self._release_missing_if_expressed(user_id, response)

            bot_db_id = self.memory_db.add_message(user_id, "assistant", response)
            if bot_db_id:
                self._bot_db_ids[user_id] = bot_db_id

            sent_msg = await update.message.reply_text(response)
            if bot_db_id:
                self.memory_db._update_tg_msg_id(bot_db_id, sent_msg.message_id)
            self._bot_reply_ids[user_id] = sent_msg.message_id

            logger.info(f"继续对话回复 [{user.full_name}]: {response[:50]}...")
            self.stats["successful_responses"] += 1
            self._track_response(elapsed_time)
            self.stats["total_messages"] += 1
        except Exception as e:
            logger.error(f"继续对话失败: {e}", exc_info=True)
            try:
                await update.message.reply_text(f"继续对话出错: {e}")
            except Exception:
                pass
            self.stats["failed_responses"] += 1

    async def suggest_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/suggest命令 - 并行调用3路API生成候选用户回复，按钮选择"""
        user = update.effective_user
        user_id = str(user.id)

        if not self._is_user_allowed(int(user_id)):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        recent = self.memory_db.get_recent_conversation(user_id, limit=50)
        if not recent:
            await update.message.reply_text("还没有对话历史呢~ 先聊几句吧")
            return

        status_msg = await update.message.reply_text("正在生成候选回复...")

        # ── 手动构建上下文（只取最近50条对话） ──
        messages = []
        user_memories = self.memory_db.get_user_memories(user_id, limit=None)
        messages.append({"role": "system", "content": self.prompt_engine._build_system_prompt(user_memories)})

        recent = self.memory_db.get_recent_conversation(user_id, limit=50)
        for role, content in recent:
            messages.append({"role": role, "content": content})

        gen_instruction = ("【生成任务】你是对话中的\"用户\"，不是bot。请以上面完整的对话历史为上下文，"
                           "以用户的身份和口吻，生成用户接下来可能会对bot说的话。"
                           "硬性要求：\n"
                           "1）动作用()表示，如（抱抱）（笑）\n"
                           "2）10-20字，尽量短\n"
                           "3）只输出纯回复文本，不要\"用户:\"\"我说:\"等前缀，不要引号包裹\n"
                           "4）必须是用户对bot说的话，绝对不能是bot对用户说的话\n"
                           "5）不要重复对话里已经出现过的话\n"
                           "6）内容要符合对话中用户的人设")
        messages.append({"role": "user", "content": gen_instruction})

        # ── 并行3路LLM调用 ──
        async def _single_call(index: int):
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self.llm_manager.client.chat,
                    messages,
                    self.config["advanced"]["temperature"] + 0.1,
                    min(self.config["advanced"]["max_tokens_per_response"], 128),
                    self.llm_manager.model,
                    None  # suggest 用非思考模式，速度快
                )
                return result.strip()
            except Exception as e:
                logger.warning(f"候选回复生成[{index}]失败: {e}")
                return None

        tasks = [_single_call(i) for i in range(3)]
        candidates = await asyncio.gather(*tasks)

        # 过滤空结果
        valid = [c for c in candidates if c and len(c) >= 2]
        if len(valid) < 2:
            await status_msg.edit_text("生成候选回复失败了~ 再来一次吧")
            return

        self._suggestions[user_id] = valid[:3]

        # 构建展示文本
        lines = ["选一条作为你的回复：\n"]
        for i, text in enumerate(valid[:3], 1):
            lines.append(f"{i}. {text}")
        display_text = "\n".join(lines)

        # 构建按钮（只显示实际可用数量）
        btn_row = []
        for i in range(len(valid[:3])):
            btn_row.append(InlineKeyboardButton(f"选项{i+1}", callback_data=f"suggest:{i}"))
        kb_rows = [btn_row, [InlineKeyboardButton("取消", callback_data="suggest:cancel")]]

        await status_msg.edit_text(
            display_text,
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )

    async def _process_suggestion_selection(self, query, user_id: int, choice_index: int):
        """用户选择候选回复后的处理"""
        user_id_str = str(user_id)
        candidates = self._suggestions.pop(user_id_str, None)
        if not candidates or choice_index >= len(candidates):
            await query.answer("候选已过期，请重新 /suggest", show_alert=True)
            return

        chosen_text = candidates[choice_index]

        # 移除按钮，显示选中的回复
        await query.edit_message_text(f"你说: {chosen_text}", reply_markup=None)
        await query.answer()

        # 存入 DB
        user_msg_db_id = self.memory_db.add_message(user_id_str, "user", chosen_text)

        # 生成 bot 回复
        try:
            messages = self.prompt_engine.build_messages(user_id_str, chosen_text, self.memory_db, self._get_mood_state(user_id_str))
            start_time = time.time()
            response = self.llm_manager.generate_response(messages)
            elapsed_time = time.time() - start_time
            logger.info(f"候选选择后生成耗时: {elapsed_time:.2f}s")
            self._release_missing_if_expressed(user_id_str, response)

            bot_db_id = self.memory_db.add_message(user_id_str, "assistant", response)
            if bot_db_id:
                self._bot_db_ids[user_id_str] = bot_db_id

            sent_msg = await query.message.reply_text(response)
            if bot_db_id:
                self.memory_db._update_tg_msg_id(bot_db_id, sent_msg.message_id)
            self._bot_reply_ids[user_id_str] = sent_msg.message_id

            self.stats["successful_responses"] += 1
            self._track_response(elapsed_time)
            self.stats["total_messages"] += 1

            asyncio.create_task(self._process_arousal_async(user_id_str, chosen_text, user_msg_db_id))
        except Exception as e:
            logger.error(f"候选选择后生成失败: {e}", exc_info=True)
            try:
                await query.message.reply_text(f"生成回复出错: {e}")
            except Exception:
                pass
            self.stats["failed_responses"] += 1

    async def mood_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/mood命令 - 查看当前心情"""
        user = update.effective_user
        user_id = str(user.id)

        if not self._is_user_allowed(int(user_id)):
            await update.message.reply_text("抱歉，您没有被授权使用此机器人。")
            return

        mood = self._get_mood_state(user_id)
        def bar(v): return "█" * (v // 2) + "░" * (5 - v // 2)
        text = f"""当前心情

开心: {bar(mood['happiness'])} {mood['happiness']}/10
想念: {bar(mood['missing'])} {mood['missing']}/10
精力: {bar(mood['energy'])} {mood['energy']}/10（值越高精力越好）
生气: {bar(mood['anger'])} {mood['anger']}/10
性欲: {bar(mood['arousal'])} {mood['arousal']}/10"""
        await update.message.reply_text(text)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """统一分发所有 inline button 回调"""
        query = update.callback_query
        data = query.data
        user_id = update.effective_user.id

        if not self._is_user_allowed(user_id):
            await query.answer("无权限", show_alert=True)
            return

        # ── 思考模式按钮 ──
        if data.startswith("think:"):
            mode = data.split(":", 1)[1]
            if mode == "high":
                self.llm_manager.set_thinking(enabled=True, effort="high")
                await query.answer("已设置: 高强度思考")
            elif mode == "max":
                self.llm_manager.set_thinking(enabled=True, effort="max")
                await query.answer("已设置: 最大强度思考")
            elif mode == "off":
                self.llm_manager.set_thinking(enabled=False)
                await query.answer("已关闭思考模式")
            await query.edit_message_reply_markup(reply_markup=None)

        # ── 记忆删除按钮 ──
        elif data.startswith("delmem:"):
            try:
                _, mem_id_str, page_str = data.split(":")
                mem_id = int(mem_id_str)
                page = int(page_str)
            except (ValueError, IndexError):
                await query.answer("参数错误", show_alert=True)
                return

            if self.memory_db.delete_memory_by_id(str(user_id), mem_id):
                await query.answer("已删除")
            else:
                await query.answer("删除失败", show_alert=True)
                return

            # 刷新当前页
            await self._show_memory_page(query, user_id, page)

        # ── 记忆翻页按钮 ──
        elif data.startswith("delmem_page:"):
            try:
                page = int(data.split(":", 1)[1])
            except (ValueError, IndexError):
                await query.answer("参数错误", show_alert=True)
                return

            await self._show_memory_page(query, user_id, page)

        elif data == "noop":
            await query.answer()

        # ── 候选回复选择按钮 ──
        elif data.startswith("suggest:"):
            choice = data.split(":", 1)[1]
            if choice == "cancel":
                self._suggestions.pop(str(user_id), None)
                await query.edit_message_text("已取消", reply_markup=None)
                await query.answer()
            else:
                try:
                    idx = int(choice)
                    await self._process_suggestion_selection(query, user_id, idx)
                except (ValueError, IndexError):
                    await query.answer("选项无效", show_alert=True)

        # ── compact 日记按钮 ──
        elif data.startswith("compact_view:"):
            try:
                rid = int(data.split(":", 1)[1])
                record = self.memory_db.get_compact_record(rid)
                if not record or record["user_id"] != str(user_id):
                    await query.answer("记录不存在", show_alert=True)
                    return
                text = f"*{record['title']}*\n_{record['created_at']}_\n\n{record['content']}"
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀ 返回列表", callback_data="compact_list"),
                    InlineKeyboardButton("删除", callback_data=f"compact_delete:{rid}")
                ]])
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)
                await query.answer()
            except (ValueError, IndexError):
                await query.answer("参数错误", show_alert=True)

        elif data == "compact_list":
            await self._show_compact_list(query, str(user_id))

        elif data.startswith("compact_page:"):
            try:
                page = int(data.split(":", 1)[1])
                await self._show_compact_page(query, str(user_id), page)
            except (ValueError, IndexError):
                await query.answer("参数错误", show_alert=True)

        elif data.startswith("compact_delete:"):
            try:
                rid = int(data.split(":", 1)[1])
                if self.memory_db.delete_compact_record(rid, str(user_id)):
                    await query.answer("已删除")
                else:
                    await query.answer("删除失败", show_alert=True)
                    return
                await self._show_compact_list(query, str(user_id))
            except (ValueError, IndexError):
                await query.answer("参数错误", show_alert=True)

        # ── clear 总结选择按钮 ──
        elif data.startswith("clear:"):
            choice = data.split(":", 1)[1]
            if choice == "cancel":
                await query.edit_message_text("已取消", reply_markup=None)
                await query.answer()
            elif choice in ("compact", "direct"):
                uid = str(user_id)
                title = content = None
                if choice == "compact":
                    await query.edit_message_text("正在总结...", reply_markup=None)
                    since = self.memory_db.get_last_clear_at(uid)
                    try:
                        title, content = await self._do_compact(uid, since)
                        if title:
                            self.memory_db.create_compact_record(uid, title, content)
                    except Exception:
                        pass
                else:
                    await query.edit_message_text("正在清除...", reply_markup=None)
                deleted = self.memory_db.clear_user_conversation(uid)
                self.memory_db.record_last_clear(uid)
                if title:
                    await query.edit_message_text(f"日记已保存，已清除 {deleted} 条对话\n\n*{title}*\n_{content[:200]}_",
                                                  parse_mode='Markdown')
                else:
                    await query.edit_message_text(f"已清除 {deleted} 条对话历史")
                await query.answer()

        # ── status tab 切换 ──
        elif data.startswith("status:"):
            tab = data.split(":", 1)[1]
            await self._show_status_tab(query, str(user_id), tab)

        else:
            await query.answer("未知操作", show_alert=True)

    async def _show_memory_page(self, query, user_id: int, page: int):
        """显示记忆列表的某一页（每页10条），通过 inline keyboard 实现删除和翻页"""
        uid = str(user_id)
        memories = self.memory_db.get_user_memories_with_id(uid)

        if not memories:
            await query.edit_message_text("已经没有长期记忆了~")
            return

        total = len(memories)
        per_page = 10
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))

        start = (page - 1) * per_page
        end = min(start + per_page, total)
        page_memories = memories[start:end]

        lines = [f"长期记忆 ({total} 条，第 {page}/{total_pages} 页):"]
        for i, (mem_id, mem_type, content, importance) in enumerate(page_memories, start + 1):
            short = content[:50] + "..." if len(content) > 50 else content
            type_emoji = {"personal": "[个人]", "preference": "[喜好]", "event": "[事件]",
                          "emotion": "[情感]", "fact": "[事实]"}.get(mem_type, "[其他]")
            lines.append(f"{i}. {type_emoji} [{mem_type}] {short} (重要度:{importance})")

        text = "\n".join(lines)

        # 构建按钮：每条记忆一行一个删除按钮
        button_rows = []
        for i, (mem_id, mem_type, content, importance) in enumerate(page_memories, start + 1):
            short = content[:30]
            button_rows.append([InlineKeyboardButton(
                f"删除 #{i}: {short}", callback_data=f"delmem:{mem_id}:{page}"
            )])

        # 翻页按钮
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀ 上一页", callback_data=f"delmem_page:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("下一页 ▶", callback_data=f"delmem_page:{page + 1}"))
        button_rows.append(nav_row)

        kb = InlineKeyboardMarkup(button_rows)

        try:
            await query.edit_message_text(text, reply_markup=kb)
        except Exception:
            await query.edit_message_text(
                text[:4000] + "\n...（内容过长截断）", reply_markup=kb
            )

    def run(self):
        """运行Telegram机器人（同步入口）"""
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop

        try:
            # 检查Telegram API连接
            async def check_conn():
                return await self._check_telegram_connection()

            if not loop.run_until_complete(check_conn()):
                logger.warning("Telegram API连接测试失败，继续尝试启动...")

            # 创建应用，设置超时和代理
            request_kwargs = {
                "connect_timeout": self.connect_timeout,
                "read_timeout": self.read_timeout
            }
            if self.proxy_url:
                request_kwargs["proxy_url"] = self.proxy_url
                logger.info(f"使用代理: {self.proxy_url}")

            request = HTTPXRequest(**request_kwargs)
            self.application = Application.builder().token(self.bot_token).request(request).build()

            # 设置命令菜单
            loop.run_until_complete(self.setup_commands(self.application))

            # 注册处理器
            self.register_handlers(self.application)

            # 发送启动通知（如果配置了管理员用户ID）
            admin_ids = self.config["telegram"].get("admin_user_ids", [])
            if admin_ids:
                async def send_notifications():
                    for admin_id in admin_ids:
                        try:
                            await self.application.bot.send_message(
                                chat_id=admin_id,
                                text=f"Telegram机器人启动成功！\n启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                        except Exception as e:
                            logger.warning(f"无法发送启动通知给 {admin_id}: {e}")
                loop.run_until_complete(send_notifications())

            logger.info("Telegram机器人已启动，等待消息...")

            # 开始轮询（阻塞式）
            loop.run_until_complete(self.application.run_polling(allowed_updates=Update.ALL_TYPES))

        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭...")
        except Exception as e:
            logger.error(f"机器人运行异常: {e}", exc_info=True)
        finally:
            # 关闭清理
            loop.run_until_complete(self.shutdown())
            loop.close()

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        retry=tenacity.retry_if_exception_type((TimedOut, NetworkError)),
        before_sleep=lambda retry_state: logger.warning(f"重试设置命令菜单，尝试次数: {retry_state.attempt_number}")
    )
    async def setup_commands(self, application: Application):
        """设置机器人命令菜单

        Args:
            application: Telegram应用实例
        """
        commands = [
            BotCommand("suggest", "生成3条候选回复供选择"),
            BotCommand("mood", "查看当前心情"),
            BotCommand("continue", "让bot继续独自生成下一条回复"),
            BotCommand("regenerate", "重新生成上一轮回复"),
            BotCommand("clear", "清除对话历史（短期记忆）"),
            BotCommand("clear_memories", "清除长期记忆(警告)"),
            BotCommand("thinking", "思考模式 (按钮版)"),
            BotCommand("help", "显示帮助信息"),
            BotCommand("status", "显示机器人状态"),
            BotCommand("start", "开始使用机器人"),
            BotCommand("compact", "日记总结对话 (/compact list 查看历史)"),
        ]

        await application.bot.set_my_commands(commands)
        logger.info("机器人命令菜单设置完成")

    def register_handlers(self, application: Application):
        """注册消息处理器

        Args:
            application: Telegram应用实例
        """
        # 命令处理器
        application.add_handler(CommandHandler("suggest", self.suggest_command))
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(CommandHandler("clear_memories", self.clear_memories_command))
        application.add_handler(CommandHandler("confirm_clear_memories", self.confirm_clear_memories_command))
        application.add_handler(CommandHandler("list_memories", self.list_memories_command))
        application.add_handler(CommandHandler("delete_memory", self.delete_memory_command))
        application.add_handler(CommandHandler("thinking", self.thinking_command))
        application.add_handler(CommandHandler("regenerate", self.regenerate_command))
        application.add_handler(CommandHandler("continue", self.continue_command))
        application.add_handler(CommandHandler("compact", self.compact_command))
        application.add_handler(CommandHandler("mood", self.mood_command))

        # 文本消息处理器
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))

        # 按钮回调处理器
        application.add_handler(CallbackQueryHandler(self.handle_callback))

        logger.info("消息处理器注册完成")


    async def shutdown(self):
        """关闭机器人"""
        logger.info("正在关闭机器人...")

        # 保存统计信息
        self._save_stats()

        # 关闭数据库
        if hasattr(self, 'memory_db'):
            self.memory_db.close()

        # 清理事件循环引用
        self.loop = None

        logger.info("机器人已关闭")

    def _save_stats(self):
        """保存统计信息"""
        stats_file = "bot_stats.json"
        try:
            import json
            from datetime import datetime

            # 转换datetime对象为字符串
            def json_serializer(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")

            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump(self.stats, f, default=json_serializer, ensure_ascii=False, indent=2)
            logger.info(f"统计信息已保存到 {stats_file}")
        except Exception as e:
            logger.error(f"保存统计信息失败: {e}")

    def get_status(self) -> Dict:
        """获取机器人状态

        Returns:
            状态字典
        """
        uptime = datetime.now() - self.stats["start_time"]
        hours, remainder = divmod(uptime.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)

        return {
            "status": "running",
            "uptime": f"{int(hours)}小时{int(minutes)}分钟{int(seconds)}秒",
            "total_messages": self.stats["total_messages"],
            "success_rate": (
                self.stats["successful_responses"] / self.stats["total_messages"]
                if self.stats["total_messages"] > 0 else 0
            ),
            "memory_db_size": self._get_db_size(),
            "config": {
                "model": self.config["llm"]["model"],
                "temperature": self.config["advanced"]["temperature"]
            }
        }

    def _get_db_size(self) -> str:
        """获取数据库大小"""
        try:
            import os
            db_path = self.config["memory"]["db_path"]
            if os.path.exists(db_path):
                size_bytes = os.path.getsize(db_path)
                if size_bytes < 1024:
                    return f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.1f} KB"
                else:
                    return f"{size_bytes / (1024 * 1024):.1f} MB"
            return "0 B"
        except:
            return "未知"

    async def _check_telegram_connection(self) -> bool:
        """检查Telegram API连接

        Returns:
            True如果连接成功
        """
        try:
            import httpx
            import asyncio

            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"

            client_kwargs = {"timeout": self.connect_timeout}
            if self.proxy_url:
                client_kwargs["proxy"] = self.proxy_url
                logger.info(f"连接测试使用代理: {self.proxy_url}")

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    logger.info("Telegram API连接测试成功")
                    return True
                else:
                    logger.warning(f"Telegram API连接测试失败: HTTP {response.status_code}")
                    return False
        except Exception as e:
            logger.warning(f"Telegram API连接测试异常: {e}")
            return False


def create_telegram_bot(config_path: str = "config/config.yaml") -> TelegramBot:
    """创建Telegram机器人实例

    Args:
        config_path: 配置文件路径

    Returns:
        Telegram机器人实例
    """
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return TelegramBot(config)


if __name__ == "__main__":
    # 测试机器人
    print("测试Telegram机器人...")

    # 创建测试配置
    test_config = {
        "llm": {
            "api_key": "test_key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat"
        },
        "telegram": {
            "bot_token": "test_token",
            "allowed_user_ids": [],
            "enable_group_chat": False,
            "admin_user_ids": []
        },
        "memory": {
            "db_path": "test_memory.db"
        },
        "prompt": {
            "max_prompt_length": 6000,
            "include_recent_messages": 10
        },
        "advanced": {
            "temperature": 0.7,
            "max_tokens_per_response": 1024,
            "retry_attempts": 3,
            "timeout_seconds": 30
        }
    }

    try:
        bot = TelegramBot(test_config)
        print("机器人创建成功")
        print(f"状态: {bot.get_status()}")
    except Exception as e:
        print(f"机器人创建失败: {e}")