"""
Faind 配置管理模块
负责读取/写入 config.json，支持热加载
兼容开发模式和 PyInstaller 打包模式
API Key 使用 Windows DPAPI 加密存储
"""

import json
import os
import sys
import copy
import base64
import ctypes
from ctypes import wintypes
from pathlib import Path

# ---------------------------------------------------------------------------
# Windows DPAPI 加密（绑定当前 Windows 用户账号）
# ---------------------------------------------------------------------------

CRYPTPROTECT_UI_FORBIDDEN = 0x1

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]

_ENCRYPTED_PREFIX = "ENC:"

_DPAPI_AVAILABLE = False
try:
    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    _CryptProtectData = _crypt32.CryptProtectData
    _CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),  # pDataIn
        wintypes.LPCWSTR,            # szDataDescr
        ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
        ctypes.c_void_p,             # pvReserved
        ctypes.c_void_p,             # pPromptStruct
        wintypes.DWORD,              # dwFlags
        ctypes.POINTER(_DATA_BLOB),  # pDataOut
    ]
    _CryptProtectData.restype = wintypes.BOOL

    _CryptUnprotectData = _crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),  # pDataIn
        ctypes.POINTER(wintypes.LPWSTR),  # ppszDataDescr
        ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
        ctypes.c_void_p,             # pvReserved
        ctypes.c_void_p,             # pPromptStruct
        wintypes.DWORD,              # dwFlags
        ctypes.POINTER(_DATA_BLOB),  # pDataOut
    ]
    _CryptUnprotectData.restype = wintypes.BOOL

    _LocalFree = _kernel32.LocalFree
    _LocalFree.argtypes = [ctypes.c_void_p]
    _LocalFree.restype = ctypes.c_void_p

    _DPAPI_AVAILABLE = True
except (AttributeError, OSError):
    pass


def _encrypt_value(plaintext: str) -> str:
    """使用 Windows DPAPI 加密字符串，返回带前缀的密文"""
    if not _DPAPI_AVAILABLE or not plaintext:
        return plaintext

    try:
        data_in = _DATA_BLOB()
        raw = plaintext.encode("utf-8")
        data_in.cbData = len(raw)
        data_in.pbData = ctypes.cast(
            ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_char)
        )

        data_out = _DATA_BLOB()
        desc = "Faind API Key"

        ok = _CryptProtectData(
            ctypes.byref(data_in),
            desc,
            None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(data_out),
        )
        if not ok:
            print("[Config] DPAPI 加密失败，回退明文存储")
            return plaintext

        encrypted = ctypes.string_at(data_out.pbData, data_out.cbData)
        _LocalFree(data_out.pbData)
        return _ENCRYPTED_PREFIX + base64.b64encode(encrypted).decode("ascii")
    except Exception as e:
        print(f"[Config] DPAPI 加密异常: {e}，回退明文存储")
        return plaintext


def _decrypt_value(value: str) -> str:
    """解密带 DPAPI 前缀的密文，明文直接返回"""
    if not _DPAPI_AVAILABLE or not value:
        return value

    if not value.startswith(_ENCRYPTED_PREFIX):
        return value  # 明文（旧配置兼容）

    try:
        b64 = value[len(_ENCRYPTED_PREFIX):]
        encrypted = base64.b64decode(b64)

        data_in = _DATA_BLOB()
        data_in.cbData = len(encrypted)
        data_in.pbData = ctypes.cast(
            ctypes.create_string_buffer(encrypted), ctypes.POINTER(ctypes.c_char)
        )

        data_out = _DATA_BLOB()
        desc_out = wintypes.LPWSTR()

        ok = _CryptUnprotectData(
            ctypes.byref(data_in),
            ctypes.byref(desc_out),
            None, None, None,
            0,
            ctypes.byref(data_out),
        )
        if not ok:
            print("[Config] DPAPI 解密失败（可能切换了用户账号），请重新输入 API Key")
            return ""

        plaintext = ctypes.string_at(data_out.pbData, data_out.cbData).decode("utf-8")
        _LocalFree(data_out.pbData)
        if desc_out.value:
            _LocalFree(desc_out)
        return plaintext
    except Exception as e:
        print(f"[Config] DPAPI 解密异常: {e}，请重新输入 API Key")
        return ""


def get_app_dir() -> Path:
    """
    获取应用数据目录路径（用于读取打包的数据文件如 DLL）
    打包模式：sys._MEIPASS 指向 _internal/ 目录
    开发模式：使用项目目录（__file__ 所在目录）
    """
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent


