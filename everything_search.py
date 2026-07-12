"""
Faind Everything 搜索模块
封装 Everything SDK DLL，提供文件搜索功能
支持两种模式：DLL SDK（高性能）和 ES CLI（降级方案）
"""

import ctypes
from ctypes import wintypes
import os
import subprocess
import json
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
        
        # 始终探测 CLI 路径，作为运行时降级备用
        cli_path = config.resolve_es_cli_path()
        if cli_path and os.path.isfile(cli_path):
            self._es_cli_path = cli_path
        
        if dll_path:
            self._load_dll(dll_path)
        else:
            # 自动查找 DLL
            resolved_path = config.resolve_dll_path()
            if resolved_path:
                self._load_dll(resolved_path)
            else:
                # 降级到 ES CLI
                print("[EverythingSearch] 未找到 Everything64.dll，尝试使用 ES CLI")
                self._try_fallback_to_cli()

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
        """设置 DLL 函数签名"""
        dll = self.dll

        # 设置搜索
        dll.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
        dll.Everything_SetSearchW.restype = None

        # 设置最大结果数
        dll.Everything_SetMax.argtypes = [wintypes.DWORD]
        dll.Everything_SetMax.restype = None

        # 设置偏移
        dll.Everything_SetOffset.argtypes = [wintypes.DWORD]
        dll.Everything_SetOffset.restype = None

        # 设置请求标志
        dll.Everything_SetRequestFlags.argtypes = [wintypes.DWORD]
        dll.Everything_SetRequestFlags.restype = None

        # 执行查询
        dll.Everything_QueryW.argtypes = [wintypes.BOOL]
        dll.Everything_QueryW.restype = wintypes.BOOL

        # 获取结果数量
        dll.Everything_GetNumResults.argtypes = []
        dll.Everything_GetNumResults.restype = wintypes.DWORD

        # 获取最后一个错误
        dll.Everything_GetLastError.argtypes = []
        dll.Everything_GetLastError.restype = wintypes.DWORD

        # 获取结果文件名
        dll.Everything_GetResultFileNameW.argtypes = [wintypes.DWORD]
        dll.Everything_GetResultFileNameW.restype = ctypes.c_wchar_p

        # 获取结果路径
        dll.Everything_GetResultPathW.argtypes = [wintypes.DWORD]
        dll.Everything_GetResultPathW.restype = ctypes.c_wchar_p

        # 获取结果完整路径
        dll.Everything_GetResultFullPathNameW.argtypes = [
            wintypes.DWORD, ctypes.c_wchar_p, wintypes.DWORD
        ]
        dll.Everything_GetResultFullPathNameW.restype = wintypes.DWORD

        # 获取结果扩展名
        dll.Everything_GetResultExtensionW.argtypes = [wintypes.DWORD]
        dll.Everything_GetResultExtensionW.restype = ctypes.c_wchar_p

        # 获取结果大小
        dll.Everything_GetResultSize.argtypes = [wintypes.DWORD, ctypes.POINTER(LARGE_INTEGER)]
        dll.Everything_GetResultSize.restype = wintypes.BOOL

        # 获取结果修改日期
        dll.Everything_GetResultDateModified.argtypes = [wintypes.DWORD, ctypes.POINTER(FILETIME)]
        dll.Everything_GetResultDateModified.restype = wintypes.BOOL

        # 获取结果创建日期
        dll.Everything_GetResultDateCreated.argtypes = [wintypes.DWORD, ctypes.POINTER(FILETIME)]
        dll.Everything_GetResultDateCreated.restype = wintypes.BOOL

        # 判断是否为文件夹
        dll.Everything_IsFolderResult.argtypes = [wintypes.DWORD]
        dll.Everything_IsFolderResult.restype = wintypes.BOOL

        # 重置
        dll.Everything_Reset.argtypes = []
        dll.Everything_Reset.restype = None

        # 索引状态
        dll.Everything_IsDBLoaded.argtypes = []
        dll.Everything_IsDBLoaded.restype = wintypes.BOOL

    @property
    def is_available(self) -> bool:
        """搜索功能是否可用（DLL 或 CLI 任一可用）"""
        return self._initialized

    @property
    def is_cli_mode(self) -> bool:
        """是否使用 CLI 模式"""
        return self._use_cli

    @property
    def has_cli_fallback(self) -> bool:
        """是否有 CLI 降级可用"""
        return bool(self._es_cli_path) and os.path.isfile(self._es_cli_path)

    def search(self, query: str, max_results: int = None, apply_filters: bool = True) -> dict:
        """
        执行搜索
        :param query: Everything 搜索语法字符串
        :param max_results: 最大结果数，默认从配置读取
        :param apply_filters: 是否应用搜索过滤器（排除系统文件夹等）
        :return: {"success": bool, "results": [...], "error": str, "total": int}
        """
        if not self._initialized:
            return {
                "success": False,
                "results": [],
                "error": "Everything 未初始化，请确保 Everything 已安装并运行",
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
                filtered_query = self._apply_query_filters(query, filter_config)

        if self._use_cli:
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

        # 路径优先重试：结果太少且查询不含 path: 时，自动用 path: 重试
        if result.get("success") and result.get("total", 0) < 5 and "path:" not in query:
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
        """后处理过滤：对 CLI 模式结果进行路径排除（DLL 模式通过查询语法已排除）"""
        if self._use_cli:
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
        确保 Everything 服务在运行。
        优先使用用户已安装并运行的 Everything；
        如果未运行，自动启动内嵌的 Everything64.exe 便携版。
        :return: Everything 是否可用的
        """
        # 1. 检查是否已在运行（用户已安装的 Everything）
        if self.check_everything_running():
            print("[EverythingSearch] 检测到 Everything 已在运行，使用现有服务")
            self._started_by_us = False
            return True

        # 2. 未运行，启动内嵌便携版
        print("[EverythingSearch] Everything 未运行，尝试启动内嵌版本...")
        return self._start_embedded_everything()

    def _start_embedded_everything(self) -> bool:
        """启动内嵌的 Everything64.exe 便携版（后台模式）"""
        import time

        everything_dir = config._ensure_everything_extracted()
        everything_exe = everything_dir / "Everything64.exe"

        if not everything_exe.exists():
            print(f"[EverythingSearch] 内嵌 Everything 不存在: {everything_exe}")
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

            # 等待 Everything 初始化（最多 10 秒）
            for _ in range(20):
                time.sleep(0.5)
                if self.check_everything_running():
                    self._started_by_us = True
                    print(f"[EverythingSearch] 内嵌 Everything 已就绪 ({everything_exe})")

                    # 如果还没初始化搜索模式，尝试匹配模式
                    if not self._initialized:
                        self._try_auto_init()

                    return True

            print("[EverythingSearch] 内嵌 Everything 启动超时（10秒）")
            return False

        except FileNotFoundError:
            print(f"[EverythingSearch] 无法启动 Everything: 文件不存在 {everything_exe}")
            return False
        except Exception as e:
            print(f"[EverythingSearch] 启动 Everything 失败: {e}")
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
            except Exception:
                pass

        # 降级到 CLI
        self._try_fallback_to_cli()

    def is_index_ready(self) -> bool:
        """
        检查 Everything 索引是否已就绪（数据库加载完毕）。
        DLL 模式通过 Everything_IsDBLoaded 判断，
        CLI 模式通过尝试搜索 '*' 并检查是否有结果来判断。
        """
        if not self._initialized:
            return False

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
        等待 Everything 索引就绪。
        :param timeout: 超时秒数（首次启动 MFT 扫描可能较慢，建议 60-120）
        :param progress_callback: 可选回调 callback(elapsed_seconds, total_indexed)
        :return: 索引是否在超时内就绪
        """
        import time
        if not self._initialized:
            return False

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
        """关闭由 Faind 启动的 Everything 进程"""
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
        """检查 Everything 是否正在运行"""
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

    def get_status_detail(self) -> dict:
        """获取详细的搜索状态信息"""
        dll_loaded = self.dll is not None
        everything_running = False
        cli_available = bool(self._es_cli_path) and os.path.isfile(self._es_cli_path) if self._es_cli_path else False
        index_ready = self._index_ready

        if dll_loaded and not self._use_cli:
            everything_running = self.check_everything_running()
            index_ready = self.is_index_ready()
        elif self._use_cli:
            everything_running = self.check_everything_running()
            index_ready = self.is_index_ready()

        return {
            "dll_loaded": dll_loaded,
            "cli_available": cli_available,
            "cli_path": self._es_cli_path,
            "use_cli": self._use_cli,
            "everything_running": everything_running,
            "search_available": self._initialized,
            "index_ready": index_ready,
            "started_by_us": self._started_by_us,
            "using_embedded": self._started_by_us,   # 是否使用内嵌 Everything
            "using_user": everything_running and not self._started_by_us,  # 是否使用用户已安装的 Everything
        }