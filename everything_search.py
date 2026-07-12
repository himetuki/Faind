"""
Faind 搜索模块
统一搜索入口，支持三种后端：fd（默认轻量）、Everything SDK DLL、ES.exe CLI
通过 config.search_engine 配置选择（"fd" / "everything_dll" / "everything_es" / "auto"）
"""

import ctypes
from ctypes import wintypes
import os
import re
import subprocess
import json
import threading
import time
from pathlib import Path
from datetime import datetime

import config

# Everything SDK 常量
EVERYTHING_OK = 0
EVERYTHING_ERROR_MEMORY = 1
EVERYTHING_ERROR_IPC = 2  # Everything 未运行
EVERYTHING_ERROR_REGISTERCLASSEX = 3
EVERYTHING_ERROR_CREATEWINDOW = 4
EVERYTHING_ERROR_CREATETHREAD = 5
EVERYTHING_ERROR_INVALIDINDEX = 6
EVERYTHING_ERROR_INVALIDCALL = 7
EVERYTHING_ERROR_INVALIDREQUEST = 8
EVERYTHING_ERROR_INVALIDPARAMETER = 9

# 请求标志
EVERYTHING_REQUEST_FILE_NAME = 0x00000001
EVERYTHING_REQUEST_PATH = 0x00000002
EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
EVERYTHING_REQUEST_EXTENSION = 0x00000008
EVERYTHING_REQUEST_SIZE = 0x00000010
EVERYTHING_REQUEST_DATE_CREATED = 0x00000020
EVERYTHING_REQUEST_DATE_MODIFIED = 0x00000040
EVERYTHING_REQUEST_DATE_ACCESSED = 0x00000080
EVERYTHING_REQUEST_ATTRIBUTES = 0x00000100

ERROR_MESSAGES = {
    EVERYTHING_OK: "无错误",
    EVERYTHING_ERROR_MEMORY: "内存不足",
    EVERYTHING_ERROR_IPC: "Everything 搜索客户端未运行，请先启动 Everything",
    EVERYTHING_ERROR_REGISTERCLASSEX: "无法注册窗口类",
    EVERYTHING_ERROR_CREATEWINDOW: "无法创建监听窗口",
    EVERYTHING_ERROR_CREATETHREAD: "无法创建监听线程",
    EVERYTHING_ERROR_INVALIDINDEX: "无效索引",
    EVERYTHING_ERROR_INVALIDCALL: "无效调用",
    EVERYTHING_ERROR_INVALIDREQUEST: "无效请求数据",
    EVERYTHING_ERROR_INVALIDPARAMETER: "无效参数",
}


def _filetime_to_datetime(filetime) -> str:
    """将 Windows FILETIME 转换为可读日期字符串"""
    if filetime.dwLowDateTime == 0 and filetime.dwHighDateTime == 0:
        return ""
    try:
        # FILETIME 是 100 纳秒间隔，从 1601-01-01 开始
        timestamp = (filetime.dwHighDateTime << 32) | filetime.dwLowDateTime
        # 转换为 Unix 时间戳
        unix_ts = (timestamp - 116444736000000000) / 10000000
        dt = datetime.fromtimestamp(unix_ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return ""


class FILETIME(ctypes.Structure):
    """Windows FILETIME 结构"""
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class LARGE_INTEGER(ctypes.Structure):
    """Windows LARGE_INTEGER 结构"""
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]
    
    @property
    def value(self):
        return (self.HighPart << 32) | self.LowPart