def get_exe_dir() -> Path:
    """
    获取可执行文件所在目录（用于用户数据如 config.json、tags.db）
    打包模式：exe 旁边
    开发模式：项目目录
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent

# 默认配置
DEFAULT_CONFIG = {
    "ai": {
        "provider": "GLM",
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-v4-flash",
        "max_tokens": 1500,
        "temperature": 0.2,
        "enabled": True
    },
    "search_engine": "auto",  # "auto" | "fd" | "everything_dll" | "everything_es"
    "everything_service": {
        "enabled": False,     # 是否启用内部 Everything（随 Faind 启动并扫描）
    },
    "everything": {
        "dll_path": "",
        "use_es_cli": False,
        "es_cli_path": ""
    },
    "fd": {
        "path": ""
    },
    "first_launch_completed": False,  # 首次启动引导是否已完成
    "ui": {
        "max_results": 100,
        "theme": "Dark"
    },
    "search": {
        "fast_search": True   # 简单搜索模式，跳过 AI 直接用规则匹配文件名
    },
    "search_filters": {
        "enabled": True,
        "exclude_folders": [
            ".bin",
            "$RECYCLE.BIN",
            "System Volume Information",
            "Windows",
            "ProgramData",
            "Program Files",
            "Program Files (x86)",
            ".git",
            ".svn",
            ".hg",
            "node_modules",
            "__pycache__",
            ".vs",
            ".idea",
            ".cache"
        ],
        "exclude_paths": [],
        "folder_sort_order": "first"  # "first" | "last" | "none"
    },
    "content_reader": {
        "enabled": False,
        "max_chars_per_file": 5000,
        "supported_formats": [
            ".pdf", ".docx", ".doc", ".xlsx", ".xls",
            ".pptx", ".ppt", ".txt", ".md", ".rtf",
            ".epub", ".html", ".htm", ".odt", ".ods", ".odp"
        ],
        "ai_summary_enabled": False
    }
}

# 配置文件路径
def _get_config_dir() -> Path:
    """
    获取配置目录路径（用户数据目录）
    打包模式：exe 旁边（用户可编辑 config.json、tags.db）
    开发模式：项目目录
    """
    return get_exe_dir()

def _get_config_path() -> Path:
    """获取配置文件完整路径"""
    return _get_config_dir() / "config.json"

def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base 的值"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result

def load_config() -> dict:
    """
    加载配置文件，若不存在则创建默认配置
    仅在文件缺少时创建，不会创建额外目录
    配置文件中的 api_key 为 DPAPI 密文，加载后自动解密
    :return: 配置字典（api_key 为明文）
    """
    config_path = _get_config_path()
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            # 合并默认配置和用户配置，确保新字段有默认值
            cfg = _deep_merge(DEFAULT_CONFIG, user_config)
            # 解密 api_key
            if "ai" in cfg and "api_key" in cfg["ai"]:
                cfg["ai"]["api_key"] = _decrypt_value(cfg["ai"]["api_key"])
            # 修复：列表字段若为空或仅含占位值，回退到默认值
            _apply_list_defaults(cfg, DEFAULT_CONFIG, [
                ("search_filters", "exclude_folders"),
            ])
            return cfg
        except (json.JSONDecodeError, IOError) as e:
            print(f"[Config] 配置文件读取失败，使用默认配置: {e}")
            return copy.deepcopy(DEFAULT_CONFIG)
    else:
        # 首次运行，仅创建缺少的配置文件
        print(f"[Config] 配置文件不存在，创建默认配置: {config_path}")
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)


def _apply_list_defaults(cfg: dict, defaults: dict, list_paths: list):
    """
    检查指定路径下的列表配置，如果为空或仅含无意义占位值，回退到默认列表
    :param cfg: 合并后的配置
    :param defaults: 默认配置
    :param list_paths: [(section, key), ...] 需要检查的列表路径
    """
    for section, key in list_paths:
        user_list = cfg.get(section, {}).get(key, [])
        default_list = defaults.get(section, {}).get(key, [])
        if not user_list or user_list == ["."] or user_list == [""]:
            cfg.setdefault(section, {})[key] = list(default_list)

def save_config(config_dict: dict) -> bool:
    """
    保存配置到文件
    api_key 会先通过 DPAPI 加密再写入磁盘
    仅写入文件，不创建额外目录
    :param config_dict: 配置字典（api_key 为明文）
    :return: 是否保存成功
    """
    config_path = _get_config_path()
    # 深拷贝，避免修改调用方
    cfg = copy.deepcopy(config_dict)
    # 加密 api_key
    if "ai" in cfg and "api_key" in cfg["ai"]:
        raw = cfg["ai"]["api_key"]
        if raw and not raw.startswith(_ENCRYPTED_PREFIX):
            cfg["ai"]["api_key"] = _encrypt_value(raw)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"[Config] 配置文件保存失败: {e}")
        return False

def get_config_value(key_path: str, default=None):
    """
    获取配置中的某个值，支持点号分隔的路径
    :param key_path: 如 "ai.base_url"
    :param default: 默认值
    :return: 配置值
    """
    config = load_config()
    keys = key_path.split(".")
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current

def resolve_dll_path() -> str:
    """
    解析 Everything DLL 路径
    优先使用配置路径，否则在应用目录下查找
    """
    cfg = load_config()
    configured_path = cfg.get("everything", {}).get("dll_path", "")
    if configured_path and os.path.isfile(configured_path):
        return configured_path
    
    app_dir = get_app_dir()
    dll_candidates = [
        app_dir / "library" / "Everything-SDK" / "dll" / "Everything64.dll",
        app_dir / "Everything64.dll",
    ]
    for candidate in dll_candidates:
        if candidate.exists():
            return str(candidate)
    
    # 尝试常见安装路径
    common_paths = [
        r"C:\Program Files\Everything\Everything64.dll",
        r"C:\Program Files (x86)\Everything\Everything64.dll",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p
    
    return ""

def get_everything_dir() -> Path:
    """
    获取内嵌 Everything 的持久化目录（exe 旁的 library/Everything/）
    """
    return get_exe_dir() / "library" / "Everything"


def _find_everything_exe(directory: Path) -> str:
    """在指定目录下查找 Everything 可执行文件（Everything64.exe 或 Everything.exe）"""
    for name in ("Everything64.exe", "Everything.exe"):
        exe = directory / name
        if exe.is_file():
            return str(exe)
    return ""


def resolve_everything_exe_path() -> str:
    """
    解析 Everything 可执行文件路径（Everything64.exe 或 Everything.exe）
    优先持久化位置，其次应用目录（开发模式/MEIPASS）
    """
    persistent = _find_everything_exe(get_everything_dir())
    if persistent:
        return persistent

    app_dir = get_app_dir()
    found = _find_everything_exe(app_dir / "library" / "Everything")
    if found:
        return found

    # 常见安装路径（用户可能已安装）
    for base in [
        r"C:\Program Files\Everything",
        r"C:\Program Files (x86)\Everything",
    ]:
        found = _find_everything_exe(Path(base))
        if found:
            return found

    return ""


def _ensure_everything_extracted() -> Path:
    """
    首次运行时将内嵌的 Everything 便携版复制到持久化目录
    返回持久化目录路径
    """
    import shutil
    target_dir = get_everything_dir()
    target_found = _find_everything_exe(target_dir)

    if target_found:
        return target_dir

    if not getattr(sys, 'frozen', False):
        # 开发模式：直接使用 library/Everything/，无需复制
        source_dir = Path(__file__).parent / "library" / "Everything"
        if _find_everything_exe(source_dir):
            print(f"[Config] 开发模式，Everything 位于: {source_dir}")
            return source_dir
        return target_dir

    # 打包模式：从 MEIPASS 复制到持久化目录
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        source_dir = Path(meipass) / "library" / "Everything"
        if source_dir.exists() and _find_everything_exe(source_dir):
            target_dir.mkdir(parents=True, exist_ok=True)
            for item in source_dir.iterdir():
                dst = target_dir / item.name
                if not dst.exists():
                    try:
                        if item.is_dir():
                            shutil.copytree(item, dst)
                        else:
                            shutil.copy2(item, dst)
                    except OSError as e:
                        print(f"[Config] 复制 Everything 文件失败: {item.name}: {e}")
            print(f"[Config] Everything 已解压到: {target_dir}")
            return target_dir

    return target_dir


def resolve_fd_path() -> str:
    """
    解析 fd.exe 路径
    优先使用配置路径，否则在 library/fd/ 下查找
    """
    cfg = load_config()
    configured_path = cfg.get("fd", {}).get("path", "")
    if configured_path and os.path.isfile(configured_path):
        return configured_path

    app_dir = get_app_dir()
    candidates = [
        app_dir / "library" / "fd" / "fd.exe",
        app_dir / "fd.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return ""


def resolve_es_cli_path() -> str:
    """
    解析 ES CLI 路径
    优先使用配置路径，否则在应用目录下查找
    """
    cfg = load_config()
    configured_path = cfg.get("everything", {}).get("es_cli_path", "")
    if configured_path and os.path.isfile(configured_path):
        return configured_path
    
    app_dir = get_app_dir()
    # 直接路径
    cli_candidates = [
        app_dir / "library" / "es.exe",
        app_dir / "es.exe",
    ]
    for candidate in cli_candidates:
        if candidate.exists():
            return str(candidate)
    
    # 在 library 子目录中搜索 es.exe
    lib_dir = app_dir / "library"
    if lib_dir.exists():
        for subdir in lib_dir.iterdir():
            if subdir.is_dir():
                es_path = subdir / "es.exe"
                if es_path.exists():
                    return str(es_path)
    
    return ""


