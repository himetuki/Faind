"""
Faind 配置管理模块
负责读取/写入 config.json，支持热加载
兼容开发模式和 PyInstaller 打包模式
"""

import json
import os
import sys
import copy
from pathlib import Path


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
    "everything": {
        "dll_path": "",
        "use_es_cli": False,
        "es_cli_path": ""
    },
    "tmsu": {
        "executable_path": "tmsu.exe",
        "db_path": ""
    },
    "ui": {
        "max_results": 100,
        "theme": "Dark"
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
    :return: 配置字典
    """
    config_path = _get_config_path()
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            # 合并默认配置和用户配置，确保新字段有默认值
            cfg = _deep_merge(DEFAULT_CONFIG, user_config)
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
    仅写入文件，不创建额外目录
    :param config_dict: 配置字典
    :return: 是否保存成功
    """
    config_path = _get_config_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
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


def resolve_tmsu_path() -> str:
    """
    解析 TMSU 可执行文件路径
    优先使用配置路径，否则在应用目录下查找
    """
    cfg = load_config()
    configured_path = cfg.get("tmsu", {}).get("executable_path", "")
    if configured_path and os.path.isfile(configured_path):
        return configured_path
    
    app_dir = get_app_dir()
    tmsu_candidates = [
        app_dir / "library" / "tmsu" / "tmsu.exe",
        app_dir / "tmsu.exe",
    ]
    for candidate in tmsu_candidates:
        if candidate.exists():
            return str(candidate)
    
    return ""