class EverythingSearch:
    """Everything SDK 封装类"""

    def __init__(self, dll_path: str = None):
        self.dll = None
        self._initialized = False
        self._use_cli = False
        self._es_cli_path = ""
        self._started_by_us = False      # 是否由 Faind 启动 Everything
        self._everything_process = None  # 子进程句柄
        self._index_ready = False        # 索引是否就绪

        # fd 搜索后端
        self._use_fd = False
        self._fd_path = ""
        fd_path = config.resolve_fd_path()
        if fd_path and os.path.isfile(fd_path):
            self._fd_path = fd_path

        # 始终探测 ES CLI 路径，作为运行时降级备用
        cli_path = config.resolve_es_cli_path()
        if cli_path and os.path.isfile(cli_path):
            self._es_cli_path = cli_path

        # Everything 服务管理
        self._everything_service_enabled = config.get_config_value("everything_service.enabled", False)
        self._transitional = False           # 过渡模式：正等待 Everything 就绪后从 fd 切换
        self._everything_status = 'not_enabled'  # not_enabled | not_started | starting | scanning | working | error
        self._monitoring = False             # 后台监控线程开关
        self._monitor_thread = None          # 监控线程句柄
        self._switch_failure_count = 0       # 切换失败计数（连续失败 5 次放弃）

        # 读取用户选择的搜索引擎
        engine_choice = config.get_config_value("search_engine", "auto")

        if engine_choice == "fd":
            self._init_fd()
        elif engine_choice == "everything_es":
            self._try_fallback_to_cli()
        elif engine_choice == "everything_dll":
            self._init_dll(dll_path)
        else:  # "auto" — 优先 fd（无需后台服务），其次 DLL，最后 ES CLI
            if not self._init_fd():
                if not self._init_dll(dll_path):
                    print("[EverythingSearch] DLL 不可用，尝试 ES CLI")
                    self._try_fallback_to_cli()

        # 过渡模式：用户启用了 Everything 服务 且 fd 可用
        if self._everything_service_enabled and self._use_fd:
            # 先检测用户是否已安装并运行了 Everything
            if self._try_init_dll_for_running_everything():
                # 用户已有 Everything 在运行，直接使用（绕过过渡模式）
                self._everything_status = 'working'
                self._started_by_us = False
                print("[EverythingSearch] 检测到用户已有 Everything 正在运行，直接使用")
            else:
                # Everything 未运行，进入过渡模式：先 fd 后等待 Everything 就绪
                self._transitional = True
                self._everything_status = 'not_started'
                print("[EverythingSearch] Everything 服务已启用，当前使用 fd 过渡，等待 Everything 就绪后切换")

    def _init_fd(self) -> bool:
        """初始化 fd 搜索后端"""
        if self._fd_path and os.path.isfile(self._fd_path):
            self._use_fd = True
            self._initialized = True
            self._index_ready = True  # fd 不需要索引，直接可用
            print(f"[EverythingSearch] 使用 fd 搜索后端: {self._fd_path}")
            return True
        else:
            print("[EverythingSearch] fd.exe 未找到，无法使用 fd 后端")
            return False

    def _init_dll(self, dll_path: str = None) -> bool:
        """初始化 Everything SDK DLL 后端"""
        if dll_path:
            self._load_dll(dll_path)
        else:
            resolved_path = config.resolve_dll_path()
            if resolved_path:
                self._load_dll(resolved_path)
            else:
                print("[EverythingSearch] 未找到 Everything64.dll")
                return False
        return self._initialized and not self._use_fd

    def _load_dll(self, dll_path: str):
        """加载 Everything SDK DLL"""
        try:
            if not os.path.isfile(dll_path):
                print(f"[EverythingSearch] DLL 文件不存在: {dll_path}")
                self._try_fallback_to_cli()
                return

            self.dll = ctypes.WinDLL(dll_path)
            self._setup_function_signatures()
            self._initialized = True
            print(f"[EverythingSearch] 成功加载 Everything SDK: {dll_path}")
        except OSError as e:
            print(f"[EverythingSearch] 加载 DLL 失败: {e}")
            self._try_fallback_to_cli()

    def _try_fallback_to_cli(self):
        """降级到 ES CLI 模式"""
        if self._es_cli_path and os.path.isfile(self._es_cli_path):
            self._use_cli = True
            self._initialized = True
            print(f"[EverythingSearch] 使用 ES CLI 模式: {self._es_cli_path}")
        else:
            print("[EverythingSearch] ES CLI 也未找到，搜索功能不可用")

    def _setup_function_signatures(self):
        """设置 DLL 函数签名（防御性：逐项设置，单函数失败不影响整体）"""
        dll = self.dll

        # 定义所有需要的函数签名: (attr_name, argtypes, restype)
        _SIGNATURES = [
            ("Everything_SetSearchW", [ctypes.c_wchar_p], None),
            ("Everything_SetMax", [wintypes.DWORD], None),
            ("Everything_SetOffset", [wintypes.DWORD], None),
            ("Everything_SetRequestFlags", [wintypes.DWORD], None),
            ("Everything_QueryW", [wintypes.BOOL], wintypes.BOOL),
            ("Everything_GetNumResults", [], wintypes.DWORD),
            ("Everything_GetLastError", [], wintypes.DWORD),
            ("Everything_GetResultFileNameW", [wintypes.DWORD], ctypes.c_wchar_p),
            ("Everything_GetResultPathW", [wintypes.DWORD], ctypes.c_wchar_p),
            ("Everything_GetResultFullPathNameW",
                [wintypes.DWORD, ctypes.c_wchar_p, wintypes.DWORD], wintypes.DWORD),
            ("Everything_GetResultExtensionW", [wintypes.DWORD], ctypes.c_wchar_p),
            ("Everything_GetResultSize",
                [wintypes.DWORD, ctypes.POINTER(LARGE_INTEGER)], wintypes.BOOL),
            ("Everything_GetResultDateModified",
                [wintypes.DWORD, ctypes.POINTER(FILETIME)], wintypes.BOOL),
            ("Everything_GetResultDateCreated",
                [wintypes.DWORD, ctypes.POINTER(FILETIME)], wintypes.BOOL),
            ("Everything_IsFolderResult", [wintypes.DWORD], wintypes.BOOL),
            ("Everything_Reset", [], None),
            ("Everything_IsDBLoaded", [], wintypes.BOOL),
        ]

        for name, argtypes, restype in _SIGNATURES:
            try:
                if not hasattr(dll, name):
                    print(f"[EverythingSearch] DLL 缺少导出函数: {name}")
                    continue
                func = getattr(dll, name)
                func.argtypes = argtypes
                func.restype = restype
            except Exception as e:
                print(f"[EverythingSearch] 设置函数签名失败 {name}: {e}")
                # 对于核心搜索函数，失败则标记不可用
                if name in ("Everything_SetSearchW", "Everything_QueryW",
                            "Everything_GetNumResults", "Everything_GetLastError"):
                    raise  # 无法继续，向上抛出

    @property
    def is_available(self) -> bool:
        """搜索功能是否可用（DLL 或 CLI 或 fd 任一可用）"""
        return self._initialized

    @property
    def is_fd_mode(self) -> bool:
        """是否使用 fd 后端"""
        return self._use_fd

    @property
    def is_cli_mode(self) -> bool:
        """是否使用 CLI 模式"""
        return self._use_cli

    @property
    def is_transitional(self) -> bool:
        """是否处于过渡模式（fd → Everything 切换中）"""
        return self._transitional

    @property
    def has_cli_fallback(self) -> bool:
        """是否有 CLI 降级可用"""
        return bool(self._es_cli_path) and os.path.isfile(self._es_cli_path)

    @property
    def everything_service_enabled(self) -> bool:
        """用户是否启用了 Everything 服务"""
        return self._everything_service_enabled

    @everything_service_enabled.setter
    def everything_service_enabled(self, value: bool):
        """运行时设置 Everything 服务开关"""
        self._everything_service_enabled = value
        if value:
            if self._use_fd and not self._transitional and not self.dll:
                # 先检测用户是否已有 Everything 在运行
                if self._try_init_dll_for_running_everything():
                    self._everything_status = 'working'
                    self._started_by_us = False
                    print("[EverythingSearch] 运行时启用：检测到用户已有 Everything 正在运行，直接使用")
                else:
                    self._transitional = True
                    if self._everything_status == 'not_enabled':
                        self._everything_status = 'not_started'
                    print("[EverythingSearch] 运行时启用：进入 fd 过渡模式，等待 Everything 就绪")
        else:
            self._transitional = False
            self._stop_monitoring()
            self.shutdown()
            self._everything_status = 'not_enabled'
            # 回退到纯 fd 模式
            if self._fd_path:
                self._init_fd()

    # ===== Everything 服务管理 =====

    def start_everything_service(self) -> bool:
        """
        启动 Everything 服务并在后台监控，就绪后自动从 fd 切换到 Everything。
        仅在 everything_service_enabled=True 且 fd 可用时有效。
        :return: 是否成功启动（服务已启动或正在监控）
        """
        if not self._everything_service_enabled:
            print("[EverythingSearch] Everything 服务未启用，跳过启动")
            return False

        if self.dll is not None and not self._use_fd:
            # Everything 已经在工作
            self._everything_status = 'working'
            print("[EverythingSearch] Everything 已在工作状态")
            return True

        if self._monitoring:
            print("[EverythingSearch] 正在监控 Everything 启动中...")
            return True

        # 在启动内嵌 Everything 前，再次探测用户是否已有 Everything 在运行
        if self._try_init_dll_for_running_everything():
            self._everything_status = 'working'
            self._started_by_us = False
            self._transitional = False
            print("[EverythingSearch] 检测到用户已有 Everything 在运行，取消内嵌启动")
            return True

        # 确保有 fd 可用（过渡模式的前置条件）
        if not self._fd_path:
            print("[EverythingSearch] fd 不可用，无法进入过渡模式，后台启动 Everything 并监控")
            self._transitional = False
            self._everything_status = 'starting'
            if not self._start_embedded_everything():
                self._everything_status = 'error'
                return False
            # 启动后台监控线程（监控进程启动 → 自动初始化）
            self._monitoring = True
            self._monitor_thread = threading.Thread(target=self._monitor_everything, daemon=True)
            self._monitor_thread.start()
            print("[EverythingSearch] 后台等待 Everything 就绪...")
            return True

        # 过渡模式：先用 fd 搜索，后台启动 Everything
        self._transitional = True
        self._use_fd = True
        self._index_ready = True  # fd 立即可用
        self._everything_status = 'starting'

        # 启动 Everything 进程
        if not self._start_embedded_everything():
            print("[EverythingSearch] Everything 启动失败，继续使用 fd")
            self._everything_status = 'error'
            self._transitional = False
            return False

        # 启动后台监控线程
        self._monitoring = True
        self._everything_status = 'scanning'
        self._monitor_thread = threading.Thread(target=self._monitor_everything, daemon=True)
        self._monitor_thread.start()
        print("[EverythingSearch] Everything 过渡模式：fd 可用，后台等待 Everything 索引就绪...")
        return True

    def _monitor_everything(self):
        """
        后台线程：等待 Everything 进程就绪 → 等待索引构建完成 → 自动切换到 DLL 后端。
        全程在后台运行，不阻塞 UI 线程。
        """
        # phase 1: 等待进程启动并初始化（最多 15 秒）
        for _ in range(30):
            time.sleep(0.5)
            if not self._monitoring:
                return
            if self.check_everything_running():
                print("[EverythingSearch] Everything 进程已就绪")
                break
        else:
            self._everything_status = 'error'
            print("[EverythingSearch] Everything 启动超时（15秒），继续使用 fd")
            return

        # 非 fd 路径：进程就绪后直接尝试初始化
        if not self._use_fd and not self._initialized:
            self._try_auto_init()
            if self._initialized and not self._use_fd:
                self._everything_status = 'working'
                self._monitoring = False
                print("[EverythingSearch] Everything 就绪，已初始化搜索后端")
                return
            # 初始化失败，继续使用 fd
            if self._fd_path:
                self._use_fd = True
                self._index_ready = True
                self._initialized = True
                self._everything_status = 'working'
                self._monitoring = False
                print("[EverythingSearch] Everything 初始化失败，回退到 fd")
                return

        # phase 2: 等待索引构建完成（MFT 扫描可能需要数分钟）
        for _ in range(240):
            time.sleep(1.5)
            if not self._monitoring:
                return
            if self._try_switch_to_everything():
                return  # 切换成功

        self._everything_status = 'error'
        print("[EverythingSearch] Everything 索引等待超时，继续使用 fd")

    def _try_switch_to_everything(self) -> bool:
        """
        尝试从 fd 切换到 Everything DLL。
        加载 DLL → 检查 IsDBLoaded → 如果就绪则完成切换。
        :return: 是否切换成功
        """
        try:
            resolved_dll = config.resolve_dll_path()
            if not resolved_dll or not os.path.isfile(resolved_dll):
                return False

            # 临时加载 DLL 检查索引状态
            try:
                test_dll = ctypes.WinDLL(resolved_dll)
            except OSError as e:
                print(f"[EverythingSearch] 加载 DLL 失败: {e}")
                self._switch_failure_count += 1
                if self._switch_failure_count >= 5:
                    print("[EverythingSearch] DLL 连续加载失败 5 次，放弃切换")
                    self._monitoring = False
                    self._everything_status = 'error'
                return False

            # 只设置探测所需的最少签名
            try:
                test_dll.Everything_IsDBLoaded.restype = wintypes.BOOL
            except Exception as e:
                print(f"[EverythingSearch] DLL 版本不兼容 (IsDBLoaded): {e}")
                self._switch_failure_count += 1
                if self._switch_failure_count >= 5:
                    print("[EverythingSearch] DLL 版本不兼容，放弃切换")
                    self._monitoring = False
                    self._everything_status = 'error'
                return False

            if not test_dll.Everything_IsDBLoaded():
                return False  # 索引未就绪，继续等待

            # 索引就绪！正式切换
            self.dll = test_dll
            self._setup_function_signatures()
            self._use_fd = False
            self._transitional = False
            self._use_cli = False
            self._initialized = True
            self._index_ready = True
            self._everything_status = 'working'
            self._monitoring = False
            self._started_by_us = True
            self._switch_failure_count = 0

            print("[EverythingSearch] ✅ Everything 索引就绪，已从 fd 切换到 Everything DLL")
            return True

        except Exception as e:
            print(f"[EverythingSearch] 切换 Everything 异常: {e}")
            self._switch_failure_count += 1
            if self._switch_failure_count >= 5:
                print("[EverythingSearch] 切换连续失败 5 次，放弃切换")
                self._monitoring = False
                self._everything_status = 'error'
            return False

    def _stop_monitoring(self):
        """停止后台监控线程"""
        self._monitoring = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)
            self._monitor_thread = None

    def get_everything_status(self) -> str:
        """
        获取 Everything 服务状态。
        :return: 'not_enabled' | 'not_started' | 'starting' | 'scanning' | 'working' | 'error'
        """
        if self.dll is not None and not self._use_fd:
            # DLL 已加载，检查是否真的在工作
            try:
                if self.dll.Everything_IsDBLoaded():
                    self._everything_status = 'working'
            except Exception as e:
                print(f"[EverythingSearch] 查询 Everything 状态异常: {e}")
                self._everything_status = 'error'
        elif self._use_fd and not self._transitional:
            # 纯 fd 模式，Everything 未启用
            if self._everything_status not in ('error',):
                self._everything_status = 'not_enabled'
        return self._everything_status

    def search(self, query: str, max_results: int = None, apply_filters: bool = True) -> dict:
        """
        执行搜索
        :param query: 搜索查询字符串（Everything 语法，fd 模式会自动转换）
        :param max_results: 最大结果数，默认从配置读取
        :param apply_filters: 是否应用搜索过滤器（排除系统文件夹等）
        :return: {"success": bool, "results": [...], "error": str, "total": int}
        """
        if not self._initialized:
            return {
                "success": False,
                "results": [],
                "error": "搜索未初始化，请检查配置",
                "total": 0
            }

        if max_results is None:
            max_results = config.get_config_value("ui.max_results", 100)

        # 构建带过滤器的查询
        filtered_query = query
        filter_config = {}
        if apply_filters:
            filter_config = config.get_config_value("search_filters", {})
            if filter_config.get("enabled", True):
                if self._use_fd:
                    filtered_query = query  # fd 模式后处理过滤
                else:
                    filtered_query = self._apply_query_filters(query, filter_config)

        if self._use_fd:
            result = self._search_via_fd(filtered_query, max_results)
        elif self._use_cli:
            result = self._search_via_cli(filtered_query, max_results)
        else:
            result = self._search_via_dll(filtered_query, max_results)
            # DLL 搜索遇到 IPC 错误（Everything 未运行），自动降级到 CLI
            if not result["success"] and self._es_cli_path:
                error_code = result.get("error_code", 0)
                if error_code == EVERYTHING_ERROR_IPC:
                    print("[EverythingSearch] Everything 未运行，自动降级到 ES CLI 模式")
                    self._use_cli = True
                    self._initialized = True
                    result = self._search_via_cli(filtered_query, max_results)

        # 路径优先重试：结果太少且查询不含 path: 时，自动用 path: 重试（仅 Everything 后端）
        if not self._use_fd and result.get("success") and result.get("total", 0) < 5 and "path:" not in query:
            path_query = self._rewrite_with_path_prefix(query)
            if path_query != query:
                print(f"[EverythingSearch] 结果较少({result['total']}个)，尝试路径搜索: {path_query}")
                path_filtered_query = path_query
                if apply_filters:
                    filter_config = config.get_config_value("search_filters", {})
                    if filter_config.get("enabled", True):
                        path_filtered_query = self._apply_query_filters(path_query, filter_config)
                
                if self._use_cli:
                    path_result = self._search_via_cli(path_filtered_query, max_results)
                else:
                    path_result = self._search_via_dll(path_filtered_query, max_results)
                
                if path_result.get("success") and path_result.get("total", 0) > result.get("total", 0):
                    # 合并结果，去重
                    existing_paths = {r["full_path"] for r in result.get("results", [])}
                    for item in path_result.get("results", []):
                        if item["full_path"] not in existing_paths:
                            result["results"].append(item)
                            existing_paths.add(item["full_path"])
                    result["total"] = len(result["results"])

        # 后处理：CLI 模式下额外过滤 + 文件夹排序
        if result.get("success") and result.get("results"):
            if apply_filters and filter_config.get("enabled", True):
                result["results"] = self._post_filter_results(result["results"], filter_config)
            result["results"] = self._sort_by_folder_order(result["results"], filter_config)
            result["total"] = len(result["results"])

        return result

    def _rewrite_with_path_prefix(self, query: str) -> str:
        """
        将查询改写为路径优先搜索
        例如: 'Candydoll ext:jpg' → 'path:Candydoll ext:jpg'
        例如: 'Candydoll' → 'path:Candydoll'
        不改写已含 path: 的查询，也不改写纯语法查询
        """
        import re
        # 如果已经含 path: 或 folder:，不再改写
        if "path:" in query or "folder:" in query:
            return query
        
        # 提取 Everything 语法前缀（ext:, dm:, size: 等）和关键词部分
        # 策略：找到第一个非语法关键词，给它加 path: 前缀
        parts = query.split()
        keywords = []  # 纯关键词部分
        syntax_parts = []  # 语法部分（ext:, dm:, size:, !path: 等）
        
        for part in parts:
            # 语法前缀
            if re.match(r'^(ext:|dm:|dc:|da:|size:|folder:|path:|!path:|infolder:|type:)', part):
                syntax_parts.append(part)
            elif part.startswith("*") or part.startswith("|") or part.startswith("!"):
                syntax_parts.append(part)
            else:
                keywords.append(part)
        
        if not keywords:
            return query  # 纯语法查询，不改写
        
        # 对关键词部分加 path: 前缀
        path_keywords = [f"path:{kw}" for kw in keywords]
        
        # 组合：path关键词 + 语法部分
        return " ".join(path_keywords + syntax_parts)

    def _apply_query_filters(self, query: str, filter_config: dict) -> str:
        """将排除规则转换为 Everything 搜索语法的 !path: 排除条件"""
        exclude_folders = filter_config.get("exclude_folders", [])
        exclude_paths = filter_config.get("exclude_paths", [])
        
        parts = [query]
        for folder in exclude_folders:
            # Everything 语法: !path:folder 排除路径中包含 folder 的结果
            parts.append(f'!path:"{folder}"')
        for path in exclude_paths:
            parts.append(f'!path:"{path}"')
        
        return " ".join(parts)

    def _post_filter_results(self, results: list, filter_config: dict) -> list:
        """后处理过滤：对 fd/CLI 模式结果进行路径排除（DLL 模式通过查询语法已排除）"""
        if self._use_cli or self._use_fd:
            exclude_folders = filter_config.get("exclude_folders", [])
            exclude_paths = filter_config.get("exclude_paths", [])
            filtered = []
            for item in results:
                full_path = item.get("full_path", "")
                path_parts = full_path.replace("/", "\\").split("\\")
                # 检查是否包含排除的文件夹名
                skip = False
                for folder in exclude_folders:
                    if folder in path_parts:
                        skip = True
                        break
                if not skip:
                    for exc_path in exclude_paths:
                        if full_path.lower().startswith(exc_path.lower()):
                            skip = True
                            break
                if not skip:
                    filtered.append(item)
            return filtered
        return results

    def _sort_by_folder_order(self, results: list, filter_config: dict) -> list:
        """根据 folder_sort_order 配置排序结果"""
        order = filter_config.get("folder_sort_order", "first") if filter_config else "first"
        if order == "none":
            return results
        folders = [r for r in results if r.get("is_folder")]
        files = [r for r in results if not r.get("is_folder")]
        if order == "first":
            return folders + files
        elif order == "last":
            return files + folders
        return results

    def _search_via_dll(self, query: str, max_results: int) -> dict:
        """通过 DLL SDK 执行搜索"""
        try:
            # 重置状态
            self.dll.Everything_Reset()

            # 设置搜索参数
            self.dll.Everything_SetSearchW(query)
            self.dll.Everything_SetMax(max_results)
            self.dll.Everything_SetOffset(0)

            # 请求需要的字段
            request_flags = (
                EVERYTHING_REQUEST_FILE_NAME |
                EVERYTHING_REQUEST_PATH |
                EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME |
                EVERYTHING_REQUEST_EXTENSION |
                EVERYTHING_REQUEST_SIZE |
                EVERYTHING_REQUEST_DATE_MODIFIED |
                EVERYTHING_REQUEST_DATE_CREATED |
                EVERYTHING_REQUEST_ATTRIBUTES
            )
            self.dll.Everything_SetRequestFlags(request_flags)

            # 执行查询
            success = self.dll.Everything_QueryW(True)  # 等待完成
            if not success:
                error_code = self.dll.Everything_GetLastError()
                error_msg = ERROR_MESSAGES.get(error_code, f"未知错误 (代码: {error_code})")
                return {
                    "success": False,
                    "results": [],
                    "error": error_msg,
                    "error_code": error_code,
                    "total": 0
                }

            # 获取结果数量
            num_results = self.dll.Everything_GetNumResults()
            results = []

            for i in range(num_results):
                result = self._get_result_item(i)
                if result:
                    results.append(result)

            return {
                "success": True,
                "results": results,
                "error": "",
                "total": num_results
            }

        except Exception as e:
            return {
                "success": False,
                "results": [],
                "error": f"搜索异常: {str(e)}",
                "total": 0
            }

    def _get_result_item(self, index: int) -> dict:
        """获取单个搜索结果"""
        try:
            # 文件名
            name = self.dll.Everything_GetResultFileNameW(index) or ""

            # 路径
            path = self.dll.Everything_GetResultPathW(index) or ""

            # 完整路径
            buf_size = 4096
            buf = ctypes.create_unicode_buffer(buf_size)
            self.dll.Everything_GetResultFullPathNameW(index, buf, buf_size)
            full_path = buf.value or ""

            # 扩展名
            ext = self.dll.Everything_GetResultExtensionW(index) or ""

            # 大小
            size_val = LARGE_INTEGER()
            has_size = self.dll.Everything_GetResultSize(index, ctypes.byref(size_val))
            size_str = ""
            if has_size:
                size_str = self._format_size(size_val.value)

            # 修改日期
            date_modified = FILETIME()
            has_modified = self.dll.Everything_GetResultDateModified(index, ctypes.byref(date_modified))
            modified_str = _filetime_to_datetime(date_modified) if has_modified else ""

            # 创建日期
            date_created = FILETIME()
            has_created = self.dll.Everything_GetResultDateCreated(index, ctypes.byref(date_created))
            created_str = _filetime_to_datetime(date_created) if has_created else ""

            # 是否为文件夹
            is_folder = bool(self.dll.Everything_IsFolderResult(index))

            return {
                "name": name,
                "path": path,
                "full_path": full_path,
                "extension": ext.lower(),
                "size": size_str,
                "date_modified": modified_str,
                "date_created": created_str,
                "is_folder": is_folder
            }
        except Exception as e:
            print(f"[EverythingSearch] 获取结果 {index} 失败: {e}")
            return None

    def _search_via_cli(self, query: str, max_results: int) -> dict:
        """通过 ES CLI 执行搜索（降级方案）"""
        try:
            # ES CLI 输出格式: 路径
            cmd = [
                self._es_cli_path,
                "-n", str(max_results),  # 限制结果数
                "-sort", "date-modified-descending",
                query
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"ES CLI 返回错误代码: {result.returncode}"
                return {
                    "success": False,
                    "results": [],
                    "error": error_msg,
                    "total": 0
                }

            lines = result.stdout.strip().split("\n")
            results = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                full_path = line
                name = os.path.basename(full_path)
                path = os.path.dirname(full_path)
                _, ext = os.path.splitext(name)
                is_folder = os.path.isdir(full_path) if os.path.exists(full_path) else False
                
                # 获取文件信息（如果文件存在）
                size_str = ""
                modified_str = ""
                try:
                    if os.path.exists(full_path):
                        stat = os.stat(full_path)
                        size_str = self._format_size(stat.st_size)
                        modified_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                except (OSError, PermissionError):
                    pass

                results.append({
                    "name": name,
                    "path": path,
                    "full_path": full_path,
                    "extension": ext.lstrip(".").lower(),
                    "size": size_str,
                    "date_modified": modified_str,
                    "date_created": "",
                    "is_folder": is_folder
                })

            return {
                "success": True,
                "results": results,
                "error": "",
                "total": len(results)
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "results": [],
                "error": "搜索超时",
                "total": 0
            }
        except FileNotFoundError:
            return {
                "success": False,
                "results": [],
                "error": f"ES CLI 未找到: {self._es_cli_path}",
                "total": 0
            }
        except Exception as e:
            return {
                "success": False,
                "results": [],
                "error": f"CLI 搜索异常: {str(e)}",
                "total": 0
            }

    def _search_via_fd(self, query: str, max_results: int) -> dict:
        """通过 fd CLI 执行搜索"""
        try:
            args = self._build_fd_args(query, max_results)
            cmd = [self._fd_path] + args
            print(f"[EverythingSearch] fd: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0x08000000,
            )

            if result.returncode != 0 and result.returncode != 1:
                # rc=1 可能是没找到结果，正常情况
                error_msg = result.stderr.strip() or f"fd 返回错误代码: {result.returncode}"
                return {
                    "success": False,
                    "results": [],
                    "error": error_msg,
                    "total": 0
                }

            lines = result.stdout.strip().split("\n")
            results = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                full_path = line
                name = os.path.basename(full_path)
                path = os.path.dirname(full_path)
                _, ext = os.path.splitext(name)
                is_folder = os.path.isdir(full_path) if os.path.exists(full_path) else False

                # 获取文件信息
                size_str = ""
                modified_str = ""
                try:
                    if os.path.exists(full_path):
                        stat = os.stat(full_path)
                        size_str = self._format_size(stat.st_size)
                        modified_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                except (OSError, PermissionError):
                    pass

                results.append({
                    "name": name,
                    "path": path,
                    "full_path": full_path,
                    "extension": ext.lstrip(".").lower(),
                    "size": size_str,
                    "date_modified": modified_str,
                    "date_created": "",
                    "is_folder": is_folder
                })

            return {
                "success": True,
                "results": results,
                "error": "",
                "total": len(results)
            }

        except FileNotFoundError:
            return {
                "success": False,
                "results": [],
                "error": f"fd 未找到: {self._fd_path}",
                "total": 0
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "results": [],
                "error": "fd 搜索超时",
                "total": 0
            }
        except Exception as e:
            return {
                "success": False,
                "results": [],
                "error": f"fd 搜索异常: {str(e)}",
                "total": 0
            }

    def _build_fd_args(self, query: str, max_results: int) -> list:
        """
        将 Everything 搜索语法转换为 fd 命令行参数。

        fd 支持: regex 模式匹配、-e 扩展名、--full-path 全路径、--type d/f 类型、
                 --changed-within 修改时间、--size 文件大小

        翻译规则:
        - ext:xxx → -e xxx
        - path:xxx → --full-path + regex 匹配完整路径
        - folder: → --type d
        - !path:xxx → -E 排除 glob
        - size:>xxx → --size +xxx
        - dm:xxx → --changed-within xxx
        - 普通关键词 → regex pattern（匹配完整路径）
        """
        import re as _re

        args = []

        # 解析 Everything 搜索语法
        keywords = []      # 普通关键词
        extensions = []    # ext:xxx
        path_patterns = [] # path:xxx
        exclude_paths = [] # !path:xxx → -E glob
        is_folder = False  # folder:
        size_filters = []  # size:>xxx → --size +xxx / --size -xxx
        date_filters = []  # dm:xxx → --changed-within xxx

        parts = query.split()
        for part in parts:
            # 排除路径 !path:xxx
            if part.startswith("!path:"):
                p = part[len("!path:"):].strip('"').strip("'")
                exclude_paths.append(p)
            # 路径 path:xxx
            elif part.startswith("path:"):
                p = part[len("path:"):].strip('"').strip("'")
                path_patterns.append(p)
            # 扩展名 ext:xxx
            elif part.startswith("ext:"):
                exts = part[len("ext:"):].split(";")
                for e in exts:
                    e = e.strip().lstrip(".")
                    if e:
                        extensions.append(e)
            # 文件夹
            elif part.startswith("folder:"):
                is_folder = True
            # 大小
            elif part.startswith("size:"):
                size_filters.append(part)
            # 日期
            elif part.startswith("dm:") or part.startswith("dc:") or part.startswith("da:"):
                date_filters.append(part)
            # 普通关键词
            elif part and not part.startswith("*") and not part.startswith("!"):
                keywords.append(part)

        # ============================================================
        # 1. 构建主搜索 pattern（正则，匹配完整路径）
        # ============================================================
        if keywords:
            escaped = [_re.escape(kw) for kw in keywords]
            pattern = "|".join(escaped)
            args.append(pattern)
        elif is_folder or extensions or size_filters or date_filters:
            args.append(".")
        else:
            args.append(".")

        # ============================================================
        # 2. --full-path：让正则匹配完整路径而非仅文件名
        # ============================================================
        args.append("--full-path")

        # ============================================================
        # 3. --type (文件/文件夹)
        # ============================================================
        if is_folder:
            args.extend(["--type", "d"])
        else:
            args.extend(["--type", "f"])

        # ============================================================
        # 4. -e 扩展名
        # ============================================================
        for ext in extensions:
            if ext and ext != "*":
                args.extend(["-e", ext])

        # ============================================================
        # 5. --changed-within 日期筛选
        #    Everything 语法: dm:today / dm:thisweek / dm:lastweek / dm:>2024-01-01
        #    fd 语法:         --changed-within 1d / 1w / 2w / 2024-01-01..
        # ============================================================
        for df in date_filters:
            fd_date = self._convert_date_filter_to_fd(df)
            if fd_date:
                args.extend(["--changed-within", fd_date])

        # ============================================================
        # 6. --size 大小筛选
        #    Everything 语法: size:>100mb / size:<1kb
        #    fd 语法:          --size +100m / --size -1k
        # ============================================================
        for sf in size_filters:
            fd_size = self._convert_size_filter_to_fd(sf)
            if fd_size:
                args.extend(["--size", fd_size])

        # ============================================================
        # 7. -E 排除路径（fd 的 glob 排除模式）
        #    !path:xxx → -E "*xxx*"
        # ============================================================
        for ep in exclude_paths:
            args.extend(["-E", f"*{ep}*"])

        # ============================================================
        # 8. --full-path 路径关键词合并到 regex
        #    盘符已被 _extract_search_roots 处理，其余路径关键词需匹配完整路径
        # ============================================================
        non_drive_paths = [p for p in path_patterns
                           if not _re.match(r'^[A-Za-z]\s*[:\\\\]', p)]
        if non_drive_paths:
            if keywords or args[0] != ".":
                path_regex = "|".join([_re.escape(p) for p in non_drive_paths])
                args[0] = f"({path_regex}).*({args[0]})"
            else:
                path_regex = "|".join([_re.escape(p) for p in non_drive_paths])
                args[0] = f"({path_regex})"

        # ============================================================
        # 9. --max-results
        # ============================================================
        args.extend(["--max-results", str(max_results)])

        # 排除隐藏/忽略文件，提升速度
        args.extend(["--hidden", "--no-ignore"])

        # 搜索根目录：从 path: 和盘符中提取，没有指定则全盘搜索
        search_roots = self._extract_search_roots(path_patterns, keywords)
        args.extend(search_roots)

        return args

    @staticmethod
    def _convert_date_filter_to_fd(date_filter: str) -> str:
        """
        将 Everything 日期语法转换为 fd --changed-within 参数。

        Everything → fd:
          dm:today     → 1d
          dm:yesterday → 2d
          dm:thisweek  → 1w
          dm:lastweek  → 2w
          dm:thismonth → 1month
          dm:lastmonth → 2month
          dm:thisyear  → 1year
          dm:>YYYY-MM-DD → YYYY-MM-DD.. (fd 接受日期范围)
          dm:YYYY-MM-DD  → YYYY-MM-DD..YYYY-MM-DD
        dc:/da: 同理（fd 的 --changed-within 基于 mtime）
        """
        import re as _re_d

        val = date_filter.split(":", 1)[1] if ":" in date_filter else ""
        val = val.strip()

        # 相对时间
        RELATIVE_MAP = {
            "today": "1d",
            "yesterday": "2d",
            "thisweek": "1w",
            "lastweek": "2w",
            "thismonth": "1month",
            "lastmonth": "2month",
            "thisyear": "1year",
            "lastyear": "2year",
        }
        if val.lower() in RELATIVE_MAP:
            return RELATIVE_MAP[val.lower()]

        # 大于某日期: dm:>2024-01-01 → "2024-01-01.."
        if val.startswith(">"):
            return f"{val[1:].strip()}.."

        # 小于某日期: dm:<2024-01-01 → "..2024-01-01"
        if val.startswith("<"):
            return f"..{val[1:].strip()}"

        # 范围: dm:2024-01-01-2024-12-31 → "2024-01-01..2024-12-31"
        range_match = _re_d.match(r'^(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})$', val)
        if range_match:
            return f"{range_match.group(1)}..{range_match.group(2)}"

        # 单日: dm:2024-01-01 → "2024-01-01..2024-01-01"
        if _re_d.match(r'^\d{4}-\d{2}-\d{2}$', val):
            return f"{val}..{val}"

        # 无法识别，返回空
        return ""

    @staticmethod
    def _convert_size_filter_to_fd(size_filter: str) -> str:
        """
        将 Everything 大小语法转换为 fd --size 参数。

        Everything → fd:
          size:>100mb  → +100m
          size:<1kb    → -1k
          size:>=100mb → +100m
          size:<=1kb   → -1k
          size:100kb..1mb → 100k..1m
          size:unknown  → "" (不支持的格式)
        """
        import re as _re_s

        val = size_filter.split(":", 1)[1] if ":" in size_filter else ""
        val = val.strip()

        # 标准化单位: kb→k, mb→m, gb→g, tb→t
        def _normalize_unit(s: str) -> str:
            s = s.lower()
            for unit in ["kb", "mb", "gb", "tb", "b"]:
                if s.endswith(unit):
                    return s.replace(unit, unit[0] if unit != "b" else "b")
            return s

        # 范围: size:100kb..1mb → 100k..1m
        range_match = _re_s.match(r'^(\d+[kmgtb]*)\.\.(\d+[kmgtb]*)$', val, _re_s.IGNORECASE)
        if range_match:
            lo = _normalize_unit(range_match.group(1))
            hi = _normalize_unit(range_match.group(2))
            return f"{lo}..{hi}"

        # 大于等于: >=100mb
        gte_match = _re_s.match(r'^>=\s*(\d+[kmgtb]*)$', val, _re_s.IGNORECASE)
        if gte_match:
            return f"+{_normalize_unit(gte_match.group(1))}"

        # 小于等于: <=1kb
        lte_match = _re_s.match(r'^<=\s*(\d+[kmgtb]*)$', val, _re_s.IGNORECASE)
        if lte_match:
            return f"-{_normalize_unit(lte_match.group(1))}"

        # 大于: >100mb
        gt_match = _re_s.match(r'^>\s*(\d+[kmgtb]*)$', val, _re_s.IGNORECASE)
        if gt_match:
            return f"+{_normalize_unit(gt_match.group(1))}"

        # 小于: <1kb
        lt_match = _re_s.match(r'^<\s*(\d+[kmgtb]*)$', val, _re_s.IGNORECASE)
        if lt_match:
            return f"-{_normalize_unit(lt_match.group(1))}"

        return ""

    def _get_search_roots(self) -> list:
        """获取搜索根目录列表（所有可用盘符）"""
        roots = []
        try:
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                p = f"{letter}:\\"
                if os.path.exists(p):
                    roots.append(p)
        except Exception as e:
            # 回退：搜索当前目录
            print(f"[EverythingSearch] 获取搜索根目录失败: {e}")
            roots.append(".")
        return roots

    def _extract_search_roots(self, path_patterns: list, keywords: list = None) -> list:
        """
        从 query 中提取搜索限定目录。
        - 如果 path: 包含盘符（如 E:、E:\），只搜索对应盘符
        - 如果 path: 包含具体路径（如 E:/projects），以该路径为根搜索
        - 如果没有 path 限制，默认全盘搜索
        :return: 搜索根目录列表
        """
        import re as _re2

        specific_roots = []
        for p in (path_patterns or []):
            # 匹配盘符模式: E: 或 E:\ 或 E:/ 或 E\\
            drive_match = _re2.match(r'^([A-Za-z])\s*[:\\\\]', p)
            if drive_match:
                root = f"{drive_match.group(1).upper()}:\\"
                if os.path.exists(root):
                    specific_roots.append(root)
                    continue
            # 匹配具体路径: E:\projects\foo
            path_match = _re2.match(r'^([A-Za-z]:[\\\\/][^\s*?|]+)', p)
            if path_match:
                candidate = path_match.group(1).rstrip("\\/")
                if os.path.isdir(candidate):
                    specific_roots.append(candidate)
                    continue

        # 从 keywords 中检测裸盘符: "E:" "D:" 等
        if not specific_roots and keywords:
            for kw in keywords:
                drive_match = _re2.match(r'^([A-Za-z])\s*:$', kw)
                if drive_match:
                    root = f"{drive_match.group(1).upper()}:\\"
                    if os.path.exists(root):
                        specific_roots.append(root)

        if specific_roots:
            print(f"[EverythingSearch] fd 搜索范围: {specific_roots}")
            return specific_roots

        return self._get_search_roots()

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小"""
        if size < 0:
            return ""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def ensure_everything_running(self) -> bool:
        """
        确保搜索后端就绪。
        fd 模式但没有启用 Everything 服务：直接返回 True。
        过渡模式：启动 Everything 服务并后台监控。
        Everything 模式：启动内嵌 Everything 便携版。
        :return: 搜索是否可用
        """
        # 纯 fd 模式（用户未启用 Everything 服务）
        if self._use_fd and not self._everything_service_enabled:
            print("[EverythingSearch] fd 模式无需后台服务，直接可用")
            return True

        # 过渡模式：fd 已可用，后台启动 Everything
        if self._everything_service_enabled and self._transitional:
            print("[EverythingSearch] 过渡模式：fd 已就绪，启动 Everything 服务...")
            self.start_everything_service()
            return True  # fd 已可用，不需要阻塞

        # Everything 已在工作
        if self._everything_service_enabled and self.dll is not None and not self._use_fd:
            print("[EverythingSearch] Everything 已在工作状态")
            if not self.check_everything_running():
                print("[EverythingSearch] Everything 进程异常，尝试重启")
                return self._start_embedded_everything()
            return True

        # 1. 检查是否已在运行（用户已安装的 Everything）
        if self.check_everything_running():
            print("[EverythingSearch] 检测到 Everything 已在运行，使用现有服务")
            self._started_by_us = False
            return True

        # 2. 未运行，启动内嵌便携版
        print("[EverythingSearch] Everything 未运行，尝试启动内嵌版本...")
        return self._start_embedded_everything()

    def _start_embedded_everything(self) -> bool:
        """启动内嵌的 Everything 便携版（非阻塞，仅负责启动进程，等待由后台监控线程处理）"""
        everything_dir = config._ensure_everything_extracted()

        # 尝试两种可执行文件名
        everything_exe = None
        for name in ("Everything64.exe", "Everything.exe"):
            candidate = everything_dir / name
            if candidate.is_file():
                everything_exe = candidate
                break

        if everything_exe is None:
            print(f"[EverythingSearch] 内嵌 Everything 不存在于: {everything_dir}")
            return False

        try:
            ini_path = everything_dir / "Everything.ini"
            cmd = [str(everything_exe)]
            if ini_path.exists():
                cmd += ["-config", str(ini_path)]
            cmd.append("-startup")

            print(f"[EverythingSearch] 启动内嵌 Everything: {' '.join(cmd)}")

            # 创建进程，隐藏窗口
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0x08000000
            self._everything_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._started_by_us = True
            print(f"[EverythingSearch] 内嵌 Everything 进程已启动，后台等待就绪")
            return True

        except FileNotFoundError:
            print(f"[EverythingSearch] 无法启动 Everything: 文件不存在 {everything_exe}")
            return False
        except Exception as e:
            print(f"[EverythingSearch] 启动 Everything 失败: {e}")
            return False

    def _try_init_dll_for_running_everything(self) -> bool:
        """
        检测用户是否已安装并运行了 Everything，若是则直接加载 DLL 使用。
        仅在 fd 可用 + Everything 服务启用时调用，用于跳过不必要的过渡模式。
        :return: 是否成功加载 DLL 并确认 Everything 正在工作
        """
        resolved_dll = config.resolve_dll_path()
        if not resolved_dll or not os.path.isfile(resolved_dll):
            return False

        try:
            test_dll = ctypes.WinDLL(resolved_dll)
            # 只设置最关键的签名用于探测
            test_dll.Everything_IsDBLoaded.restype = wintypes.BOOL
            test_dll.Everything_Reset.argtypes = []
            test_dll.Everything_Reset.restype = None
            test_dll.Everything_QueryW.argtypes = [wintypes.BOOL]
            test_dll.Everything_QueryW.restype = wintypes.BOOL
            test_dll.Everything_GetLastError.argtypes = []
            test_dll.Everything_GetLastError.restype = wintypes.DWORD

            if test_dll.Everything_IsDBLoaded():
                # 用户 Everything 正在运行且索引就绪，直接正式加载
                self.dll = test_dll
                self._setup_function_signatures()
                self._use_fd = False
                self._use_cli = False
                self._transitional = False
                self._initialized = True
                self._index_ready = True
                return True

            # DB 未就绪，再试一次简单的 IPC 查询（Everything 可能在扫描但还没加载完 DB）
            test_dll.Everything_Reset()
            test_dll.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
            test_dll.Everything_SetSearchW.restype = None
            test_dll.Everything_SetSearchW("")
            test_dll.Everything_SetMax.argtypes = [wintypes.DWORD]
            test_dll.Everything_SetMax.restype = None
            test_dll.Everything_SetMax(1)
            if test_dll.Everything_QueryW(True):
                error = test_dll.Everything_GetLastError()
                # 只要不是 IPC 错误，就说明 Everything 在运行
                if error != EVERYTHING_ERROR_IPC:
                    self.dll = test_dll
                    self._setup_function_signatures()
                    self._use_fd = False
                    self._use_cli = False
                    self._transitional = False
                    self._initialized = True
                    self._index_ready = True
                    return True

        except (OSError, Exception) as e:
            print(f"[EverythingSearch] 探测已运行 Everything 失败: {e}")

        return False

    def _try_auto_init(self):
        """自动初始化搜索模式（在确保 Everything 运行后）"""
        if self._initialized:
            return

        # 优先尝试 DLL
        resolved_dll = config.resolve_dll_path()
        if resolved_dll and os.path.isfile(resolved_dll):
            try:
                self._load_dll(resolved_dll)
                if self._initialized:
                    return
            except Exception as e:
                print(f"[EverythingSearch] 自动初始化 DLL 失败: {e}")

        # 降级到 CLI
        self._try_fallback_to_cli()

    def is_index_ready(self) -> bool:
        """
        检查搜索索引是否已就绪。
        fd 模式：无需索引，直接返回 True。
        DLL 模式通过 Everything_IsDBLoaded 判断，
        CLI 模式通过尝试搜索 '*' 并检查是否有结果来判断。
        """
        if not self._initialized:
            return False

        if self._use_fd:
            return True
        
        if self._use_cli:
            return self._check_index_ready_cli()
        else:
            return self._check_index_ready_dll()

    def _check_index_ready_dll(self) -> bool:
        """通过 SDK DLL 检查 IsDBLoaded"""
        if not self.dll:
            return False
        try:
            return bool(self.dll.Everything_IsDBLoaded())
        except Exception:
            return False

    def _check_index_ready_cli(self) -> bool:
        """通过 ES CLI 检查索引（搜索 '*' 看返回码）"""
        if not self._es_cli_path:
            return False
        try:
            result = subprocess.run(
                [self._es_cli_path, "-n", "1"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            # IPC 错误 = Everything 未运行，返回空 = 索引未就绪
            if result.returncode != 0 and "IPC" in (result.stderr or ""):
                return False
            # 返回 0 或返回结果 → 索引就绪
            return result.returncode == 0
        except Exception:
            return False

    def wait_for_index(self, timeout: float = 60, progress_callback=None) -> bool:
        """
        等待搜索索引就绪。
        fd 模式：无需索引，直接返回 True。
        :param timeout: 超时秒数（首次启动 MFT 扫描可能较慢，建议 60-120）
        :param progress_callback: 可选回调 callback(elapsed_seconds, total_indexed)
        :return: 索引是否在超时内就绪
        """
        import time
        if not self._initialized:
            return False

        if self._use_fd:
            self._index_ready = True
            return True

        # 先快速检查
        if self.is_index_ready():
            self._index_ready = True
            if progress_callback:
                total = self._get_total_indexed()
                progress_callback(0, total)
            return True

        start = time.monotonic()
        last_total = 0

        # 轮询等待
        while time.monotonic() - start < timeout:
            time.sleep(0.5)

            if self.is_index_ready():
                self._index_ready = True
                if progress_callback:
                    total = self._get_total_indexed()
                    progress_callback(time.monotonic() - start, total)
                return True

            # 上报正在构建中的进度
            if progress_callback:
                total = self._get_total_indexed()
                if total != last_total:
                    last_total = total
                    progress_callback(time.monotonic() - start, total)

        self._index_ready = False
        return False

    def _get_total_indexed(self) -> int:
        """获取当前已索引的文件+文件夹总数（可能不精确）"""
        if self._use_fd:
            return 0  # fd 不维护索引，返回 0
        if self._use_cli:
            return self._get_total_indexed_cli()
        return self._get_total_indexed_dll()

    def _get_total_indexed_dll(self) -> int:
        """通过 SDK 获取已索引数"""
        if not self.dll or not self._check_index_ready_dll():
            return 0
        try:
            # IsDBLoaded 返回 true 后，运行一次空查询来获取统计
            self.dll.Everything_Reset()
            self.dll.Everything_SetSearchW("")
            self.dll.Everything_SetMax(1)
            if self.dll.Everything_QueryW(True):
                return self.dll.Everything_GetTotResults()
        except Exception:
            pass
        return 0

    def _get_total_indexed_cli(self) -> int:
        """通过 CLI 获取已索引数"""
        try:
            result = subprocess.run(
                [self._es_cli_path, "-get-total-size"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception:
            pass
        return 0

    def shutdown(self):
        """关闭由 Faind 启动的 Everything 进程，停止后台监控"""
        self._stop_monitoring()
        if self._started_by_us and self._everything_process:
            try:
                print("[EverythingSearch] 正在关闭内嵌 Everything...")
                self._everything_process.terminate()
                self._everything_process.wait(timeout=5)
                print("[EverythingSearch] 内嵌 Everything 已关闭")
            except Exception as e:
                print(f"[EverythingSearch] 关闭 Everything 时出错: {e}")
            finally:
                self._started_by_us = False
                self._everything_process = None

    def check_everything_running(self) -> bool:
        """检查 Everything 是否正在运行（fd + 过渡模式返回 False 表示 Everything 进程未就绪）"""
        if self._use_fd and not self._transitional:
            return False  # 纯 fd 模式，Everything 未运行

        if self._transitional:
            # 过渡模式下，检查 Everything 进程是否在运行
            return self._check_everything_process_alive()

        if self._use_cli:
            # CLI 模式下尝试执行一个简单查询
            try:
                result = subprocess.run(
                    [self._es_cli_path, "-n", "1", "nomatch12345"],
                    capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace"
                )
                # es.exe 需要 Everything 运行才能工作（IPC通信）
                # 如果返回 IPC 错误，说明 Everything 未运行
                if result.returncode != 0 and "IPC" in result.stderr:
                    return False
                return True
            except Exception:
                return False
        else:
            # DLL 模式下尝试查询
            try:
                self.dll.Everything_Reset()
                self.dll.Everything_SetSearchW("")
                self.dll.Everything_SetMax(1)
                result = self.dll.Everything_QueryW(True)
                if not result:
                    error = self.dll.Everything_GetLastError()
                    return error != EVERYTHING_ERROR_IPC
                return True
            except Exception:
                return False

    def _check_everything_process_alive(self) -> bool:
        """检查 Everything 进程是否存活（过渡模式用）"""
        if self._everything_process is not None:
            return self._everything_process.poll() is None
        # 没有进程引用，尝试通过 DLL 探测
        try:
            resolved = config.resolve_dll_path()
            if resolved and os.path.isfile(resolved):
                dll = ctypes.WinDLL(resolved)
                dll.Everything_IsDBLoaded.restype = wintypes.BOOL
                dll.Everything_IsDBLoaded()
                return True
        except Exception:
            pass
        return False

    def get_status_detail(self) -> dict:
        """获取详细的搜索状态信息"""
        dll_loaded = self.dll is not None
        everything_running = False
        cli_available = bool(self._es_cli_path) and os.path.isfile(self._es_cli_path) if self._es_cli_path else False
        fd_available = bool(self._fd_path) and os.path.isfile(self._fd_path)
        index_ready = self._index_ready

        if self._use_fd:
            if self._transitional:
                everything_running = self._check_everything_process_alive()
                index_ready = True  # fd 在过渡期间始终可用
            else:
                everything_running = False
                index_ready = True
        elif dll_loaded and not self._use_cli:
            everything_running = self.check_everything_running()
            index_ready = self.is_index_ready()
        elif self._use_cli:
            everything_running = self.check_everything_running()
            index_ready = self.is_index_ready()

        # 确定后端名称
        if self._use_fd:
            if self._transitional:
                backend = "fd→everything"
            else:
                backend = "fd"
        elif self._use_cli:
            backend = "es.exe"
        elif dll_loaded:
            backend = "everything_dll"
        else:
            backend = "none"

        return {
            "backend": backend,
            "dll_loaded": dll_loaded,
            "cli_available": cli_available,
            "fd_available": fd_available,
            "cli_path": self._es_cli_path,
            "fd_path": self._fd_path,
            "use_fd": self._use_fd,
            "use_cli": self._use_cli,
            "everything_running": everything_running,
            "search_available": self._initialized,
            "index_ready": index_ready,
            "started_by_us": self._started_by_us,
            "using_embedded": self._started_by_us,
            "using_user": everything_running and not self._started_by_us,
            "everything_service_enabled": self._everything_service_enabled,
            "transitional": self._transitional,
            "everything_status": self.get_everything_status(),
        }