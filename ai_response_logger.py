"""
AI 回复日志记录模块
记录所有 AI API 交互的完整信息，用于排查搜索失败和 API 返回值异常。

日志内容：
- 用户查询、搜索模式、时间戳
- AI API 请求（模型、消息、工具调用）
- AI API 响应（内容、工具调用、完成原因）
- 搜索最终结果（成功/失败、结果数、错误信息）
- API 异常和降级事件

日志文件位置：${exe_dir}/ai_responses.log
滚动策略：单文件最大 10MB，保留最近 5 个备份
"""

import json
import logging
import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# 获取日志文件路径（与 config.json 同目录）
def _get_log_dir() -> Path:
    """获取日志目录"""
    import config as cfg_module
    return cfg_module.get_exe_dir()


def _get_log_path() -> Path:
    """获取日志文件路径"""
    return _get_log_dir() / "ai_responses.log"


# 创建独立 logger
_ai_logger = logging.getLogger("ai_response")
_ai_logger.setLevel(logging.DEBUG)
_ai_logger.propagate = False  # 不传播到根 logger

# 配置 handler（只在首次导入时配置）
if not _ai_logger.handlers:
    log_path = _get_log_path()
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    _ai_logger.addHandler(handler)


class AIRequestLogger:
    """记录单次 AI 搜索交互的上下文管理器"""

    def __init__(self, user_query: str, fast_mode: bool = True):
        self.session_id = _generate_session_id()
        self.user_query = user_query
        self.fast_mode = fast_mode
        self.start_time = time.time()
        self.api_calls: list = []
        self.errors: list = []
        self.final_result: Optional[dict] = None
        self._log_header()

    def _log_header(self):
        """记录搜索请求头"""
        mode = "快速搜索(规则)" if self.fast_mode else "AI 智能搜索"
        _ai_logger.info(
            f"[{self.session_id}] ========== 新搜索 ==========\n"
            f"  模式: {mode}\n"
            f"  查询: \"{self.user_query}\""
        )

    def log_api_request(self, iteration: int, model: str, messages_summary: str,
                        tool_count: int = 0):
        """记录 API 请求"""
        self.api_calls.append({
            "iteration": iteration,
            "model": model,
            "messages_summary": messages_summary,
            "tool_count": tool_count,
            "timestamp": datetime.now().isoformat()
        })
        _ai_logger.debug(
            f"[{self.session_id}] 第{iteration}轮 API 请求:\n"
            f"  模型: {model}\n"
            f"  消息数: {len(messages_summary.split(chr(10))) if messages_summary else 0}\n"
            f"  工具数: {tool_count}"
        )

    def log_api_response(self, iteration: int, has_tool_calls: bool,
                         tool_names: list = None, content: str = "",
                         finish_reason: str = "", usage: dict = None):
        """记录 API 响应"""
        tool_str = ", ".join(tool_names) if tool_names else "无"
        content_preview = content[:200] if content else "(空)"

        usage_str = ""
        if usage:
            usage_str = (f"\n  Token: prompt={usage.get('prompt_tokens', '?')}, "
                         f"completion={usage.get('completion_tokens', '?')}, "
                         f"total={usage.get('total_tokens', '?')}")

        _ai_logger.debug(
            f"[{self.session_id}] 第{iteration}轮 API 响应:\n"
            f"  工具调用: {has_tool_calls} ({tool_str})\n"
            f"  完成原因: {finish_reason}\n"
            f"  内容预览: {content_preview}"
            f"{usage_str}"
        )

    def log_api_error(self, iteration: int, error: str, error_type: str = "API错误"):
        """记录 API 调用错误"""
        self.errors.append({
            "iteration": iteration,
            "error": error,
            "type": error_type,
            "timestamp": datetime.now().isoformat()
        })
        _ai_logger.error(
            f"[{self.session_id}] 第{iteration}轮 {error_type}:\n"
            f"  {error}"
        )

    def log_tool_execution(self, tool_name: str, args: dict, result_summary: str):
        """记录工具执行"""
        args_str = json.dumps(args, ensure_ascii=False, default=str)
        if len(args_str) > 300:
            args_str = args_str[:300] + "..."
        _ai_logger.debug(
            f"[{self.session_id}] 执行工具: {tool_name}\n"
            f"  参数: {args_str}\n"
            f"  结果: {result_summary}"
        )

    def log_search_result(self, success: bool, total: int, error: str = "",
                          message: str = "", cached: bool = False):
        """记录搜索最终结果"""
        elapsed = time.time() - self.start_time
        self.final_result = {
            "success": success,
            "total": total,
            "error": error,
            "message": message,
            "cached": cached,
            "elapsed_seconds": round(elapsed, 2)
        }

        status = "成功" if success else "失败"
        cache_tag = " (缓存命中)" if cached else ""

        _ai_logger.info(
            f"[{self.session_id}] ========== 搜索{status}{cache_tag} ==========\n"
            f"  耗时: {elapsed:.2f}s\n"
            f"  结果数: {total}\n"
            f"  消息: \"{message}\"\n"
            f"  错误: \"{error}\"\n"
            f"  API调用次数: {len(self.api_calls)}\n"
            f"  错误次数: {len(self.errors)}"
        )

    def log_content_analysis(self, file_count: int, query: str, success: bool):
        """记录内容分析（二次分析）"""
        status = "成功" if success else "失败"
        _ai_logger.info(
            f"[{self.session_id}] 内容分析{status}: {file_count}个文件"
        )

    def log_content_analysis_error(self, error: str):
        """记录内容分析错误"""
        _ai_logger.error(
            f"[{self.session_id}] 内容分析异常: {error}"
        )

    def get_summary(self) -> dict:
        """获取本次搜索的摘要数据"""
        return {
            "session_id": self.session_id,
            "query": self.user_query,
            "fast_mode": self.fast_mode,
            "elapsed": round(time.time() - self.start_time, 2),
            "api_calls": len(self.api_calls),
            "errors": len(self.errors),
            "final": self.final_result
        }


# ============ 工具函数 ============

def _generate_session_id() -> str:
    """生成简短的会话 ID"""
    import random
    import string
    ts = datetime.now().strftime("%m%d%H%M%S")
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{ts}-{rand}"


def log_info(msg: str):
    """记录一般信息"""
    _ai_logger.info(msg)


def log_error(msg: str):
    """记录错误"""
    _ai_logger.error(msg)


def log_warning(msg: str):
    """记录警告"""
    _ai_logger.warning(msg)


def get_log_file_path() -> str:
    """获取日志文件完整路径"""
    return str(_get_log_path())
