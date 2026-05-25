#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长期记忆数据库
使用SQLite存储对话历史和用户记忆
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import List, Tuple, Optional
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MemoryDB:
    def __init__(self, db_path: str = "memory.db"):
        """初始化记忆数据库

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self):
        """连接数据库"""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row  # 返回字典格式
            logger.info(f"已连接数据库: {self.db_path}")
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            raise

    def create_tables(self):
        """创建数据库表"""
        cursor = self.conn.cursor()

        # 对话历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,  -- 'user' 或 'assistant'
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_important INTEGER DEFAULT 0,  -- 是否重要消息
                telegram_msg_id INTEGER  -- 对应的Telegram消息ID
            )
        """)

        # 尝试添加 telegram_msg_id 列（兼容旧数据库）
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN telegram_msg_id INTEGER")
        except sqlite3.OperationalError:
            pass  # 列已存在

        # 尝试添加文爱状态快照列（兼容旧数据库）
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN erotic_active INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN erotic_enter_count INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN erotic_exit_count INTEGER")
        except sqlite3.OperationalError:
            pass

        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_id
            ON conversations (user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON conversations (timestamp)
        """)

        # 用户记忆表（存储重要信息）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,  -- 'preference', 'event', 'fact'
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 1,  -- 重要性 1-10
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_accessed DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 用户信息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_info (
                user_id TEXT PRIMARY KEY,
                nickname TEXT,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                total_messages INTEGER DEFAULT 0,
                settings TEXT DEFAULT '{}'  -- JSON格式的用户设置
            )
        """)

        # compact 对话总结表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compact_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()
        logger.info("数据库表创建完成")

    def add_message(self, user_id: str, role: str, content: str, is_important: bool = False,
                    telegram_msg_id: Optional[int] = None) -> Optional[int]:
        """添加消息到对话历史

        Args:
            user_id: 用户ID
            role: 角色 ('user' 或 'assistant')
            content: 消息内容
            is_important: 是否重要消息
            telegram_msg_id: Telegram消息ID（用于编辑功能追溯）

        Returns:
            新插入记录的自增ID，失败返回 None
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (user_id, role, content, is_important, telegram_msg_id)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, role, content, 1 if is_important else 0, telegram_msg_id))

            # 更新用户最后活跃时间
            self.update_user_last_seen(user_id)

            self.conn.commit()
            logger.debug(f"已添加消息: {user_id} - {role}")
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"添加消息失败: {e}")
            self.conn.rollback()
            return None

    def get_recent_conversation(self, user_id: str, limit: int = 10) -> List[Tuple[str, str]]:
        """获取最近的对话历史

        Args:
            user_id: 用户ID
            limit: 返回的最大消息数

        Returns:
            消息列表，格式为 [(role, content), ...]
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT role, content FROM conversations
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, limit))

            rows = cursor.fetchall()
            # 返回按时间顺序排列的消息（最早的在前）
            rows.reverse()
            return [(row[0], row[1]) for row in rows]
        except Exception as e:
            logger.error(f"获取对话历史失败: {e}")
            return []

    def add_user_memory(self, user_id: str, memory_type: str, content: str, importance: int = 5):
        """添加用户记忆

        Args:
            user_id: 用户ID
            memory_type: 记忆类型 ('preference', 'event', 'fact')
            content: 记忆内容
            importance: 重要性 (1-10)
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO user_memories (user_id, memory_type, content, importance)
                VALUES (?, ?, ?, ?)
            """, (user_id, memory_type, content, importance))

            self.conn.commit()
            logger.info(f"已添加记忆: {user_id} - {memory_type}")

            # 修剪记忆，保持每个用户最多50条记忆
            self.prune_user_memories(user_id, max_memories=50)
        except Exception as e:
            logger.error(f"添加记忆失败: {e}")
            self.conn.rollback()

    def prune_user_memories(self, user_id: str, max_memories: int = 50):
        """修剪用户记忆，保留最重要的记忆

        Args:
            user_id: 用户ID
            max_memories: 最大记忆数量
        """
        try:
            cursor = self.conn.cursor()

            # 计算当前记忆数量
            cursor.execute("""
                SELECT COUNT(*) FROM user_memories WHERE user_id = ?
            """, (user_id,))
            current_count = cursor.fetchone()[0]

            if current_count <= max_memories:
                return

            # 找出要删除的记忆ID（重要性最低的）
            cursor.execute("""
                SELECT id FROM user_memories
                WHERE user_id = ?
                ORDER BY importance ASC, last_accessed ASC
                LIMIT ?
            """, (user_id, current_count - max_memories))

            ids_to_delete = [row[0] for row in cursor.fetchall()]

            if not ids_to_delete:
                return

            # 删除记忆
            placeholders = ','.join(['?'] * len(ids_to_delete))
            cursor.execute(f"""
                DELETE FROM user_memories
                WHERE id IN ({placeholders})
            """, ids_to_delete)

            self.conn.commit()
            logger.info(f"已修剪用户 {user_id} 的记忆，删除了 {len(ids_to_delete)} 条，保留 {max_memories} 条")

        except Exception as e:
            logger.error(f"修剪用户记忆失败: {e}")
            self.conn.rollback()

    def get_user_memories(self, user_id: str, memory_type: str = None, limit: int = None) -> List[str]:
        """获取用户记忆

        Args:
            user_id: 用户ID
            memory_type: 记忆类型过滤（可选）
            limit: 返回的最大记忆数，None表示无限制

        Returns:
            记忆内容列表
        """
        try:
            cursor = self.conn.cursor()

            if limit is not None and limit > 0:
                if memory_type:
                    cursor.execute("""
                        SELECT content FROM user_memories
                        WHERE user_id = ? AND memory_type = ?
                        ORDER BY importance DESC, last_accessed DESC
                        LIMIT ?
                    """, (user_id, memory_type, limit))
                else:
                    cursor.execute("""
                        SELECT content FROM user_memories
                        WHERE user_id = ?
                        ORDER BY importance DESC, last_accessed DESC
                        LIMIT ?
                    """, (user_id, limit))
                # 更新最后访问时间
                rows = cursor.fetchall()
                if rows:
                    cursor.execute("""
                        UPDATE user_memories
                        SET last_accessed = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND id IN (
                            SELECT id FROM user_memories
                            WHERE user_id = ?
                            ORDER BY importance DESC
                            LIMIT ?
                        )
                    """, (user_id, user_id, limit))
                    self.conn.commit()
            else:
                # 无限制读取所有记忆
                if memory_type:
                    cursor.execute("""
                        SELECT content FROM user_memories
                        WHERE user_id = ? AND memory_type = ?
                        ORDER BY importance DESC, last_accessed DESC
                    """, (user_id, memory_type))
                else:
                    cursor.execute("""
                        SELECT content FROM user_memories
                        WHERE user_id = ?
                        ORDER BY importance DESC, last_accessed DESC
                    """, (user_id,))
                rows = cursor.fetchall()
                # 更新所有访问过的记忆的访问时间
                if rows:
                    cursor.execute("""
                        UPDATE user_memories
                        SET last_accessed = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                    """, (user_id,))
                    self.conn.commit()

            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"获取记忆失败: {e}")
            return []

    def get_user_memories_with_id(self, user_id: str, memory_type: str = None) -> List[Tuple[int, str, str, int]]:
        """获取用户记忆（带ID，用于列出和删除）

        Args:
            user_id: 用户ID
            memory_type: 记忆类型过滤（可选）

        Returns:
            记忆列表，格式为 [(id, memory_type, content, importance), ...]
        """
        try:
            cursor = self.conn.cursor()

            if memory_type:
                cursor.execute("""
                    SELECT id, memory_type, content, importance FROM user_memories
                    WHERE user_id = ? AND memory_type = ?
                    ORDER BY importance DESC, last_accessed DESC
                """, (user_id, memory_type))
            else:
                cursor.execute("""
                    SELECT id, memory_type, content, importance FROM user_memories
                    WHERE user_id = ?
                    ORDER BY importance DESC, last_accessed DESC
                """, (user_id,))

            rows = cursor.fetchall()
            return [(row[0], row[1], row[2], row[3]) for row in rows]
        except Exception as e:
            logger.error(f"获取记忆列表失败: {e}")
            return []

    def delete_memory_by_id(self, user_id: str, memory_id: int) -> bool:
        """删除指定ID的记忆

        Args:
            user_id: 用户ID（用于验证权限）
            memory_id: 记忆ID

        Returns:
            是否成功删除
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                DELETE FROM user_memories
                WHERE id = ? AND user_id = ?
            """, (memory_id, user_id))

            deleted = cursor.rowcount > 0
            self.conn.commit()

            if deleted:
                logger.info(f"已删除记忆 {memory_id}")
            else:
                logger.warning(f"删除记忆失败：ID {memory_id} 不存在或不属于用户 {user_id}")
            return deleted
        except Exception as e:
            logger.error(f"删除记忆失败: {e}")
            self.conn.rollback()
            return False

    def update_user_last_seen(self, user_id: str):
        """更新用户最后活跃时间

        Args:
            user_id: 用户ID
        """
        try:
            cursor = self.conn.cursor()

            # 检查用户是否存在
            cursor.execute("SELECT 1 FROM user_info WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                # 更新现有用户
                cursor.execute("""
                    UPDATE user_info
                    SET last_seen = CURRENT_TIMESTAMP,
                        total_messages = total_messages + 1
                    WHERE user_id = ?
                """, (user_id,))
            else:
                # 创建新用户
                cursor.execute("""
                    INSERT INTO user_info (user_id, first_seen, last_seen, total_messages)
                    VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
                """, (user_id,))

            self.conn.commit()
        except Exception as e:
            logger.error(f"更新用户信息失败: {e}")
            self.conn.rollback()

    def get_user_info(self, user_id: str) -> Optional[dict]:
        """获取用户信息

        Args:
            user_id: 用户ID

        Returns:
            用户信息字典
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT nickname, first_seen, last_seen, total_messages, settings
                FROM user_info WHERE user_id = ?
            """, (user_id,))

            row = cursor.fetchone()
            if row:
                return {
                    "nickname": row[0],
                    "first_seen": row[1],
                    "last_seen": row[2],
                    "total_messages": row[3],
                    "settings": json.loads(row[4]) if row[4] else {}
                }
            return None
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            return None

    def mark_message_as_important(self, message_id: int):
        """标记消息为重要

        Args:
            message_id: 消息ID
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE conversations
                SET is_important = 1
                WHERE id = ?
            """, (message_id,))
            self.conn.commit()
            logger.info(f"已标记消息 {message_id} 为重要")
        except Exception as e:
            logger.error(f"标记消息失败: {e}")
            self.conn.rollback()

    def cleanup_old_messages(self, days: int = 30):
        """清理旧消息（保留指定天数内的消息）

        Args:
            days: 保留天数
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                DELETE FROM conversations
                WHERE timestamp < datetime('now', ?)
            """, (f'-{days} days',))

            deleted_count = cursor.rowcount
            self.conn.commit()
            logger.info(f"已清理 {deleted_count} 条旧消息（{days}天前）")
            return deleted_count
        except Exception as e:
            logger.error(f"清理旧消息失败: {e}")
            self.conn.rollback()
            return 0

    def clear_user_conversation(self, user_id: str) -> int:
        """清除指定用户的所有对话历史

        Args:
            user_id: 用户ID

        Returns:
            删除的消息条数
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                DELETE FROM conversations
                WHERE user_id = ?
            """, (user_id,))

            deleted_count = cursor.rowcount
            self.conn.commit()
            logger.info(f"已清除用户 {user_id} 的 {deleted_count} 条对话历史")
            return deleted_count
        except Exception as e:
            logger.error(f"清除用户对话历史失败: {e}")
            self.conn.rollback()
            return 0

    def clear_user_memories(self, user_id: str) -> int:
        """清除指定用户的所有长期记忆

        Args:
            user_id: 用户ID

        Returns:
            删除的记忆条数
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                DELETE FROM user_memories
                WHERE user_id = ?
            """, (user_id,))

            deleted_count = cursor.rowcount
            self.conn.commit()
            logger.info(f"已清除用户 {user_id} 的 {deleted_count} 条长期记忆")
            return deleted_count
        except Exception as e:
            logger.error(f"清除用户长期记忆失败: {e}")
            self.conn.rollback()
            return 0

    def get_last_user_message(self, user_id: str) -> Optional[str]:
        """获取用户最近一条消息内容

        Args:
            user_id: 用户ID

        Returns:
            最近一条用户消息内容，没有则返回 None
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT content FROM conversations
                WHERE user_id = ? AND role = 'user'
                ORDER BY timestamp DESC
                LIMIT 1
            """, (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"获取最后用户消息失败: {e}")
            return None

    def delete_last_conversation_pair(self, user_id: str) -> int:
        """删除用户最近一轮对话（一条 user 消息 + 一条 assistant 回复）

        Args:
            user_id: 用户ID

        Returns:
            删除的消息条数
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id, role FROM conversations
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT 2
            """, (user_id,))
            rows = cursor.fetchall()
            if not rows:
                return 0

            ids_to_delete = [row[0] for row in rows]
            placeholders = ','.join(['?' for _ in ids_to_delete])
            cursor.execute(f"""
                DELETE FROM conversations WHERE id IN ({placeholders})
            """, ids_to_delete)

            deleted = cursor.rowcount
            self.conn.commit()
            logger.info(f"已删除用户 {user_id} 的 {deleted} 条最近对话")
            return deleted
        except Exception as e:
            logger.error(f"删除最近对话失败: {e}")
            self.conn.rollback()
            return 0

    def get_message_by_tg_id(self, telegram_msg_id: int) -> Optional[dict]:
        """通过Telegram消息ID查找数据库记录

        Args:
            telegram_msg_id: Telegram消息ID

        Returns:
            {'id': int, 'user_id': str, 'role': str, 'content': str} 或 None
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id, user_id, role, content FROM conversations
                WHERE telegram_msg_id = ?
                LIMIT 1
            """, (telegram_msg_id,))
            row = cursor.fetchone()
            if row:
                return {"id": row[0], "user_id": row[1], "role": row[2], "content": row[3]}
            return None
        except Exception as e:
            logger.error(f"通过TG ID查找消息失败: {e}")
            return None

    def edit_message_content(self, db_id: int, new_content: str) -> bool:
        """编辑消息内容

        Args:
            db_id: 数据库消息ID
            new_content: 新内容
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE conversations SET content = ?, timestamp = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_content, db_id))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"编辑消息失败: {e}")
            self.conn.rollback()
            return False

    def _update_tg_msg_id(self, db_id: int, telegram_msg_id: int):
        """回填Telegram消息ID（bot发送回复后调用）"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE conversations SET telegram_msg_id = ? WHERE id = ?
            """, (telegram_msg_id, db_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"回填TG消息ID失败: {e}")
            self.conn.rollback()

    def delete_message_by_id(self, db_id: int) -> bool:
        """按数据库ID删除单条消息"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE id = ?", (db_id,))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除消息失败: {e}")
            self.conn.rollback()
            return False

    def delete_messages_from_id(self, db_id: int, user_id: str) -> List[int]:
        """删除指定ID及其之后的所有消息，返回被删除的 telegram_msg_id 列表"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT telegram_msg_id FROM conversations
                WHERE user_id = ? AND id >= ? AND telegram_msg_id IS NOT NULL
            """, (user_id, db_id))
            tg_ids = [row[0] for row in cursor.fetchall()]
            cursor.execute("""
                DELETE FROM conversations WHERE user_id = ? AND id >= ?
            """, (user_id, db_id))
            self.conn.commit()
            return tg_ids
        except Exception as e:
            logger.error(f"批量删除消息失败: {e}")
            self.conn.rollback()
            return []

    def set_arousal_snapshot(self, conv_id: int, active: bool, enter_count: int, exit_count: int):
        """写入文爱状态快照到 conversation 行（仅 user 消息调用）"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE conversations
                SET erotic_active = ?, erotic_enter_count = ?, erotic_exit_count = ?
                WHERE id = ?
            """, (1 if active else 0, enter_count, exit_count, conv_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"写入 arousal 快照失败: {e}")
            self.conn.rollback()

    def get_last_arousal_snapshot_before(self, user_id: str, before_db_id: int) -> tuple:
        """获取指定 ID 之前最近一条用户消息的文爱状态快照

        Returns:
            (active, enter_count, exit_count)，无记录时返回 (False, 0, 0)
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT erotic_active, erotic_enter_count, erotic_exit_count
                FROM conversations
                WHERE user_id = ? AND role = 'user' AND id < ? AND erotic_active IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
            """, (user_id, before_db_id))
            row = cursor.fetchone()
            if row:
                return (bool(row[0]), row[1] or 0, row[2] or 0)
            return (False, 0, 0)
        except Exception as e:
            logger.error(f"获取 arousal 快照失败: {e}")
            return (False, 0, 0)

    def reset_arousal_snapshot(self, conv_id: int):
        """置空指定行的文爱快照（编辑后旧判定失效）"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE conversations
                SET erotic_active = NULL, erotic_enter_count = NULL, erotic_exit_count = NULL
                WHERE id = ?
            """, (conv_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"重置 arousal 快照失败: {e}")
            self.conn.rollback()

    def get_conversation_from_id(self, user_id: str, from_db_id: int) -> List[Tuple[str, str]]:
        """获取从指定ID开始的消息（用于编辑后输出摘要）

        Args:
            user_id: 用户ID
            from_db_id: 起始数据库ID

        Returns:
            [(role, content), ...] 按时间顺序
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT role, content FROM conversations
                WHERE user_id = ? AND id >= ?
                ORDER BY id ASC
            """, (user_id, from_db_id))
            return [(row[0], row[1]) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取对话摘要失败: {e}")
            return []

    def get_user_mood(self, user_id: str) -> dict:
        """读取用户心情状态，不存在则返回默认值"""
        try:
            info = self.get_user_info(user_id)
            if info and info["settings"] and "mood" in info["settings"]:
                mood = info["settings"]["mood"]
                # 确保每个维度存在
                for k in ("happiness", "missing", "energy", "anger", "arousal"):
                    if k not in mood:
                        mood[k] = 5
                return mood
        except Exception:
            pass
        return {"happiness": 7, "missing": 3, "energy": 7, "anger": 1, "arousal": 3}

    def set_user_mood(self, user_id: str, mood: dict, updated_at: str = None):
        """保存用户心情到 settings JSON"""
        from datetime import datetime as dt
        try:
            info = self.get_user_info(user_id)
            if not info:
                # 用户还不存在，先创建
                cursor = self.conn.cursor()
                default_settings = {"mood": mood, "mood_updated": updated_at or dt.now().strftime("%Y-%m-%d %H:%M")}
                cursor.execute("""
                    INSERT INTO user_info (user_id, settings)
                    VALUES (?, ?)
                """, (user_id, json.dumps(default_settings, ensure_ascii=False)))
                self.conn.commit()
                return

            settings = info["settings"] or {}
            settings["mood"] = mood
            settings["mood_updated"] = updated_at or dt.now().strftime("%Y-%m-%d %H:%M")

            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE user_info SET settings = ? WHERE user_id = ?
            """, (json.dumps(settings, ensure_ascii=False), user_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"保存心情失败: {e}")
            self.conn.rollback()

    def get_erotic_state(self, user_id: str) -> dict:
        """读取文爱状态机"""
        try:
            info = self.get_user_info(user_id)
            if info and info.get("settings") and isinstance(info["settings"], dict):
                erotic = info["settings"].get("erotic", {})
                return {
                    "active": erotic.get("active", False),
                    "count_enter": erotic.get("count_enter", 0),
                    "count_exit": erotic.get("count_exit", 0),
                }
        except Exception:
            pass
        return {"active": False, "count_enter": 0, "count_exit": 0}

    def save_erotic_state(self, user_id: str, state: dict):
        """保存文爱状态机"""
        try:
            info = self.get_user_info(user_id)
            cursor = self.conn.cursor()
            if info and info.get("settings") is not None:
                settings = info["settings"] if isinstance(info["settings"], dict) else {}
                settings["erotic"] = state
                cursor.execute(
                    "UPDATE user_info SET settings = ? WHERE user_id = ?",
                    (json.dumps(settings, ensure_ascii=False), user_id)
                )
            else:
                # 用户不存在或者 settings 为空
                default_settings = {"erotic": state}
                if info:
                    cursor.execute(
                        "UPDATE user_info SET settings = ? WHERE user_id = ?",
                        (json.dumps(default_settings, ensure_ascii=False), user_id)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO user_info (user_id, settings) VALUES (?, ?)",
                        (user_id, json.dumps(default_settings, ensure_ascii=False))
                    )
            self.conn.commit()
        except Exception as e:
            logger.error(f"保存文爱状态失败: {e}")
            self.conn.rollback()

    def record_last_clear(self, user_id: str):
        """记录最近一次 /clear 的时间戳"""
        from datetime import datetime as dt
        ts = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        info = self.get_user_info(user_id)
        settings = (info.get("settings") or {}) if info else {}
        if not isinstance(settings, dict):
            settings = {}
        settings["last_clear"] = ts
        cursor = self.conn.cursor()
        if info:
            cursor.execute("UPDATE user_info SET settings = ? WHERE user_id = ?",
                           (json.dumps(settings, ensure_ascii=False), user_id))
        else:
            cursor.execute("INSERT INTO user_info (user_id, settings) VALUES (?, ?)",
                           (user_id, json.dumps(settings, ensure_ascii=False)))
        self.conn.commit()

    def get_last_clear_at(self, user_id: str) -> str:
        info = self.get_user_info(user_id)
        if info and info.get("settings") and isinstance(info["settings"], dict):
            return info["settings"].get("last_clear", "2000-01-01 00:00:00")
        return "2000-01-01 00:00:00"

    def create_compact_record(self, user_id: str, title: str, content: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO compact_records (user_id, title, content) VALUES (?, ?, ?)",
            (user_id, title, content)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_compact_records(self, user_id: str) -> list:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, title, created_at FROM compact_records WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        )
        return [(row[0], row[1], row[2]) for row in cursor.fetchall()]

    def get_compact_record(self, record_id: int) -> dict:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, user_id, title, content, created_at FROM compact_records WHERE id = ?",
            (record_id,)
        )
        row = cursor.fetchone()
        if row:
            return {"id": row[0], "user_id": row[1], "title": row[2], "content": row[3], "created_at": row[4]}
        return None

    def delete_compact_record(self, record_id: int, user_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM compact_records WHERE id = ? AND user_id = ?",
            (record_id, user_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_memory_stats(self, user_id: str) -> dict:
        stats = {}
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,))
        stats["conversations"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM user_memories WHERE user_id = ?", (user_id,))
        stats["memories"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM compact_records WHERE user_id = ?", (user_id,))
        stats["compacts"] = cursor.fetchone()[0]
        cursor.execute("SELECT memory_type, COUNT(*) FROM user_memories WHERE user_id = ? GROUP BY memory_type", (user_id,))
        stats["memory_types"] = {row[0]: row[1] for row in cursor.fetchall()}
        info = self.get_user_info(user_id)
        stats["last_clear"] = None
        if info and info.get("settings") and isinstance(info["settings"], dict):
            stats["last_clear"] = info["settings"].get("last_clear")
        cursor.execute("SELECT title, created_at FROM compact_records WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
        row = cursor.fetchone()
        stats["last_compact"] = {"title": row[0], "time": row[1]} if row else None
        return stats

    def get_messages_since_clear(self, user_id: str, since: str) -> list:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? AND timestamp > ? ORDER BY id ASC",
            (user_id, since)
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    # 测试数据库功能
    with MemoryDB("test_memory.db") as db:
        # 添加测试消息
        db.add_message("test_user", "user", "你好！")
        db.add_message("test_user", "assistant", "你好呀~")

        # 获取历史
        history = db.get_recent_conversation("test_user", 5)
        print("对话历史:", history)

        # 添加记忆
        db.add_user_memory("test_user", "preference", "喜欢玩游戏光遇", 7)
        memories = db.get_user_memories("test_user")
        print("用户记忆:", memories)

        # 获取用户信息
        user_info = db.get_user_info("test_user")
        print("用户信息:", user_info)

    # 删除测试数据库
    os.remove("test_memory.db")