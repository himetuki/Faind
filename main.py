"""
Faind 主入口
启动 customtkinter 原生桌面界面
"""

import sys
import os
import logging
from pathlib import Path

# 配置日志 — 同时输出到终端和文件
logging.basicConfig(
    level=logging.INFO,
    format='[%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

import config
from ai_parser import SearchAgent
from everything_search import EverythingSearch
from tag_manager import TagManager
from content_reader import ContentReader


def ensure_local_files():
    """
    自动扫描并仅创建缺少的本地缓存/配置文件
    用户数据文件放在 exe 旁边，不创建外部目录
    """
    exe_dir = config.get_exe_dir()

    # 1. config.json — 仅在不存在时创建
    config_path = exe_dir / "config.json"
    if not config_path.exists():
        print(f"[Faind] 配置文件不存在，创建默认配置: {config_path}")
        config.save_config(config.DEFAULT_CONFIG)
    else:
        print(f"[Faind] 配置文件已存在: {config_path}")

    # 2. tags.db — 由 TagManager 自动创建（CREATE TABLE IF NOT EXISTS）

    # 3. library 子目录检查（仅提示，不创建）
    app_dir = config.get_app_dir()
    lib_dir = app_dir / "library"
    if lib_dir.exists():
        print(f"[Faind] library 目录: {lib_dir}")
    else:
        print(f"[Faind] library 目录不存在（非必需）: {lib_dir}")

    print(f"[Faind] 应用目录: {app_dir}")
    print(f"[Faind] 数据目录: {exe_dir}")


def main():
    """主入口函数"""
    # 扫描并创建缺少的本地文件
    ensure_local_files()

    # 初始化模块
    print("[Faind] 正在初始化模块...")
    search_engine = EverythingSearch()
    tag_manager = TagManager()
    content_reader = ContentReader()
    agent = SearchAgent(search_engine, tag_manager, content_reader)
    print("[Faind] 模块初始化完成")

    # 启动 GUI
    import customtkinter as ctk
    from gui import FaindApp

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    app = FaindApp()
    app.set_modules(search_engine, agent, tag_manager, content_reader)
    app.check_status()

    print("[Faind] 正在启动界面...")
    app.mainloop()


if __name__ == "__main__":
    main()