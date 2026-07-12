"""
Faind 搜索 Agent 模块
使用 OpenAI function calling 实现智能文件搜索与标签管理
支持 AI Agent 多步推理 + 规则匹配降级
"""

import json
import logging
import os
import re
import sys
from typing import Optional

import config
from ai_cache import AICache
from ai_response_logger import AIRequestLogger

logger = logging.getLogger(__name__)


def _ensure_ssl_certs():
    """
    确保 SSL 证书在 PyInstaller 打包后可用
    certifi 的 cacert.pem 在 PyInstaller onefile 模式下可能找不到，需要手动设置
    """
    try:
        import certifi

        # 尝试获取 certifi 证书路径
        cert_path = certifi.where()
        if cert_path and os.path.isfile(cert_path):
            os.environ.setdefault('SSL_CERT_FILE', cert_path)
            os.environ.setdefault('REQUESTS_CA_BUNDLE', cert_path)
            return

        # PyInstaller onefile 模式下，cacert.pem 可能被放在 certifi 子目录中
        if getattr(sys, 'frozen', False):
            meipass = sys._MEIPASS
            alt_paths = [
                os.path.join(meipass, 'certifi', 'cacert.pem'),
                os.path.join(meipass, 'cacert.pem'),
            ]
            for alt in alt_paths:
                if os.path.isfile(alt):
                    os.environ['SSL_CERT_FILE'] = alt
                    os.environ['REQUESTS_CA_BUNDLE'] = alt
                    return
    except ImportError:
        pass


_ensure_ssl_certs()

# ============ Agent 系统提示词 ============
AGENT_SYSTEM_PROMPT = """你是 Faind 文件搜索助手，一个智能文件管理 Agent。你可以通过调用工具来帮用户查找文件、管理标签。

## 工作原则
1. 理解用户真实意图，不要机械翻译关键词
2. 善用组合条件精确定位文件（如 "最近的Python文件" → 搜索 ext:py;pyw dm:thisweek）
3. 如果首次搜索结果太多，自动追加条件缩小范围
4. 标签操作时，从用户描述中提取有意义的标签（不要用无意义标签如"文件"）
5. 每次只调用必要的工具，不要冗余调用

## Everything 搜索语法参考
- 关键词：直接输入（匹配文件名和路径）
- 扩展名：ext:pdf 或 *.pdf
- 多扩展名：ext:doc;docx;pdf（注意不加分号后空格）
- 路径中搜索：path:关键词（用于搜索主题/人名/系列，可匹配文件夹名）
- 日期：dm:today / dm:yesterday / dm:thisweek / dm:thismonth / dm:thisyear
- 大小：size:>100mb / size:<1kb
- 逻辑：空格=AND，|=OR，!=NOT
- 文件夹：folder:关键词
- 示例："本周修改的PDF" → ext:pdf dm:thisweek

## 搜索策略（重要！）
- 路径优先：搜索主题、人名、系列时，必须使用 path:关键词 来匹配路径和文件夹名
- 很多文件按文件夹组织（如 Candydoll_Ziliy 文件夹下的图片），文件名可能不含主题关键词
- 错误示例：搜索 "Candydoll" 只用关键词匹配文件名 → 只返回1个结果
- 正确示例：搜索 "Candydoll" 用 path:Candydoll → 返回路径匹配的完整结果
- 规则：人名/主题/系列/品牌 等关键词一律用 path: 搜索

## 无结果重试策略（重要！）
如果 search_files 返回 0 个结果，绝不要直接放弃！必须尝试以下策略：
- 使用同义词、近义词、相关词汇重新搜索
- 放宽搜索条件（去掉部分限制、使用更宽泛的关键词）
- 尝试不同的 Everything 语法表达（如 path:关键词 改用直接关键词，或反过来）
- 最多尝试3轮不同的搜索策略，直到找到文件或确认确实不存在

## 内容搜索流程（用户要求查找包含特定内容的文件时）
当用户意图涉及文件**内容**（如"包含XXX的资料"、"关于XXX的文档"），必须遵循两阶段流程：

### 第一阶段：文件名/路径搜索
1. 调用 search_files 按文件名和路径搜索，获取候选文件列表
2. 向用户报告第一轮搜索找到了多少候选文件

### 第二阶段：内容验证与筛选
1. 从第一轮结果中选取最相关的文件（建议前15个），调用 read_file_contents 读取其实际内容
2. 仔细对比每个文件的内容与用户搜索意图，判断是否真正相关
3. **重要**：只保留内容真正匹配的文件！文件名匹配但内容无关的要排除
4. 最终回复中明确指出哪些文件通过了内容验证，哪些被排除了

## 标签提取规则
- "把这些标记为重要项目" → tags: ["重要", "项目"]
- "添加标签 工作" → tags: ["工作"]
- "标记为已处理" → tags: ["已处理"]
- 避免提取无意义标签如"文件"、"这些"、"那个"等

## 回复格式
完成工具调用后，用简洁中文总结结果。不要重复工具返回的原始数据。"""

