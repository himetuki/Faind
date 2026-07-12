"""
Faind 主入口
启动 PySide6 + qfluentwidgets FluentUI 桌面界面
"""

import sys
import os
import logging
from pathlib import Path

# 配置日志 — 先设级别，LogCapture 接管后统一输出到控制台 + 缓冲区
logging.root.setLevel(logging.INFO)

# 提前导入 LogCapture 并在 basicConfig 之前挂载，捕获所有后续输出
from gui import LogCapture
LogCapture().hook()

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

    # 自动确保 Everything 在后台运行（如未运行则启动内嵌便携版）
    print("[Faind] 检查 Everything 运行状态...")
    everything_auto_started = search_engine.ensure_everything_running()
    if everything_auto_started:
        status = search_engine.get_status_detail()
        if status.get("started_by_us"):
            print("[Faind] 使用内嵌 Everything（软件自带）")
        else:
            print("[Faind] 使用系统已安装的 Everything")
    else:
        print("[Faind] 警告: 无法启动 Everything，搜索功能可能不可用")
        print("[Faind] 请从 https://www.voidtools.com/ 下载 Everything Portable Zip x64")
        print("[Faind] 将 Everything64.exe 放入 library/Everything/ 目录")

    print("[Faind] 模块初始化完成")

    # 启动 GUI（PySide6 + qfluentwidgets FluentUI）
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from gui import FaindApp

    # 启用高 DPI 缩放
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    qt_app = QApplication(sys.argv)
    qt_app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)

    # FaindWindow 内部会根据配置自动设置 light/dark 主题
    window = FaindApp()
    window.set_modules(search_engine, agent, tag_manager, content_reader)
    window.check_status()

    # 后台建立索引（不阻塞界面）
    if everything_auto_started:
        window.start_indexing()

    print("[Faind] 正在启动界面...")
    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()