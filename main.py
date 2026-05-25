#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 聊天机器人 - 主程序入口
基于 OpenAI 兼容 API 和自定义人格数据
"""

import os
import sys
import yaml
import argparse
import logging
from colorama import init, Fore, Style

# 初始化colorama（Windows终端颜色支持）
init(autoreset=True)

# 添加项目目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram_bot import create_telegram_bot, TelegramBot

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format=f'{Fore.CYAN}%(asctime)s{Style.RESET_ALL} - {Fore.GREEN}%(name)s{Style.RESET_ALL} - {Fore.YELLOW}%(levelname)s{Style.RESET_ALL} - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def print_banner():
    """打印程序横幅"""
    banner = f"""
{Fore.MAGENTA}{'='*60}{Style.RESET_ALL}
{Fore.CYAN}  Telegram 角色扮演聊天机器人{Style.RESET_ALL}
{Fore.MAGENTA}{'='*60}{Style.RESET_ALL}
{Fore.YELLOW}基于 OpenAI 兼容 API + 自定义人格数据{Style.RESET_ALL}
{Fore.GREEN}版本: 1.0.0{Style.RESET_ALL}
{Fore.MAGENTA}{'='*60}{Style.RESET_ALL}
"""
    print(banner)


def check_dependencies():
    """检查依赖是否安装"""
    # 模块名到包名的映射（用于显示）
    package_map = {
        'telegram': 'python-telegram-bot',
        'requests': 'requests',
        'yaml': 'PyYAML',
        'tenacity': 'tenacity',
        'colorama': 'colorama'
    }

    required_modules = ['telegram', 'requests', 'yaml', 'tenacity', 'colorama']
    missing_packages = []

    for module in required_modules:
        try:
            __import__(module.replace('-', '_'))
        except ImportError:
            missing_packages.append(package_map.get(module, module))

    if missing_packages:
        print(f"{Fore.RED}缺少依赖包: {', '.join(missing_packages)}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}请运行: pip install -r requirements.txt{Style.RESET_ALL}")
        return False

    return True


def load_config(config_path: str = "config.yaml") -> dict:
    """加载配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典
    """
    if not os.path.exists(config_path):
        print(f"{Fore.RED}配置文件 {config_path} 不存在{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}请运行: python setup.py  进行交互式配置{Style.RESET_ALL}")
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 检查必要的配置项
        required_keys = ['llm', 'telegram', 'memory', 'prompt', 'advanced']
        for key in required_keys:
            if key not in config:
                print(f"{Fore.RED}配置文件中缺少必要的键: {key}{Style.RESET_ALL}")
                return None

        # 检查API密钥
        api_key = config['llm'].get('api_key', '').strip()
        if not api_key or "your-" in api_key.lower():
            print(f"{Fore.RED}请先配置 LLM API 密钥{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}运行: python setup.py  进行交互式配置{Style.RESET_ALL}")
            return None

        # 检查Telegram Bot Token
        bot_token = config['telegram'].get('bot_token', '').strip()
        if not bot_token or "your-" in bot_token.lower():
            print(f"{Fore.RED}请先配置 Telegram Bot Token{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}运行: python setup.py  进行交互式配置{Style.RESET_ALL}")
            return None

        return config

    except yaml.YAMLError as e:
        print(f"{Fore.RED}配置文件解析失败: {e}{Style.RESET_ALL}")
        return None
    except Exception as e:
        print(f"{Fore.RED}加载配置文件失败: {e}{Style.RESET_ALL}")
        return None


def check_persona_file():
    """检查人格数据文件"""
    persona_file = "digital_person/persona_final-d.md"
    if not os.path.exists(persona_file):
        print(f"{Fore.RED}人格数据文件 {persona_file} 不存在{Style.RESET_ALL}")
        return False

    file_size = os.path.getsize(persona_file)
    if file_size < 100:
        print(f"{Fore.RED}人格数据文件过小，可能不完整{Style.RESET_ALL}")
        return False

    print(f"{Fore.GREEN}人格数据文件加载成功 ({file_size} 字节){Style.RESET_ALL}")
    return True


def setup_environment():
    """设置运行环境"""
    # 创建必要的目录
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    # 检查是否有示例配置文件
    example_config = "config.example.yaml"
    if not os.path.exists("config.yaml") and os.path.exists(example_config):
        import shutil
        shutil.copy(example_config, "config.yaml")
        print(f"{Fore.YELLOW}已创建 config.yaml，请填写API密钥{Style.RESET_ALL}")

    return True


def run_bot(config: dict):
    """运行机器人

    Args:
        config: 配置字典
    """
    try:
        print(f"{Fore.CYAN}正在启动Telegram机器人...{Style.RESET_ALL}")

        # 创建机器人实例
        bot = TelegramBot(config)

        print(f"{Fore.GREEN}机器人创建成功！{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}配置信息:{Style.RESET_ALL}")
        print(f"  • 模型: {config['llm']['model']}")
        print(f"  • API: {config['llm']['base_url']}")
        print(f"  • 温度: {config['advanced']['temperature']}")
        print(f"  • 最大历史: {config['prompt']['include_recent_messages']}条")
        print(f"  • 记忆数据库: {config['memory']['db_path']}")

        print(f"\n{Fore.CYAN}正在启动Telegram机器人...{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}请确保已配置正确的Telegram Bot Token{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}按 Ctrl+C 可安全退出程序{Style.RESET_ALL}")

        # 运行机器人
        bot.run()

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}收到中断信号，正在安全退出...{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}机器人运行失败: {e}{Style.RESET_ALL}")
        logger.error(f"机器人运行失败: {e}", exc_info=True)


def show_status():
    """显示机器人状态"""
    try:
        from memory_db import MemoryDB
        import sqlite3

        print(f"{Fore.CYAN}Telegram机器人状态{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{'-'*40}{Style.RESET_ALL}")

        # 检查配置文件
        if os.path.exists("config.yaml"):
            print(f"{Fore.GREEN}✓ 配置文件存在{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}✗ 配置文件缺失{Style.RESET_ALL}")

        # 检查人格数据
        persona_path = "digital_person/persona_final-d.md"
        if os.path.exists(persona_path):
            size = os.path.getsize(persona_path)
            print(f"{Fore.GREEN}✓ 人格数据文件存在 ({size} 字节){Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}✗ 人格数据文件缺失{Style.RESET_ALL}")

        # 检查世界书
        wb_path = "digital_person/world_book.json"
        if os.path.exists(wb_path):
            import json
            with open(wb_path, "r", encoding="utf-8") as f:
                wb = json.load(f)
            print(f"{Fore.GREEN}✓ 世界书存在 ({len(wb.get('entries',[]))} 条目){Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}○ 世界书未找到{Style.RESET_ALL}")

        # 检查数据库
        if os.path.exists("memory.db"):
            conn = sqlite3.connect("memory.db")
            cursor = conn.cursor()

            # 获取统计信息
            cursor.execute("SELECT COUNT(*) FROM conversations")
            total_msgs = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM conversations")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM user_memories")
            total_memories = cursor.fetchone()[0]

            conn.close()

            print(f"{Fore.GREEN}✓ 记忆数据库存在{Style.RESET_ALL}")
            print(f"  • 总对话数: {total_msgs}")
            print(f"  • 总用户数: {total_users}")
            print(f"  • 重要记忆: {total_memories}")
        else:
            print(f"{Fore.YELLOW}○ 记忆数据库未创建{Style.RESET_ALL}")

        # 检查日志文件
        if os.path.exists("bot.log"):
            size = os.path.getsize("bot.log")
            print(f"{Fore.GREEN}✓ 日志文件存在 ({size} 字节){Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}○ 日志文件未创建{Style.RESET_ALL}")

        print(f"{Fore.MAGENTA}{'-'*40}{Style.RESET_ALL}")

    except Exception as e:
        print(f"{Fore.RED}获取状态失败: {e}{Style.RESET_ALL}")


def cleanup_old_data(days: int = 30):
    """清理旧数据

    Args:
        days: 保留天数
    """
    try:
        from memory_db import MemoryDB

        print(f"{Fore.YELLOW}正在清理 {days} 天前的旧数据...{Style.RESET_ALL}")

        db = MemoryDB("memory.db")
        deleted_count = db.cleanup_old_messages(days)
        db.close()

        print(f"{Fore.GREEN}清理完成，删除了 {deleted_count} 条旧消息{Style.RESET_ALL}")

    except Exception as e:
        print(f"{Fore.RED}清理数据失败: {e}{Style.RESET_ALL}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Telegram聊天机器人")
    parser.add_argument("--config", "-c", default="config.yaml",
                       help="配置文件路径 (默认: config.yaml)")
    parser.add_argument("--status", "-s", action="store_true",
                       help="显示机器人状态")
    parser.add_argument("--cleanup", type=int, metavar="DAYS",
                       help="清理指定天数前的旧数据")
    parser.add_argument("--version", "-v", action="store_true",
                       help="显示版本信息")

    args = parser.parse_args()

    # 显示版本
    if args.version:
        print_banner()
        return

    # 显示状态
    if args.status:
        show_status()
        return

    # 清理数据
    if args.cleanup:
        cleanup_old_data(args.cleanup)
        return

    # 正常启动流程
    print_banner()

    # 检查依赖
    if not check_dependencies():
        sys.exit(1)

    # 设置环境
    if not setup_environment():
        sys.exit(1)

    # 检查人格数据文件
    if not check_persona_file():
        sys.exit(1)

    # 加载配置
    config = load_config(args.config)
    if not config:
        sys.exit(1)

    # 运行机器人
    run_bot(config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}程序被用户中断{Style.RESET_ALL}")
        sys.exit(0)
    except Exception as e:
        print(f"{Fore.RED}程序运行异常: {e}{Style.RESET_ALL}")
        logger.error(f"程序运行异常: {e}", exc_info=True)
        sys.exit(1)