# ============ 工具定义 ============
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "使用 Everything 搜索引擎查找文件。支持 Everything 搜索语法：ext:扩展名、path:路径、dm:日期、size:大小、folder:文件夹等。可组合多个条件（空格=AND）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Everything 搜索语法字符串。例如：'ext:pdf dm:thisweek' 搜索本周修改的PDF"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认100",
                        "default": 100
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_tags",
            "description": "为指定文件添加标签",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "文件完整路径列表"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要添加的标签列表"
                    }
                },
                "required": ["files", "tags"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_tags",
            "description": "移除指定文件的标签",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "文件完整路径列表"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要移除的标签列表"
                    }
                },
                "required": ["files", "tags"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tags",
            "description": "获取指定文件的标签",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件完整路径"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_tags",
            "description": "获取所有已使用的标签列表",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_tag",
            "description": "按标签搜索文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "标签名"
                    }
                },
                "required": ["tag"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_tags",
            "description": "根据文件信息（名称、扩展名、路径）推荐合适的标签",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_info": {
                        "type": "object",
                        "description": "文件信息",
                        "properties": {
                            "name": {"type": "string", "description": "文件名"},
                            "path": {"type": "string", "description": "文件路径"},
                            "extension": {"type": "string", "description": "文件扩展名"}
                        }
                    }
                },
                "required": ["file_info"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_contents",
            "description": "读取文件的文本内容。用于内容搜索第二阶段：在文件名匹配后，读取候选文件的实际内容来判断是否与用户意图真正相关。支持 PDF、DOCX、XLSX、PPTX、TXT、MD 等格式。每次建议读取不超过15个文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要读取内容的文件完整路径列表，建议每次不超过15个"
                    }
                },
                "required": ["file_paths"]
            }
        }
    }
]

# ============ 规则匹配关键词（降级方案用） ============
TAG_KEYWORDS = ["标记", "添加标签", "打标签", "设为", "标签为", "加上标签", "标注"]
UNTAG_KEYWORDS = ["删除标签", "移除标签", "去掉标签", "取消标签", "去除标签"]
QUERY_TAG_KEYWORDS = ["查看标签", "有什么标签", "标签列表", "显示标签"]

FILE_TYPE_MAP = {
    "文档": "ext:doc;docx;pdf;txt;rtf;odt;xls;xlsx;ppt;pptx;csv;md",
    "图片": "ext:jpg;jpeg;png;gif;bmp;svg;ico;webp;tiff;psd",
    "视频": "ext:mp4;avi;mkv;mov;wmv;flv;webm;m4v",
    "音频": "ext:mp3;wav;flac;aac;ogg;wma;m4a",
    "压缩包": "ext:zip;rar;7z;tar;gz;bz2",
    "代码": "ext:py;js;ts;java;c;cpp;h;cs;go;rs;rb;php;html;css;sql",
    "表格": "ext:xls;xlsx;csv",
    "演示": "ext:ppt;pptx",
    "PDF": "ext:pdf",
}

DATE_MAP = {
    "今天": "dm:today", "今日": "dm:today",
    "昨天": "dm:yesterday", "前天": "dm:yesterday-2d",
    "本周": "dm:thisweek", "这周": "dm:thisweek",
    "上周": "dm:lastweek",
    "本月": "dm:thismonth", "这个月": "dm:thismonth",
    "上月": "dm:lastmonth", "上个月": "dm:lastmonth",
    "今年": "dm:thisyear",
}


