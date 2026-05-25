#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM API 客户端
提供 OpenAI 兼容 API 调用功能，支持 DeepSeek / OpenAI / Groq / 本地模型等
包含重试机制和错误处理
"""

import requests
import json
import time
import logging
from typing import List, Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com"):
        """初始化 LLM 客户端（OpenAI 兼容接口）

        Args:
            api_key: API 密钥
            base_url: API 基础 URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def chat(self, messages: List[Dict], temperature: float = 0.7,
             max_tokens: int = 1024, model: str = "deepseek-chat",
             thinking: Optional[Dict] = None) -> str:
        """调用DeepSeek聊天API

        Args:
            messages: 消息列表，格式为 [{"role": "system/user/assistant", "content": "..."}, ...]
            temperature: 生成温度（0.1-1.0）
            max_tokens: 最大生成token数
            model: 模型名称
            thinking: 思考模式配置，如 {"type": "enabled", "reasoning_effort": "high"}

        Returns:
            生成的文本内容

        Raises:
            Exception: API调用失败
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        if thinking is not None:
            payload["thinking"] = thinking

        try:
            start_time = time.time()
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            elapsed_time = time.time() - start_time

            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]

                # 记录使用统计
                usage = result.get("usage", {})
                logger.info(
                    f"API调用成功 - "
                    f"耗时: {elapsed_time:.2f}s, "
                    f"输入token: {usage.get('prompt_tokens', 'N/A')}, "
                    f"输出token: {usage.get('completion_tokens', 'N/A')}, "
                    f"总token: {usage.get('total_tokens', 'N/A')}"
                )

                return content
            else:
                error_msg = f"API调用失败 - 状态码: {response.status_code}, 响应: {response.text}"
                logger.error(error_msg)

                # 如果是认证错误，不重试
                if response.status_code in [401, 403]:
                    raise Exception(f"API密钥错误或权限不足: {response.text}")
                else:
                    raise Exception(error_msg)

        except requests.exceptions.Timeout:
            logger.error("API调用超时")
            raise Exception("API调用超时，请检查网络连接")
        except requests.exceptions.ConnectionError:
            logger.error("网络连接错误")
            raise Exception("网络连接错误，请检查网络")
        except Exception as e:
            logger.error(f"API调用异常: {e}")
            raise

    def stream_chat(self, messages: List[Dict], temperature: float = 0.7,
                    max_tokens: int = 1024, model: str = "deepseek-chat",
                    thinking: Optional[Dict] = None):
        """流式调用DeepSeek API（生成器）

        Args:
            messages: 消息列表
            temperature: 生成温度
            max_tokens: 最大生成token数
            model: 模型名称
            thinking: 思考模式配置，如 {"type": "enabled", "reasoning_effort": "high"}

        Yields:
            生成的文本片段
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }

        if thinking is not None:
            payload["thinking"] = thinking

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=30
            )

            if response.status_code != 200:
                error_msg = f"流式API调用失败 - 状态码: {response.status_code}"
                logger.error(error_msg)
                raise Exception(error_msg)

            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break

                        try:
                            json_data = json.loads(data)
                            if "choices" in json_data and len(json_data["choices"]) > 0:
                                delta = json_data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            logger.error(f"流式API调用异常: {e}")
            raise

    def check_api_key(self) -> bool:
        """检查API密钥是否有效

        Returns:
            True如果有效，False如果无效
        """
        try:
            # 发送一个简单的测试请求
            test_messages = [{"role": "user", "content": "Hello"}]
            self.chat(test_messages, max_tokens=10)
            logger.info("API密钥验证成功")
            return True
        except Exception as e:
            logger.error(f"API密钥验证失败: {e}")
            return False

    def estimate_tokens(self, text: str) -> int:
        """粗略估计文本的token数量

        Args:
            text: 输入文本

        Returns:
            估计的token数量
        """
        # 简单估算：英文约4字符/token，中文约2字符/token
        # 实际应使用tiktoken库，但为简化依赖使用估算
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars

        # 估算：中文字符约2字符/token，其他约4字符/token
        estimated_tokens = (chinese_chars / 2) + (other_chars / 4)
        return int(estimated_tokens)


class LLMManager:
    """LLM管理器，封装客户端并提供高级功能"""

    def __init__(self, config: dict):
        """初始化LLM管理器

        Args:
            config: 配置字典
        """
        self.config = config
        self.client = DeepSeekClient(
            api_key=config["llm"]["api_key"],
            base_url=config["llm"]["base_url"]
        )
        self.model = config["llm"].get("model", "deepseek-chat")
        self.thinking_config = None

    def set_thinking(self, enabled: bool, effort: str = "high"):
        """设置思考模式

        Args:
            enabled: 是否启用思考模式
            effort: 思考强度，"high" 或 "max"
        """
        if enabled:
            self.thinking_config = {"type": "enabled", "reasoning_effort": effort}
        else:
            self.thinking_config = {"type": "disabled"}

    def get_thinking_status(self) -> dict:
        """获取当前思考模式状态"""
        if self.thinking_config is None:
            return {"enabled": True, "effort": "high", "explicitly_set": False}
        enabled = self.thinking_config.get("type") == "enabled"
        return {
            "enabled": enabled,
            "effort": self.thinking_config.get("reasoning_effort", "high") if enabled else None,
            "explicitly_set": True
        }

    def generate_response(self, messages: List[Dict]) -> str:
        """生成响应

        Args:
            messages: 消息列表

        Returns:
            生成的响应文本
        """
        try:
            response = self.client.chat(
                messages=messages,
                temperature=self.config["advanced"]["temperature"],
                max_tokens=self.config["advanced"]["max_tokens_per_response"],
                model=self.model,
                thinking=self.thinking_config
            )
            return response
        except Exception as e:
            logger.error(f"生成响应失败: {e}")
            return f"出错了: {str(e)}，请稍后再试"

    def stream_response(self, messages: List[Dict]):
        """流式生成响应

        Args:
            messages: 消息列表

        Yields:
            响应文本片段
        """
        try:
            for chunk in self.client.stream_chat(
                messages=messages,
                temperature=self.config["advanced"]["temperature"],
                max_tokens=self.config["advanced"]["max_tokens_per_response"],
                model=self.model,
                thinking=self.thinking_config
            ):
                yield chunk
        except Exception as e:
            logger.error(f"流式生成响应失败: {e}")
            yield f"流式响应出错: {str(e)}"


if __name__ == "__main__":
    # 测试客户端
    import os
    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("请设置 DEEPSEEK_API_KEY 环境变量")
        exit(1)

    client = DeepSeekClient(api_key)

    # 测试API密钥
    if client.check_api_key():
        print("API密钥验证成功")

        # 测试聊天
        messages = [
            {"role": "system", "content": "你是一个有帮助的助手。"},
            {"role": "user", "content": "你好，请用中文回复我。"}
        ]

        response = client.chat(messages, max_tokens=50)
        print(f"响应: {response}")

        # 测试流式响应
        print("\n流式响应测试:")
        for chunk in client.stream_chat(messages, max_tokens=50):
            print(chunk, end="", flush=True)
        print()
    else:
        print("API密钥验证失败")