class SearchAgent:
    """文件搜索 Agent — 使用 AI tool calling 进行智能搜索与标签管理"""

    def __init__(self, search_engine=None, tag_manager=None, content_reader=None):
        self.search_engine = search_engine
        self.tag_manager = tag_manager
        self.content_reader = content_reader
        self.client = None
        self.model = "gpt-4o-mini"
        self.max_tokens = 1500
        self.temperature = 0.2
        self.cache = AICache()
        self._init_ai_client()

    def _init_ai_client(self):
        """初始化 AI 客户端"""
        cfg = config.load_config()
        ai_cfg = cfg.get("ai", {})

        if not ai_cfg.get("enabled", True):
            print("[SearchAgent] AI 功能已禁用，使用规则匹配模式")
            return

        api_key = ai_cfg.get("api_key", "")
        base_url = ai_cfg.get("base_url", "")

        if not api_key:
            print("[SearchAgent] API Key 未配置，使用规则匹配模式")
            return

        try:
            from openai import OpenAI
            self.client = OpenAI(base_url=base_url, api_key=api_key)
            self.model = ai_cfg.get("model", "gpt-4o-mini")
            self.max_tokens = ai_cfg.get("max_tokens", 1500)
            self.temperature = ai_cfg.get("temperature", 0.2)
            print(f"[SearchAgent] AI 客户端初始化成功，模型: {self.model}")
        except ImportError:
            print("[SearchAgent] openai 库未安装，使用规则匹配模式")
        except Exception as e:
            print(f"[SearchAgent] AI 客户端初始化失败: {e}，使用规则匹配模式")

    @property
    def ai_available(self) -> bool:
        """AI 是否可用"""
        return self.client is not None

    # ============ Agent 主循环 ============

    def process(self, user_input: str, context: dict = None, fast_mode: bool = True) -> dict:
        """
        Agent 主入口：处理用户输入
        :param user_input: 用户自然语言输入
        :param context: 上下文 {"selected_files": [...]}
        :param fast_mode: True=简单搜索（跳过AI，规则转查询），False=AI智能搜索
        :return: 统一结果 {"success", "results", "error", "total", "message", "actions",
                           "content_results": [...]}
        """
        user_input = user_input.strip()
        if not user_input:
            return {"success": False, "results": [], "error": "输入为空", "total": 0, "message": ""}

        selected_files = (context or {}).get("selected_files", [])
        is_tagging = any(kw in user_input for kw in ['标记', '添加标签', '打标签', '归类', '标签',
                                                       '删除标签', '移除标签', '去掉标签'])

        # 先尝试规则匹配快速路径（标签操作等明确意图）
        quick_result = self._quick_match(user_input, context)
        if quick_result:
            return quick_result

        # 简单搜索模式：跳过 AI，直接用规则转 Everything 语法搜索
        if fast_mode and not selected_files and not is_tagging:
            return self._fast_search(user_input)

        # AI Agent 模式
        req_log = None
        if self.ai_available:
            try:
                req_log = AIRequestLogger(user_input, fast_mode=False)

                # 缓存逻辑：仅搜索、无上下文、非打标时查询缓存
                if not selected_files and not is_tagging:
                    cached = self.cache.get(user_input)
                    if cached:
                        logger.info(f"缓存命中: {user_input}")
                        result = self._agent_loop(user_input, context, skip_ai=json.dumps(cached, ensure_ascii=False))
                        req_log.log_search_result(
                            success=result.get('success', False),
                            total=result.get('total', 0),
                            message=result.get('message', ''),
                            cached=True
                        )
                        return result

                result = self._agent_loop(user_input, context, req_logger=req_log)

                # 搜索结果写入缓存
                if not selected_files and not is_tagging and result.get('success'):
                    cache_data = {
                        'action': 'search',
                        'message': result.get('message', ''),
                    }
                    actions = result.get('actions', [])
                    for a in actions:
                        if a.get('tool') == 'search_files':
                            cache_data['everything_query'] = a.get('args', {}).get('query', '')
                    self.cache.set(user_input, cache_data)

                req_log.log_search_result(
                    success=result.get('success', False),
                    total=result.get('total', 0),
                    error=result.get('error', ''),
                    message=result.get('message', '')
                )
                return result
            except Exception as e:
                error_msg = str(e)
                print(f"[SearchAgent] Agent 异常，降级到规则搜索: {error_msg}")
                if req_log:
                    req_log.log_api_error(0, error_msg, "Agent异常")
                    req_log.log_search_result(success=False, total=0, error=error_msg)

        # 规则降级：纯搜索
        query = self._build_everything_query(user_input)
        if self.search_engine:
            result = self.search_engine.search(query)
            result["message"] = f"搜索: {query}"
            return result
        return {"success": False, "results": [], "error": "搜索引擎不可用", "total": 0, "message": ""}

    def _agent_loop(self, user_input: str, context: dict = None, max_iterations: int = 6,
                     skip_ai: str = None, req_logger=None, api_timeout: int = 30) -> dict:
        """
        Agent 循环：AI 推理 → 调用工具 → 观察结果 → 继续推理或结束
        :param skip_ai: 缓存命中的 JSON 字符串，跳过 AI 直接执行工具调用
        :param req_logger: AIRequestLogger 实例，用于记录交互日志
        :param api_timeout: 单次 API 调用超时秒数
        """
        # 缓存命中：直接用缓存的 tool call 执行搜索
        if skip_ai:
            try:
                cached = json.loads(skip_ai)
                query = cached.get('everything_query', '')
                if query:
                    final_result = {"success": False, "results": [], "total": 0,
                                    "message": cached.get('message', ''),
                                    "actions": [], "content_results": [],
                                    "from_cache": True}
                    if self.search_engine:
                        if req_logger:
                            req_logger.log_tool_execution(
                                "search_files",
                                {"query": query},
                                "缓存命中，直接搜索"
                            )
                        search_result = self.search_engine.search(query)
                        final_result["success"] = search_result.get("success", True)
                        final_result["results"] = search_result.get("results", [])
                        final_result["total"] = search_result.get("total", 0)
                        final_result["actions"].append({
                            "tool": "search_files",
                            "args": {"query": query},
                            "result_summary": f"搜索到 {final_result['total']} 个文件"
                        })
                    return final_result
            except json.JSONDecodeError:
                pass
        messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]

        # 构造用户消息
        user_msg = user_input
        selected_files = (context or {}).get("selected_files", [])
        if selected_files:
            file_list = "\n".join(f"  - {f}" for f in selected_files[:20])
            user_msg += f"\n\n当前选中的文件：\n{file_list}"
            if len(selected_files) > 20:
                user_msg += f"\n  ... 共 {len(selected_files)} 个文件"

        messages.append({"role": "user", "content": user_msg})

        final_result = {"success": False, "results": [], "error": "", "total": 0, "message": "", "actions": [], "content_results": []}
        read_contents = {}  # 跟踪 read_file_contents 读取到的内容

        for iteration in range(max_iterations):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=api_timeout,
                )
            except Exception as api_err:
                error_msg = f"API 调用失败(第{iteration}轮): {api_err}"
                logger.error(error_msg)
                if req_logger:
                    req_logger.log_api_error(iteration, str(api_err), "API调用异常")
                final_result["error"] = error_msg
                # 如果已有搜索结果，返回部分结果
                if final_result.get("results"):
                    final_result["success"] = True
                    final_result["message"] = f"搜索到 {final_result.get('total', 0)} 个结果（AI 请求中断）"
                else:
                    final_result["message"] = f"AI 服务暂时不可用: {api_err}"
                break

            choice = response.choices[0]
            message = choice.message
            finish_reason = choice.finish_reason or ""

            # 记录 API 调用日志
            if req_logger:
                tool_names = [tc.function.name for tc in message.tool_calls] if message.tool_calls else []
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else "?",
                    "completion_tokens": response.usage.completion_tokens if response.usage else "?",
                    "total_tokens": response.usage.total_tokens if response.usage else "?"
                } if response.usage else None
                content_preview = message.content[:200] if message.content else ""
                req_logger.log_api_request(
                    iteration, self.model,
                    f"系统提示词 + {len(messages)}条消息",
                    len(message.tool_calls) if message.tool_calls else 0
                )
                req_logger.log_api_response(
                    iteration,
                    has_tool_calls=bool(message.tool_calls),
                    tool_names=tool_names,
                    content=message.content or "",
                    finish_reason=finish_reason,
                    usage=usage
                )

            # 没有工具调用 → Agent 给出最终回复
            if not message.tool_calls:
                # 如果还没有搜索结果，提示 AI 必须调用 search_files
                if not final_result.get("results"):
                    messages.append(message)
                    messages.append({
                        "role": "user",
                        "content": "你还没有调用 search_files 搜索文件！用户需要的是文件搜索结果，请先使用 search_files 工具搜索相关文件，然后再给出回复。"
                    })
                    continue
                final_result["message"] = message.content or ""
                final_result["success"] = True
                break

            # 处理工具调用
            messages.append(message)

            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                # 执行工具
                tool_result = self._execute_tool(func_name, func_args)
                result_summary = self._summarize_tool_result(func_name, tool_result)

                # 记录工具执行日志
                if req_logger:
                    req_logger.log_tool_execution(func_name, func_args, result_summary)

                # 记录动作
                final_result["actions"].append({
                    "tool": func_name,
                    "args": func_args,
                    "result_summary": result_summary
                })

                # 跟踪搜索结果
                if func_name == "search_files" and tool_result.get("success"):
                    final_result["success"] = True
                    new_results = tool_result.get("results", [])
                    if new_results:
                        existing = {r.get("full_path", "") for r in final_result["results"]}
                        for r in new_results:
                            if r.get("full_path", "") not in existing:
                                final_result["results"].append(r)
                                existing.add(r.get("full_path", ""))
                        final_result["total"] = len(final_result["results"])
                    elif not final_result["results"]:
                        final_result["total"] = 0
                elif func_name == "search_by_tag" and tool_result.get("success"):
                    final_result["success"] = True
                    final_result["results"] = tool_result.get("results", [])
                    final_result["total"] = tool_result.get("total", 0)
                elif func_name in ("add_tags", "remove_tags"):
                    final_result["success"] = tool_result.get("success", True)
                    final_result["message"] = tool_result.get("message", "")
                elif func_name == "read_file_contents" and tool_result.get("success"):
                    # 收集读取到的文件内容，供后续 AI 分析
                    read_contents.update(tool_result.get("contents", {}))

                # 将工具结果返回给 AI
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False, default=str)
                })

        # 如果循环结束但AI没有给出总结，生成默认消息
        if not final_result.get("message"):
            actions = final_result.get("actions", [])
            if actions:
                parts = []
                for a in actions:
                    if a["tool"] == "search_files":
                        parts.append(f"搜索到 {final_result.get('total', 0)} 个结果")
                    elif a["tool"] == "add_tags":
                        parts.append(a["result_summary"])
                    elif a["tool"] == "remove_tags":
                        parts.append(a["result_summary"])
                final_result["message"] = "；".join(parts) if parts else "操作完成"
            else:
                final_result["message"] = "未执行任何操作"

        # 内容搜索第二阶段：如果 Agent 读取了文件内容，调用 AI 做结构化内容分析
        if read_contents and self.ai_available and self.client:
            content_results = self.analyze_file_contents(read_contents, user_input)
            final_result["content_results"] = content_results
            logger.info(f"内容分析完成: {len(content_results)} 个匹配文件")

        return final_result

    def _execute_tool(self, name: str, args: dict) -> dict:
        """执行工具调用"""
        if name == "search_files":
            if not self.search_engine:
                return {"success": False, "error": "搜索引擎不可用", "results": [], "total": 0}
            return self.search_engine.search(args.get("query", ""), args.get("max_results", 100))

        elif name == "add_tags":
            if not self.tag_manager:
                return {"success": False, "message": "标签系统不可用"}
            files = args.get("files", [])
            tags = args.get("tags", [])
            if not files or not tags:
                return {"success": False, "message": "文件或标签为空"}
            return self.tag_manager.add_tags(files, tags)

        elif name == "remove_tags":
            if not self.tag_manager:
                return {"success": False, "message": "标签系统不可用"}
            files = args.get("files", [])
            tags = args.get("tags", [])
            if not files or not tags:
                return {"success": False, "message": "文件或标签为空"}
            return self.tag_manager.remove_tags(files, tags)

        elif name == "get_tags":
            if not self.tag_manager:
                return {"success": False, "tags": []}
            return {"success": True, "tags": self.tag_manager.get_tags(args.get("file_path", ""))}

        elif name == "list_all_tags":
            if not self.tag_manager:
                return {"success": False, "tags": []}
            return {"success": True, "tags": self.tag_manager.get_all_tags()}

        elif name == "search_by_tag":
            if not self.tag_manager:
                return {"success": False, "results": [], "total": 0}
            return self.tag_manager.search_by_tag(args.get("tag", ""))

        elif name == "suggest_tags":
            return {"success": True, "tags": self._suggest_tags_rule(args.get("file_info", {}))}

        elif name == "read_file_contents":
            file_paths = args.get("file_paths", [])
            if not file_paths:
                return {"success": False, "error": "未提供文件路径", "contents": {}}
            if not self.content_reader or not self.content_reader.enabled:
                return {"success": False, "error": "内容读取器未启用", "contents": {}}
            contents = {}
            for fp in file_paths[:20]:  # 最多20个
                if fp and os.path.isfile(fp):
                    text = self.content_reader.read_content(fp, 2000)
                    contents[fp] = text if text else "(无法提取内容或格式不支持)"
            return {"success": True, "contents": contents,
                    "found": len(contents), "requested": len(file_paths[:20])}

        return {"success": False, "error": f"未知工具: {name}"}

    def _summarize_tool_result(self, func_name: str, result: dict) -> str:
        """为 Agent 日志生成工具结果摘要"""
        if func_name == "search_files":
            total = result.get("total", 0)
            return f"搜索到 {total} 个文件"
        elif func_name == "add_tags":
            return result.get("message", "标签已添加")
        elif func_name == "remove_tags":
            return result.get("message", "标签已移除")
        elif func_name == "get_tags":
            tags = result.get("tags", [])
            return f"标签: {', '.join(tags) if tags else '无'}"
        elif func_name == "list_all_tags":
            tags = result.get("tags", [])
            return f"共 {len(tags)} 个标签"
        elif func_name == "search_by_tag":
            total = result.get("total", 0)
            return f"按标签搜索到 {total} 个文件"
        elif func_name == "suggest_tags":
            tags = result.get("tags", [])
            return f"推荐标签: {', '.join(tags) if tags else '无'}"
        elif func_name == "read_file_contents":
            total = result.get("found", 0)
            return f"读取了 {total} 个文件的内容"
        return str(result)

    # ============ 快速匹配（规则优先路径） ============

    def _quick_match(self, text: str, context: dict = None) -> Optional[dict]:
        """
        对明确意图（标签操作）走规则快速路径，不浪费 AI 调用
        返回 None 表示未匹配，交给 Agent 处理
        """
        selected_files = (context or {}).get("selected_files", [])

        # 删除标签
        for kw in UNTAG_KEYWORDS:
            if kw in text:
                tags = self._extract_tags(text, kw)
                if tags and self.tag_manager:
                    result = self.tag_manager.remove_tags(selected_files, tags)
                    result["actions"] = [{"tool": "remove_tags", "args": {"files": selected_files, "tags": tags}}]
                    return result
                return {"success": False, "message": "请指定要移除的标签", "results": [], "total": 0, "actions": []}

        # 查询标签
        for kw in QUERY_TAG_KEYWORDS:
            if kw in text:
                if selected_files and self.tag_manager:
                    tag_map = {fp: self.tag_manager.get_tags(fp) for fp in selected_files}
                    return {"success": True, "results": [], "total": 0,
                            "message": f"已查询 {len(selected_files)} 个文件的标签",
                            "tag_map": tag_map, "actions": []}
                return None  # 交给 Agent 处理更复杂的情况

        # 添加标签（有选中文件时走快速路径）
        for kw in TAG_KEYWORDS:
            if kw in text and selected_files:
                tags = self._extract_tags(text, kw)
                if tags and self.tag_manager:
                    result = self.tag_manager.add_tags(selected_files, tags)
                    result["actions"] = [{"tool": "add_tags", "args": {"files": selected_files, "tags": tags}}]
                    return result

        return None  # 未匹配，交给 Agent

    def _fast_search(self, user_input: str) -> dict:
        """快速搜索路径：规则转查询 → 直接搜索，跳过 AI"""
        query = self._build_everything_query(user_input)
        logger.info(f"快速搜索: '{user_input}' → '{query}'")
        if self.search_engine:
            result = self.search_engine.search(query)
            result["message"] = f"搜索: {query}"
            result["actions"] = [{
                "tool": "search_files",
                "args": {"query": query},
                "result_summary": f"搜索到 {result.get('total', 0)} 个文件"
            }]
            return result
        return {"success": False, "results": [], "error": "搜索引擎不可用", "total": 0, "message": ""}

    # ============ 规则降级搜索 ============

    @staticmethod
    def _normalize_path_keyword(path_val: str) -> str:
        """将中文路径描述转换为标准盘符路径
        例如: "E盘里" → "E:\\", "E盘" → "E:\\", "E:\\dir" 保持不变
        """
        import re as _re_path
        # "X盘里/中/下/内" → "X:\"
        m = _re_path.match(r'^([A-Za-z])\s*盘(?:里|中|下|内|上)?$', path_val)
        if m:
            return f"{m.group(1).upper()}:\\"
        # 已经是标准路径格式则保持不变
        if _re_path.match(r'^[A-Za-z]:[\\\\/]', path_val):
            return path_val
        return path_val

    def _build_everything_query(self, text: str) -> str:
        """将自然语言转为 Everything 搜索语法（规则降级方案）
        
        路径优先策略：所有主题/人名/系列关键词默认使用 path: 搜索，
        优先匹配路径和文件夹名，确保搜索结果完整。
        """
        parts = []
        remaining = text

        for type_name, ext_query in FILE_TYPE_MAP.items():
            if type_name in remaining:
                parts.append(ext_query)
                remaining = remaining.replace(type_name, "").strip()

        for date_kw, date_q in DATE_MAP.items():
            if date_kw in remaining:
                parts.append(date_q)
                remaining = remaining.replace(date_kw, "").strip()

        # 识别 ext:xxx 语法
        ext_syntax = re.findall(r'ext:\w+(?:;\w+)*', remaining, re.IGNORECASE)
        for ext in ext_syntax:
            parts.append(ext)
            remaining = remaining.replace(ext, "").strip()

        ext_patterns = re.findall(r'\*?\.\w+', remaining)
        for ext in ext_patterns:
            if not ext.startswith("*"):
                ext = "*" + ext
            parts.append(ext)
            remaining = remaining.replace(ext, "").strip()

        size_patterns = re.findall(r'(?:大于|超过|>)\s*(\d+)\s*(b|kb|mb|gb|tb)', remaining, re.IGNORECASE)
        for size_val, size_unit in size_patterns:
            unit = size_unit.upper()
            parts.append(f"size:>{size_val}{unit}")
            remaining = re.sub(r'(?:大于|超过|>)\s*\d+\s*(?:b|kb|mb|gb|tb)', '', remaining, flags=re.IGNORECASE).strip()

        path_match = re.search(r'(?:在|路径|path:)\s*(\S+)', remaining)
        if path_match:
            path_val = self._normalize_path_keyword(path_match.group(1))
            parts.append(f"path:{path_val}")
            remaining = remaining.replace(path_match.group(0), "").strip()

        # 兜底：检测裸 X盘 模式（不含"在"前缀的情况，如"E盘里的md文件"）
        standalone_drive = re.search(r'([A-Za-z])\s*盘', remaining)
        if standalone_drive:
            root = f"{standalone_drive.group(1).upper()}:\\"
            # 避免与上面重复添加
            if not any(root in p for p in parts):
                parts.append(f"path:{root}")
            remaining = remaining.replace(standalone_drive.group(0), "").strip()

        # 路径优先策略：剩余关键词默认使用 path: 搜索
        # 这样可以匹配路径/文件夹名中的主题、人名、系列
        remaining = re.sub(r'(?:的|里|中|下|内)', ' ', remaining).strip()
        
        # 过滤中文停用词（动词、量词等不应作为搜索关键词）
        stop_words = {'修改', '查找', '搜索', '寻找', '查找', '显示', '列出', '查看',
                       '所有', '全部', '那些', '这些', '一些', '哪个', '什么'}
        remaining_words = remaining.split()
        remaining_words = [w for w in remaining_words if w not in stop_words]
        remaining = ' '.join(remaining_words)
        
        if remaining:
            if ' ' not in remaining and not remaining.startswith('path:'):
                # 单个关键词 → path: 搜索（匹配路径和文件夹名）
                parts.append(f"path:{remaining}")
            else:
                # 多关键词或已含 path: → 原样保留
                parts.append(remaining)

        return " ".join(parts) if parts else text

    # ============ 标签提取 ============

    def _extract_tags(self, text: str, keyword: str) -> list:
        """从文本中提取标签"""
        remaining = text.replace(keyword, "").strip()
        tags = re.split(r'[,，、\s]+', remaining)
        tags = [t.strip() for t in tags if t.strip() and len(t.strip()) > 0]
        # 过滤无意义标签
        stop_words = {"的", "了", "是", "在", "这些", "那些", "这个", "那个", "文件", "给", "把"}
        tags = [t for t in tags if t not in stop_words]
        return tags

    # ============ 标签推荐（规则） ============

    def _suggest_tags_rule(self, file_info: dict) -> list:
        """根据文件信息推荐标签（规则方案）"""
        tags = []
        name = file_info.get("name", "").lower()
        ext = file_info.get("extension", "").lower()
        path = file_info.get("path", "").lower()

        ext_tag_map = {
            "pdf": ["文档", "PDF"], "doc": ["文档", "Word"], "docx": ["文档", "Word"],
            "xls": ["表格", "Excel"], "xlsx": ["表格", "Excel"],
            "ppt": ["演示", "PPT"], "pptx": ["演示", "PPT"],
            "jpg": ["图片"], "png": ["图片"], "gif": ["图片"],
            "mp4": ["视频"], "avi": ["视频"], "mkv": ["视频"],
            "mp3": ["音频"], "wav": ["音频"], "flac": ["音频"],
            "zip": ["压缩包"], "rar": ["压缩包"], "7z": ["压缩包"],
            "py": ["代码", "Python"], "js": ["代码", "JavaScript"],
            "java": ["代码", "Java"], "ts": ["代码", "TypeScript"],
            "go": ["代码", "Go"], "rs": ["代码", "Rust"],
            "html": ["代码", "前端"], "css": ["代码", "前端"],
        }
        if ext in ext_tag_map:
            tags.extend(ext_tag_map[ext])

        path_keywords = {
            "desktop": ["桌面"], "documents": ["文档"], "downloads": ["下载"],
            "pictures": ["图片"], "music": ["音乐"], "videos": ["视频"],
            "project": ["项目"], "work": ["工作"], "study": ["学习"],
        }
        for kw, tag_list in path_keywords.items():
            if kw in path:
                tags.extend(tag_list)

        return list(dict.fromkeys(tags))[:5]

    # ============ 内容相关性分析 ============

    def analyze_file_contents(self, file_contents: dict, user_query: str) -> list:
        """
        使用 AI 分析文件内容是否匹配用户搜索意图（二次分析）
        流程：文件名匹配候选文件 → 读取内容 → AI 判断内容是否真正相关
        :param file_contents: {file_path: text_content}
        :param user_query: 用户原始查询
        :return: [{"file_path": str, "file_name": str, "relevance": float,
                    "reason": str, "snippet": str}, ...]
        """
        if not file_contents or not self.ai_available:
            return []

        # 只保留有内容的文件
        valid = {fp: txt for fp, txt in file_contents.items() if txt and len(txt) > 20}
        if not valid:
            return []

        # 构造分析 prompt
        files_info = []
        for fp, txt in valid.items():
            fname = os.path.basename(fp)
            snippet = txt[:1000]
            files_info.append(f"--- {fname} ---\n路径: {fp}\n内容片段: {snippet}\n")

        prompt = f"""用户搜索意图: {user_query}

以下是通过文件名匹配找到的候选文件及其内容片段。请逐个分析：
1. 这个文件的内容是否真正包含/讨论了用户想找的东西？
2. 用户是在找"包含XXX内容"的文档，而非仅仅是"文件名叫XXX"的文档

候选文件列表:
{chr(10).join(files_info)}

请以 JSON 数组格式返回，只返回内容确实相关的文件（相关性 >= 0.3），按相关性从高到低排序:
[{{"file_path": "完整路径", "file_name": "文件名", "relevance": 0.0~1.0, "reason": "20字以内中文理由", "snippet": "最相关的内容片段(50字内)"}}]

判断标准:
- 用户想找包含特定内容的文档 → 检查文件内容是否确实包含/讨论该主题
- 文件名匹配但内容无关 → 不返回
- 文件名不匹配但内容高度相关 → 高分返回
- 模糊匹配也值得返回（如用户搜"机器学习"，文档讨论"神经网络"也算相关）
- 只返回 JSON 数组，不要任何其他文字"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是文件内容分析专家。只输出JSON数组，不要其他内容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1500,
            )
            content = response.choices[0].message.content or "[]"
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:])
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            results = json.loads(content)
            if isinstance(results, list):
                return results
        except Exception as e:
            logger.error(f"内容分析失败: {e}")

        return []

    def clear_cache(self):
        """清空 AI 缓存"""
        self.cache.clear()

    # ============ 兼容旧接口 ============

    def parse_intent(self, text: str, context: dict = None) -> dict:
        """
        兼容旧接口：解析意图
        对于标签操作返回 action dict，对于搜索走 Agent
        """
        selected_files = (context or {}).get("selected_files", [])

        # 标签操作快速路径
        for kw in UNTAG_KEYWORDS:
            if kw in text:
                return {"action": "untag", "tags": self._extract_tags(text, kw), "files": selected_files}

        for kw in QUERY_TAG_KEYWORDS:
            if kw in text:
                return {"action": "query_tags", "files": selected_files}

        for kw in TAG_KEYWORDS:
            if kw in text:
                return {"action": "tag", "tags": self._extract_tags(text, kw), "files": selected_files}

        # 搜索走规则
        query = self._build_everything_query(text)
        return {"action": "search", "everything_query": query}

    def suggest_tags(self, file_info: dict) -> list:
        """兼容旧接口：推荐标签"""
        return self._suggest_tags_rule(file_info)