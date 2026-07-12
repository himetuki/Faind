"""
Faind GUI - 基于 PySide6 + qfluentwidgets 的 FluentUI 桌面界面
替代 customtkinter 架构，使用 Fluent Design 风格
"""

import os
import sys
import json
import threading
import logging
import collections
import datetime
import time
from pathlib import Path

# ============ PySide6 ============
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize, QPoint, QEvent, QMutex, QMutexLocker
from PySide6.QtGui import QIcon, QFont, QAction, QColor, QMouseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QScrollArea, QSplitter, QMenu, QApplication, QStackedWidget,
    QFileDialog, QSizePolicy, QSpacerItem, QCheckBox as QCheckBoxNative,
    QTextEdit, QPushButton, QDialog, QLineEdit, QGridLayout,
    QGraphicsDropShadowEffect, QListWidget, QListWidgetItem,
)

# ============ qfluentwidgets ============
from qfluentwidgets import (
    FluentWindow, NavigationInterface, NavigationItemPosition,
    FluentIcon, InfoBar, InfoBarPosition,
    PrimaryPushButton, TransparentPushButton, HyperlinkButton,
    SearchLineEdit, LineEdit, TextEdit, PlainTextEdit,
    CardWidget, ElevatedCardWidget, SimpleCardWidget,
    TitleLabel, BodyLabel, CaptionLabel, StrongBodyLabel, SubtitleLabel,
    ComboBox, CheckBox, SwitchButton,
    ScrollArea, SingleDirectionScrollArea, SmoothScrollArea,
    Dialog, MessageBox,
    ProgressBar, IndeterminateProgressBar,
    ToolTip, ToolTipFilter,
    FlowLayout,
    qconfig, Theme, setTheme, setThemeColor,
    isDarkTheme, FluentStyleSheet,
    StateToolTip, TeachingTip, TeachingTipTailPosition,
    Flyout, FlyoutAnimationType, FlyoutView,
    TabBar, TabCloseButtonDisplayMode,
    SpinBox, Slider,
    InfoBarIcon,
    PixmapLabel,
    HorizontalSeparator, VerticalSeparator,
)

import config
from content_reader import ContentReader
from ai_cache import NotRelevantCache

logger = logging.getLogger(__name__)


# ============ 全局日志捕获 ============
class LogCapture(logging.Handler):
    """
    单例：捕获所有 print() 输出和 logging 日志到环形缓冲区。
    供设置界面的日志窗口读取展示。
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_lines: int = 1000):
        if hasattr(self, '_buffer'):
            return
        super().__init__()
        self._lock = threading.Lock()
        self._buffer = collections.deque(maxlen=max_lines)
        self._original_stdout = sys.stdout
        self._hooked = False

    def hook(self):
        if self._hooked:
            return
        self.setLevel(logging.DEBUG)
        self.setFormatter(logging.Formatter('[%(name)s] %(levelname)s: %(message)s'))
        logging.root.addHandler(self)
        sys.stdout = self
        self._hooked = True

    def unhook(self):
        if not self._hooked:
            return
        sys.stdout = self._original_stdout
        logging.root.removeHandler(self)
        self._hooked = False

    def write(self, message: str):
        if message and message.rstrip():
            ts = datetime.datetime.now().strftime('%H:%M:%S')
            with self._lock:
                for line in message.rstrip('\n').split('\n'):
                    if line.strip():
                        self._buffer.append(f"[{ts}] {line}")
        self._original_stdout.write(message)

    def flush(self):
        self._original_stdout.flush()

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            with self._lock:
                self._buffer.append(msg)
        except Exception:
            self.handleError(record)

    def get_messages(self) -> list:
        with self._lock:
            return list(self._buffer)

    def get_text(self, tail: int = 500) -> str:
        with self._lock:
            msgs = list(self._buffer)[-tail:]
        return '\n'.join(msgs)


# ============ 文件类型图标映射 ============
FILE_ICON_MAP = {
    'pdf': ('📄', '#e3f2fd'), 'doc': ('📝', '#e3f2fd'), 'docx': ('📝', '#e3f2fd'),
    'xls': ('📊', '#e8f5e9'), 'xlsx': ('📊', '#e8f5e9'), 'csv': ('📊', '#e8f5e9'),
    'ppt': ('📑', '#e8f5e9'), 'pptx': ('📑', '#e8f5e9'),
    'jpg': ('🖼', '#fce4ec'), 'jpeg': ('🖼', '#fce4ec'), 'png': ('🖼', '#fce4ec'),
    'gif': ('🖼', '#fce4ec'), 'bmp': ('🖼', '#fce4ec'), 'svg': ('🖼', '#fce4ec'),
    'webp': ('🖼', '#fce4ec'),
    'mp4': ('🎬', '#f3e5f5'), 'avi': ('🎬', '#f3e5f5'), 'mkv': ('🎬', '#f3e5f5'),
    'mp3': ('🎵', '#f3e5f5'), 'wav': ('🎵', '#f3e5f5'), 'flac': ('🎵', '#f3e5f5'),
    'zip': ('📦', '#fff8e1'), 'rar': ('📦', '#fff8e1'), '7z': ('📦', '#fff8e1'),
    'py': ('💻', '#e0f2f1'), 'js': ('💻', '#e0f2f1'), 'java': ('💻', '#e0f2f1'),
    'html': ('💻', '#e0f2f1'), 'css': ('💻', '#e0f2f1'),
    'txt': ('📃', '#f5f5f5'), 'md': ('📃', '#f5f5f5'),
}

FORMAT_FILTERS = [
    ('文档', 'ext:doc;docx;pdf;txt;rtf;odt;xls;xlsx;ppt;pptx;csv;md'),
    ('图片', 'ext:jpg;jpeg;png;gif;bmp;svg;webp'),
    ('视频', 'ext:mp4;avi;mkv;mov;wmv;flv;webm'),
    ('音频', 'ext:mp3;wav;flac;aac;ogg;wma;m4a'),
    ('压缩包', 'ext:zip;rar;7z;tar;gz'),
    ('代码', 'ext:py;js;ts;java;c;cpp;h;cs;go;rs;rb;php;html;css;sql'),
]


def get_file_icon(ext, is_folder=False):
    if is_folder:
        return '📁'
    return FILE_ICON_MAP.get((ext or '').lower(), ('📄', '#f5f5f5'))[0]


def get_file_color(ext, is_folder=False):
    if is_folder:
        return '#fff3e0'
    return FILE_ICON_MAP.get((ext or '').lower(), ('📄', '#f5f5f5'))[1]


# ============ 后台工作线程 ============
class SearchWorker(QThread):
    """后台搜索工作线程"""
    finished = Signal(dict)       # 完整搜索结果
    content_ready = Signal(list)   # 内容搜索结果
    index_progress = Signal(float, int)  # 索引进度

    def __init__(self, agent, query, fast_mode=True, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.query = query
        self.fast_mode = fast_mode

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            result = self.agent.process(self.query, fast_mode=self.fast_mode)
            if not self.isInterruptionRequested():
                self.finished.emit(result)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.finished.emit({
                    "success": False, "results": [], "error": str(e),
                    "total": 0, "message": f"搜索异常: {e}"
                })


class ContentSearchWorker(QThread):
    """后台内容搜索工作线程"""
    content_ready = Signal(list)
    error = Signal(str)

    def __init__(self, agent, content_reader, search_results, query,
                 content_reader_enabled, ai_summary_enabled,
                 not_relevant_cache, last_query, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.content_reader = content_reader
        self.search_results = search_results
        self.query = query
        self.content_reader_enabled = content_reader_enabled
        self.ai_summary_enabled = ai_summary_enabled
        self.not_relevant_cache = not_relevant_cache
        self.last_query = last_query

    def run(self):
        try:
            content_results = None
            if not (self.content_reader_enabled and self.content_reader
                    and self.search_results):
                if not self.isInterruptionRequested():
                    self.content_ready.emit([])
                return

            cr_cfg = config.load_config().get('content_reader', {})
            max_chars = cr_cfg.get('max_chars_per_file', 5000)
            top_n = min(len(self.search_results), 30)

            file_paths = [item.get('full_path', '') for item in self.search_results[:top_n]
                          if item.get('full_path', '')]
            file_contents = self._read_files_parallel(file_paths, max_chars)
            if self.isInterruptionRequested():
                return

            if file_contents and self.ai_summary_enabled:
                content_results = self.agent.analyze_file_contents(file_contents, self.query)
            elif file_contents:
                content_results = []
                for fp, txt in file_contents.items():
                    name = os.path.basename(fp)
                    snippet = txt[:200].replace('\n', ' ')
                    content_results.append({
                        'file_path': fp, 'file_name': name,
                        'relevance': 0.5, 'reason': '内容匹配',
                        'snippet': snippet if len(snippet) >= 50 else txt[:200]
                    })

            if self.isInterruptionRequested():
                return

            if content_results:
                if self.not_relevant_cache and self.last_query:
                    blocked = self.not_relevant_cache.get_blocked_paths(self.last_query)
                    content_results = [r for r in content_results
                                       if r.get('file_path', '').replace('\\', '/') not in blocked]

            if not self.isInterruptionRequested():
                self.content_ready.emit(content_results or [])
        except Exception as e:
            logger.error(f"内容搜索失败: {e}")
            if not self.isInterruptionRequested():
                self.content_ready.emit([])

    def _read_files_parallel(self, file_paths, max_chars):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        valid_paths = [fp for fp in file_paths if fp and os.path.isfile(fp)]
        if not valid_paths or not self.content_reader:
            return {}

        results = {}
        cr = self.content_reader
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(cr.read_content, fp, max_chars): fp for fp in valid_paths}
            for future in as_completed(futures):
                fp = futures[future]
                try:
                    text = future.result(timeout=10)
                    if text:
                        results[fp] = text
                except Exception:
                    pass
        return results


class TagWorker(QThread):
    """后台标签操作工作线程"""
    finished = Signal(dict)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result if isinstance(result, dict) else {"success": True, "message": str(result)})
        except Exception as e:
            self.finished.emit({"success": False, "message": str(e)})


class IndexWaitWorker(QThread):
    """后台等待 Everything 索引就绪"""
    progress = Signal(float, int)
    finished = Signal(bool)

    def __init__(self, search_engine, timeout=180, parent=None):
        super().__init__(parent)
        self.search_engine = search_engine
        self.timeout = timeout

    def run(self):
        def _progress(elapsed, total):
            self.progress.emit(elapsed, total)
        ok = self.search_engine.wait_for_index(timeout=self.timeout, progress_callback=_progress)
        self.finished.emit(ok)


# ============ 自定义卡片组件 ============
class FileResultCard(CardWidget):
    """搜索结果文件卡片"""
    double_clicked = Signal(str)
    right_clicked = Signal(object, str, str)  # event, path, name
    checked_changed = Signal(str, bool)       # path, checked

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.file_path = item.get('full_path', '')
        self.setFixedHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # 复选框
        self.checkbox = CheckBox()
        self.checkbox.setFixedSize(20, 20)
        fp = self.file_path
        self.checkbox.stateChanged.connect(lambda s: self.checked_changed.emit(fp, s == Qt.CheckState.Checked.value))
        layout.addWidget(self.checkbox)

        # 图标
        ext = item.get('extension', '')
        is_folder = item.get('is_folder', False)
        icon_text = get_file_icon(ext, is_folder)
        icon_label = BodyLabel(icon_text)
        icon_label.setFixedWidth(32)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # 文件信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_text = item.get('name', '')
        name_label = BodyLabel(name_text)
        name_label.setObjectName("fileNameLabel")
        info_layout.addWidget(name_label)

        path_text = item.get('path', '')
        path_label = CaptionLabel(path_text)
        info_layout.addWidget(path_label)

        layout.addLayout(info_layout, 1)

        # 标签
        tags = item.get('tags', [])
        if tags:
            tags_layout = QHBoxLayout()
            tags_layout.setSpacing(4)
            for tag in tags[:3]:
                tag_btn = TransparentPushButton(tag)
                tag_btn.setFixedHeight(22)
                tag_btn.clicked.connect(lambda checked=False, t=tag: self._on_tag_click(t))
                tags_layout.addWidget(tag_btn)
            layout.addLayout(tags_layout)

    def _on_tag_click(self, tag):
        """标签点击 — 信号由父级 SearchInterface 连接处理"""
        pass

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.file_path)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(event, self.file_path,
                                     self.findChild(BodyLabel, "fileNameLabel").text()
                                     if self.findChild(BodyLabel, "fileNameLabel") else "")
        super().mousePressEvent(event)


class ContentResultCard(CardWidget):
    """内容搜索结果卡片"""
    double_clicked = Signal(str)
    right_clicked = Signal(object, str, str)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        fp = item.get('file_path', '')
        self.file_path = fp
        self.setFixedHeight(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 相关性指示条
        relevance = item.get('relevance', 0)
        rel_color = '#27ae60' if relevance >= 0.7 else ('#f39c12' if relevance >= 0.4 else '#a0a0a0')
        rel_bar = QFrame()
        rel_bar.setFixedWidth(4)
        rel_bar.setStyleSheet(f"background-color: {rel_color}; border-radius: 2px;")
        layout.addWidget(rel_bar)

        # 图标
        _, ext = os.path.splitext(item.get('file_name', ''))
        icon_text = get_file_icon(ext.lstrip('.').lower())
        icon_label = BodyLabel(icon_text)
        icon_label.setFixedWidth(28)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # 信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_frame = QHBoxLayout()
        name_label = BodyLabel(item.get('file_name', ''))
        name_label.setObjectName("contentFileName")
        name_frame.addWidget(name_label)

        if relevance:
            rel_text = f"{relevance:.0%}"
            rel_label = CaptionLabel(rel_text)
            rel_label.setStyleSheet(f"color: {rel_color};")
            name_frame.addWidget(rel_label)
        name_frame.addStretch()
        info_layout.addLayout(name_frame)

        reason = item.get('reason', '')
        if reason:
            reason_label = CaptionLabel(f"💡 {reason}")
            reason_label.setStyleSheet("color: #4a90d9;")
            info_layout.addWidget(reason_label)

        snippet = item.get('snippet', '')
        if snippet:
            disp = snippet[:120] + ('...' if len(snippet) > 120 else '')
            snippet_label = CaptionLabel(disp)
            info_layout.addWidget(snippet_label)

        dir_p = os.path.dirname(fp)
        dir_label = CaptionLabel(dir_p)
        dir_label.setStyleSheet("color: #888;")
        info_layout.addWidget(dir_label)

        layout.addLayout(info_layout, 1)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.file_path)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(event, self.file_path,
                                     self.findChild(BodyLabel, "contentFileName").text()
                                     if self.findChild(BodyLabel, "contentFileName") else "")
        super().mousePressEvent(event)


class TagFileCard(CardWidget):
    """标签文件卡片"""
    double_clicked = Signal(str)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        ext = item.get('extension', '')
        is_folder = item.get('is_folder', False)
        icon_text = get_file_icon(ext, is_folder)
        icon_label = BodyLabel(icon_text)
        icon_label.setFixedWidth(28)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)
        info_layout.addWidget(BodyLabel(item.get('name', '')))
        info_layout.addWidget(CaptionLabel(item.get('path', '')))
        layout.addLayout(info_layout, 1)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.double_clicked)
        super().mouseDoubleClickEvent(event)


# ============ 搜索界面 ============
class SearchInterface(QWidget):
    """搜索主界面 — Fluent Design 风格"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchInterface")

        # 引用（由主窗口注入)
        self._window = None

        # 状态
        self._search_results = []
        self._selected_files = set()
        self._active_filter = None
        self._is_searching = False
        self._ai_response_height = 140
        self._last_search_result = {}
        self._last_query = ""
        self._search_worker = None
        self._content_worker = None

        self._setup_ui()

    def set_window(self, win):
        self._window = win

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ===== 搜索区域 =====
        search_section = QFrame()
        search_layout = QVBoxLayout(search_section)
        search_layout.setContentsMargins(16, 12, 16, 8)
        search_layout.setSpacing(6)

        # 搜索框行
        search_box = QHBoxLayout()
        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("输入自然语言搜索，如：上周修改的PDF合同")
        self.search_input.setFixedHeight(40)
        self.search_input.searchSignal.connect(self._perform_search)
        self.search_input.clearSignal.connect(lambda: self.search_input.setText(""))
        search_box.addWidget(self.search_input, 1)

        search_btn = PrimaryPushButton("搜索")
        search_btn.setFixedSize(80, 40)
        search_btn.clicked.connect(self._perform_search)
        search_box.addWidget(search_btn)

        self.cancel_btn = TransparentPushButton("终止")
        self.cancel_btn.setFixedSize(60, 40)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 5px;
                font-weight: bold;
                background: rgba(231, 76, 60, 0.08);
            }
            QPushButton:hover {
                background: rgba(231, 76, 60, 0.2);
            }
            QPushButton:pressed {
                background: rgba(231, 76, 60, 0.35);
            }
        """)
        self.cancel_btn.clicked.connect(self._cancel_search)
        self.cancel_btn.hide()
        search_box.addWidget(self.cancel_btn)

        search_layout.addLayout(search_box)

        # 筛选条
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(4)

        self._filter_buttons = {}
        for name, query in FORMAT_FILTERS:
            btn = TransparentPushButton(name)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked=False, q=query: self._toggle_filter(q))
            filter_bar.addWidget(btn)
            self._filter_buttons[query] = btn

        filter_bar.addStretch()

        # 功能开关
        switch_frame = QHBoxLayout()
        switch_frame.setSpacing(4)

        _fs_cfg = config.load_config().get('search', config.DEFAULT_CONFIG.get('search', {}))
        self._fast_search_enabled = _fs_cfg.get('fast_search', True)
        self._fast_search_btn = TransparentPushButton("⚡ 简单搜索")
        self._fast_search_btn.setFixedHeight(28)
        self._fast_search_btn.clicked.connect(self._toggle_fast_search)
        self._update_fast_search_style()
        switch_frame.addWidget(self._fast_search_btn)

        _cr_cfg = config.load_config().get('content_reader', config.DEFAULT_CONFIG.get('content_reader', {}))
        self._content_reader_enabled = _cr_cfg.get('enabled', False)
        self._content_reader_btn = TransparentPushButton("📄 内容搜索")
        self._content_reader_btn.setFixedHeight(28)
        self._content_reader_btn.clicked.connect(self._toggle_content_reader)
        self._update_content_reader_style()
        switch_frame.addWidget(self._content_reader_btn)

        self._ai_summary_enabled = _cr_cfg.get('ai_summary_enabled', False)
        self._ai_summary_btn = TransparentPushButton("🤖 AI总结")
        self._ai_summary_btn.setFixedHeight(28)
        self._ai_summary_btn.clicked.connect(self._toggle_ai_summary)
        self._update_ai_summary_style()
        switch_frame.addWidget(self._ai_summary_btn)

        filter_bar.addLayout(switch_frame)
        search_layout.addLayout(filter_bar)

        main_layout.addWidget(search_section)

        # ===== 标签操作栏（默认隐藏） =====
        self.tag_action_bar = QFrame()
        self.tag_action_bar.setFixedHeight(40)
        self.tag_action_bar.setVisible(False)
        tag_action_layout = QHBoxLayout(self.tag_action_bar)
        tag_action_layout.setContentsMargins(12, 4, 12, 4)

        self.selected_count_label = BodyLabel("0 个文件已选中")
        self.selected_count_label.setStyleSheet("color: #4a90d9;")
        tag_action_layout.addWidget(self.selected_count_label)

        self.tag_input = LineEdit()
        self.tag_input.setPlaceholderText("输入标签指令，如：标记为 高数资料")
        self.tag_input.setFixedHeight(32)
        self.tag_input.returnPressed.connect(self._apply_tags)
        tag_action_layout.addWidget(self.tag_input, 1)

        tag_btn = PrimaryPushButton("🏷 添加标签")
        tag_btn.setFixedWidth(90)
        tag_btn.clicked.connect(self._apply_tags)
        tag_action_layout.addWidget(tag_btn)

        main_layout.addWidget(self.tag_action_bar)

        # ===== AI 回复区（默认隐藏） =====
        self.ai_response_frame = QFrame()
        self.ai_response_frame.setVisible(False)
        self.ai_response_frame.setMinimumHeight(60)
        ai_layout = QVBoxLayout(self.ai_response_frame)
        ai_layout.setContentsMargins(12, 8, 12, 8)
        ai_layout.setSpacing(4)

        ai_header = QHBoxLayout()
        ai_title = SubtitleLabel("🤖 AI 助手")
        ai_title.setStyleSheet("color: #4a90d9;")
        ai_header.addWidget(ai_title)

        self.ai_detail_btn = TransparentPushButton("📋 查看详情")
        self.ai_detail_btn.setFixedHeight(24)
        self.ai_detail_btn.clicked.connect(self._show_ai_detail)
        ai_header.addWidget(self.ai_detail_btn)
        ai_header.addStretch()

        close_btn = TransparentPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self._hide_ai_response)
        ai_header.addWidget(close_btn)
        ai_layout.addLayout(ai_header)

        self.ai_response_text = TextEdit()
        self.ai_response_text.setReadOnly(True)
        self.ai_response_text.setFixedHeight(self._ai_response_height)
        ai_layout.addWidget(self.ai_response_text)

        main_layout.addWidget(self.ai_response_frame)

        # ===== 分隔条 =====
        self.splitter_handle = QFrame()
        self.splitter_handle.setFixedHeight(6)
        self.splitter_handle.setCursor(Qt.CursorShape.SplitVCursor)
        self.splitter_handle.setVisible(False)
        self.splitter_handle.installEventFilter(self)
        self._splitter_dragging = False
        self._splitter_start_y = 0
        self._splitter_start_height = 0
        main_layout.addWidget(self.splitter_handle)

        # ===== 结果区域 =====
        results_section = QFrame()
        results_layout = QVBoxLayout(results_section)
        results_layout.setContentsMargins(16, 4, 16, 8)
        results_layout.setSpacing(4)

        # 结果头部
        results_header = QHBoxLayout()
        self.results_count_label = CaptionLabel("0 个结果")
        results_header.addWidget(self.results_count_label)

        self.query_label = CaptionLabel("")
        results_header.addWidget(self.query_label)
        results_header.addStretch()

        # 排序按钮
        self._sort_first_btn = TransparentPushButton("📁↑")
        self._sort_first_btn.setFixedSize(36, 28)
        self._sort_first_btn.clicked.connect(lambda: self._change_sort('first'))
        results_header.addWidget(self._sort_first_btn)

        self._sort_last_btn = TransparentPushButton("📁↓")
        self._sort_last_btn.setFixedSize(36, 28)
        self._sort_last_btn.clicked.connect(lambda: self._change_sort('last'))
        results_header.addWidget(self._sort_last_btn)

        self._sort_none_btn = TransparentPushButton("🚫")
        self._sort_none_btn.setFixedSize(36, 28)
        self._sort_none_btn.clicked.connect(lambda: self._change_sort('none'))
        results_header.addWidget(self._sort_none_btn)

        self._filter_toggle_btn = TransparentPushButton("🔽")
        self._filter_toggle_btn.setFixedSize(36, 28)
        self._filter_toggle_btn.clicked.connect(self._toggle_search_filter)
        results_header.addWidget(self._filter_toggle_btn)

        self._update_sort_buttons()
        self._update_search_filter_btn()

        results_layout.addLayout(results_header)

        # 结果滚动区
        self._results_scroll = SmoothScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setSpacing(4)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._results_scroll.setWidget(self._results_container)

        # 空状态
        self._empty_label = BodyLabel("🔍\n输入关键词开始搜索")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #888; padding: 80px;")
        self._results_layout.addWidget(self._empty_label)

        results_layout.addWidget(self._results_scroll, 1)
        main_layout.addWidget(results_section, 1)

    def eventFilter(self, obj, event):
        if obj == self.splitter_handle:
            if event.type() == QEvent.Type.MouseButtonPress:
                self._splitter_dragging = True
                self._splitter_start_y = event.globalPosition().y()
                self._splitter_start_height = self._ai_response_height
                return True
            elif event.type() == QEvent.Type.MouseMove and self._splitter_dragging:
                delta = event.globalPosition().y() - self._splitter_start_y
                new_h = max(60, min(400, int(self._splitter_start_height + delta)))
                if new_h != self._ai_response_height:
                    self._ai_response_height = new_h
                    self.ai_response_text.setFixedHeight(new_h)
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._splitter_dragging = False
                return True
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                self._ai_response_height = 140
                self.ai_response_text.setFixedHeight(140)
                return True
        return super().eventFilter(obj, event)

    def _cancel_search(self):
        """终止当前搜索任务"""
        if not self._is_searching:
            return

        print("[SearchInterface] 用户终止搜索")
        self._is_searching = False
        self.search_input.setEnabled(True)
        self.cancel_btn.hide()

        # 通知搜索 worker 中断
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.requestInterruption()
            try:
                self._search_worker.finished.disconnect(self._on_search_finished)
            except (TypeError, RuntimeError):
                pass
            # 给线程一点时间自行退出，否则强制终止
            if not self._search_worker.wait(200):
                self._search_worker.terminate()
                self._search_worker.wait(500)

        # 通知内容搜索 worker 中断
        if self._content_worker and self._content_worker.isRunning():
            self._content_worker.requestInterruption()
            try:
                self._content_worker.content_ready.disconnect(self._append_content_results)
            except (TypeError, RuntimeError):
                pass
            if not self._content_worker.wait(200):
                self._content_worker.terminate()
                self._content_worker.wait(500)

        self._search_worker = None
        self._content_worker = None

        # 清空搜索中的加载提示，恢复结果区
        self._clear_results()
        self.results_count_label.setText("已终止")
        InfoBar.info(title="搜索", content="搜索已终止", parent=self, duration=2000)

    def _perform_search(self):
        if self._is_searching:
            return
        win = self._window
        if not win or not win.agent:
            return

        query = self.search_input.text().strip()
        if not query:
            InfoBar.warning(title="提示", content="请输入搜索内容", parent=self)
            return

        full_query = query
        if self._active_filter:
            full_query = query + ' ' + self._active_filter

        self._is_searching = True
        self._last_query = full_query
        self.results_count_label.setText("搜索中...")
        self._hide_ai_response()
        self._clear_results()

        # 显示加载状态
        loading = BodyLabel("⏳ 搜索中...")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setStyleSheet("padding: 40px;")
        self._results_layout.addWidget(loading)

        self.search_input.setEnabled(False)
        self.cancel_btn.show()

        # 启动搜索线程
        fast_mode = self._fast_search_enabled
        self._search_worker = SearchWorker(win.agent, full_query, fast_mode)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.start()

    def _on_search_finished(self, result):
        self._is_searching = False
        self.search_input.setEnabled(True)
        self.cancel_btn.hide()
        self._last_search_result = result

        # 批量查询标签
        if result.get('success') and result.get('results') and self._window and self._window.tag_manager:
            fps = [item.get('full_path', '') for item in result['results']
                   if item.get('full_path') and 'tags' not in item]
            if fps:
                tag_map = self._window.tag_manager.get_tags_batch(fps)
                for item in result['results']:
                    fp = item.get('full_path', '')
                    if fp in tag_map:
                        item['tags'] = tag_map[fp]

        self._render_search_results(result)

        # 非本项过滤
        raw_results = result.get('results', [])
        query = self._last_query
        if self._window and self._window._not_relevant_cache and query:
            blocked = self._window._not_relevant_cache.get_blocked_paths(query)
            self._search_results = [r for r in raw_results
                                    if r.get('full_path', '').replace('\\', '/') not in blocked]
        else:
            self._search_results = raw_results

        # 内容搜索
        if 'content_results' in result and result['content_results']:
            self._append_content_results(result['content_results'])
        elif (self._content_reader_enabled and self._window and self._window.content_reader
              and result.get('success') and result.get('results')):
            self._content_worker = ContentSearchWorker(
                self._window.agent, self._window.content_reader,
                result['results'], self._last_query,
                self._content_reader_enabled, self._ai_summary_enabled,
                self._window._not_relevant_cache, self._last_query
            )
            self._content_worker.content_ready.connect(self._append_content_results)
            self._content_worker.start()

    def _render_search_results(self, result):
        self._clear_results()

        if result.get('success'):
            results = result.get('results', [])
            query = self._last_query
            if self._window and self._window._not_relevant_cache and query:
                blocked = self._window._not_relevant_cache.get_blocked_paths(query)
                results = [r for r in results
                           if r.get('full_path', '').replace('\\', '/') not in blocked]
            self._search_results = results
            total = len(results)
            self.results_count_label.setText(f"{total} 个结果")
            self.query_label.setText(self._last_query)

            if results:
                name_label = BodyLabel(f"📁 文件名匹配 ({total} 个)")
                name_label.setStyleSheet("color: #4a90d9; font-weight: bold;")
                self._results_layout.addWidget(name_label)

                # 分批渲染
                self._render_batch(results, 0, 8, is_content=False)
            else:
                empty = BodyLabel("📂\n未找到匹配的文件")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setStyleSheet("padding: 80px; color: #888;")
                self._results_layout.addWidget(empty)

            if result.get('message'):
                self._show_ai_response(result['message'])
        else:
            self.results_count_label.setText("搜索失败")
            err = BodyLabel(f"❌ {result.get('error', '搜索失败')}")
            err.setStyleSheet("color: #e74c3c; padding: 40px;")
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_layout.addWidget(err)

    def _render_batch(self, items, start, batch_size, is_content=False):
        batch = items[start:start + batch_size]
        for item in batch:
            if is_content:
                card = ContentResultCard(item)
                card.double_clicked.connect(self._open_file)
                card.right_clicked.connect(self._show_result_menu)
            else:
                card = FileResultCard(item)
                card.double_clicked.connect(self._open_file)
                card.right_clicked.connect(self._show_result_menu)
                card.checked_changed.connect(self._on_file_checked)
                fp = item.get('full_path', '')
                if fp in self._selected_files:
                    card.checkbox.setChecked(True)
            self._results_layout.addWidget(card)

        next_start = start + batch_size
        if next_start < len(items):
            QTimer.singleShot(16, lambda: self._render_batch(items, next_start, batch_size, is_content))

    def _append_content_results(self, content_results):
        if not content_results:
            return

        # 分隔线
        sep = HorizontalSeparator()
        self._results_layout.addWidget(sep)

        ai_label = "🤖 AI智能分析" if self._ai_summary_enabled else "📄 内容匹配"
        content_label = BodyLabel(f"{ai_label} ({len(content_results)} 个)")
        content_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        self._results_layout.addWidget(content_label)

        self._render_batch(content_results, 0, 6, is_content=True)

    def _clear_results(self):
        while self._results_layout.count() > 0:
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_file_checked(self, fp, checked):
        if checked:
            self._selected_files.add(fp)
        else:
            self._selected_files.discard(fp)

        count = len(self._selected_files)
        if count > 0:
            self.selected_count_label.setText(f"{count} 个文件已选中")
            self.tag_action_bar.setVisible(True)
        else:
            self.tag_action_bar.setVisible(False)

    def _apply_tags(self):
        instruction = self.tag_input.text().strip()
        if not instruction:
            InfoBar.warning(title="提示", content="请输入标签指令", parent=self)
            return
        if not self._selected_files:
            InfoBar.warning(title="提示", content="请先选中文件", parent=self)
            return

        file_paths = list(self._selected_files)
        win = self._window
        if not win or not win.agent:
            return

        worker = TagWorker(win.agent.process, instruction, {"selected_files": file_paths})
        worker.finished.connect(lambda r: self._on_tag_result(r, instruction))
        worker.start()

    def _on_tag_result(self, result, instruction):
        if result.get('success'):
            InfoBar.success(title="成功", content=result.get('message', '操作成功'), parent=self)
            self.tag_input.clear()
        else:
            InfoBar.error(title="失败", content=result.get('message', '操作失败'), parent=self)

    def _toggle_filter(self, query):
        if self._active_filter == query:
            self._active_filter = None
            for q, btn in self._filter_buttons.items():
                btn.setStyleSheet("")
        else:
            self._active_filter = query
            for q, btn in self._filter_buttons.items():
                if q == query:
                    btn.setStyleSheet("QPushButton { color: #4a90d9; font-weight: bold; }")
                else:
                    btn.setStyleSheet("")

        if self.search_input.text().strip():
            self._perform_search()

    def _change_sort(self, order):
        if self._window:
            self._window._search_filters['folder_sort_order'] = order
            self._window._save_search_filters()
        self._update_sort_buttons()
        if self.search_input.text().strip():
            self._perform_search()

    def _update_sort_buttons(self):
        order = 'first'
        if self._window:
            order = self._window._search_filters.get('folder_sort_order', 'first')
        for btn in [self._sort_first_btn, self._sort_last_btn, self._sort_none_btn]:
            btn.setStyleSheet("")
        active = {'first': self._sort_first_btn, 'last': self._sort_last_btn,
                  'none': self._sort_none_btn}.get(order)
        if active:
            active.setStyleSheet("QPushButton { color: #4a90d9; font-weight: bold; }")

    def _toggle_search_filter(self):
        if self._window:
            self._window._search_filters['enabled'] = not self._window._search_filters.get('enabled', True)
            self._window._save_search_filters()
            enabled = self._window._search_filters['enabled']
            msg = "过滤器已启用" if enabled else "过滤器已关闭"
            InfoBar.info(title="过滤器", content=msg, parent=self)
            self._update_search_filter_btn()

    def _update_search_filter_btn(self):
        enabled = True
        if self._window:
            enabled = self._window._search_filters.get('enabled', True)
        if enabled:
            self._filter_toggle_btn.setStyleSheet("QPushButton { color: #4a90d9; font-weight: bold; }")
        else:
            self._filter_toggle_btn.setStyleSheet("")

    def _toggle_fast_search(self):
        self._fast_search_enabled = not self._fast_search_enabled
        self._update_fast_search_style()
        self._save_fast_search_config()
        msg = "简单搜索已启用" if self._fast_search_enabled else "AI 智能搜索已启用"
        InfoBar.info(title="搜索模式", content=msg, parent=self)

    def _update_fast_search_style(self):
        if self._fast_search_enabled:
            self._fast_search_btn.setStyleSheet("QPushButton { color: #4a90d9; font-weight: bold; }")
        else:
            self._fast_search_btn.setStyleSheet("")

    def _save_fast_search_config(self):
        cfg = config.load_config()
        cfg.setdefault('search', {})
        cfg['search']['fast_search'] = self._fast_search_enabled
        config.save_config(cfg)

    def _toggle_content_reader(self):
        self._content_reader_enabled = not self._content_reader_enabled
        self._update_content_reader_style()
        self._save_content_reader_config()
        win = self._window
        if win and self._content_reader_enabled and not win.content_reader:
            win.content_reader = ContentReader()
        if win and win.content_reader:
            win.content_reader.enabled = self._content_reader_enabled
        msg = "内容搜索已启用" if self._content_reader_enabled else "内容搜索已关闭"
        InfoBar.info(title="内容搜索", content=msg, parent=self)

    def _update_content_reader_style(self):
        if self._content_reader_enabled:
            self._content_reader_btn.setStyleSheet("QPushButton { color: #4a90d9; font-weight: bold; }")
        else:
            self._content_reader_btn.setStyleSheet("")

    def _toggle_ai_summary(self):
        self._ai_summary_enabled = not self._ai_summary_enabled
        self._update_ai_summary_style()
        self._save_content_reader_config()
        msg = "AI 总结已启用" if self._ai_summary_enabled else "AI 总结已关闭"
        InfoBar.info(title="AI总结", content=msg, parent=self)

    def _update_ai_summary_style(self):
        if self._ai_summary_enabled:
            self._ai_summary_btn.setStyleSheet("QPushButton { color: #4a90d9; font-weight: bold; }")
        else:
            self._ai_summary_btn.setStyleSheet("")

    def _save_content_reader_config(self):
        cfg = config.load_config()
        cfg.setdefault('content_reader', {})
        cfg['content_reader']['enabled'] = self._content_reader_enabled
        cfg['content_reader']['ai_summary_enabled'] = self._ai_summary_enabled
        config.save_config(cfg)

    def update_content_toggle_buttons(self):
        self._update_content_reader_style()
        self._update_ai_summary_style()

    def _show_ai_response(self, message):
        self.ai_response_text.setPlainText(message)
        self.ai_response_frame.setVisible(True)
        self.splitter_handle.setVisible(True)
        self.ai_response_text.setFixedHeight(self._ai_response_height)

    def _hide_ai_response(self):
        self.ai_response_frame.setVisible(False)
        self.splitter_handle.setVisible(False)

    def _show_ai_detail(self):
        dialog = Dialog("AI 回复详情", self._window if self._window else self)
        dialog.setMinimumSize(700, 550)

        layout = QVBoxLayout(dialog)

        title = SubtitleLabel("🤖 AI 交互详情")
        layout.addWidget(title)

        result = self._last_search_result

        # 概要
        summary_card = SimpleCardWidget()
        summary_layout = QVBoxLayout(summary_card)
        success = result.get('success', False)
        status = "✅ 成功" if success else "❌ 失败"
        status_color = '#27ae60' if success else '#e74c3c'
        sl = BodyLabel(f"状态: {status}")
        sl.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        summary_layout.addWidget(sl)
        summary_layout.addWidget(BodyLabel(f"结果数: {result.get('total', 0)}"))
        summary_layout.addWidget(BodyLabel(f"消息: {result.get('message', '无')}"))
        if result.get('error'):
            summary_layout.addWidget(BodyLabel(f"错误: {result['error']}"))
        if result.get('from_cache'):
            summary_layout.addWidget(BodyLabel("📦 缓存命中"))
        layout.addWidget(summary_card)

        # 工具调用记录
        actions = result.get('actions', [])
        if actions:
            layout.addWidget(SubtitleLabel("🔧 工具调用记录"))

            actions_scroll = SmoothScrollArea()
            actions_container = QWidget()
            actions_layout = QVBoxLayout(actions_container)
            actions_layout.setSpacing(4)
            actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            for i, a in enumerate(actions):
                card = SimpleCardWidget()
                card_layout = QVBoxLayout(card)
                card_layout.setSpacing(2)

                tool_name = a.get('tool', '未知')
                tl = BodyLabel(f"#{i+1} {tool_name}")
                tl.setStyleSheet("color: #4a90d9; font-weight: bold;")
                card_layout.addWidget(tl)

                if a.get('args'):
                    args_text = json.dumps(a['args'], ensure_ascii=False, indent=2)
                    card_layout.addWidget(CaptionLabel(args_text))

                summary = a.get('result_summary', '')
                if summary:
                    card_layout.addWidget(BodyLabel(f"结果: {summary}"))
                actions_layout.addWidget(card)

            actions_scroll.setWidget(actions_container)
            layout.addWidget(actions_scroll, 1)
        else:
            layout.addWidget(BodyLabel("(无工具调用记录)"))

        # 底部
        bottom = QHBoxLayout()
        try:
            from ai_response_logger import get_log_file_path
            bottom.addWidget(CaptionLabel(f"📋 完整日志: {get_log_file_path()}"))
        except Exception:
            pass
        bottom.addStretch()
        close_btn = PrimaryPushButton("关闭")
        close_btn.clicked.connect(dialog.close)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        dialog.exec()

    def _show_result_menu(self, event, file_path, file_name):
        menu = QMenu(self)
        menu.addAction("📂 打开文件", lambda: self._open_file(file_path))
        menu.addAction("📁 浏览路径", lambda: self._open_file_location(file_path))
        menu.addSeparator()
        menu.addAction("🏷 编辑标签", lambda: self._edit_tags_for_file(file_path, file_name))
        menu.addAction("✏ 重命名", lambda: self._rename_file(file_path, file_name))
        menu.addSeparator()
        menu.addAction("🗑 非本项", lambda: self._mark_not_relevant(file_path, file_name))
        menu.exec(event.globalPos() if hasattr(event, 'globalPos') else event.globalPosition().toPoint())

    def _open_file(self, fp):
        try:
            if os.path.exists(fp):
                os.startfile(fp)
            else:
                InfoBar.error(title="错误", content=f"文件不存在: {fp}", parent=self)
        except Exception as e:
            InfoBar.error(title="错误", content=f"打开失败: {e}", parent=self)

    def _open_file_location(self, fp):
        try:
            dir_p = os.path.dirname(fp)
            if os.path.isdir(dir_p):
                if os.path.exists(fp):
                    os.system(f'explorer /select,"{fp}"')
                else:
                    os.startfile(dir_p)
        except Exception as e:
            InfoBar.error(title="错误", content=f"打开路径失败: {e}", parent=self)

    def _edit_tags_for_file(self, fp, file_name=""):
        win = self._window
        current_tags = []
        if win and win.tag_manager:
            try:
                current_tags = win.tag_manager.get_tags(fp)
            except Exception:
                pass

        dialog = Dialog(f"编辑标签 - {file_name or os.path.basename(fp)}", win if win else self)
        dialog.setMinimumSize(480, 320)
        layout = QVBoxLayout(dialog)

        layout.addWidget(BodyLabel(f"文件: {file_name or os.path.basename(fp)}"))

        tags_text = ", ".join(current_tags) if current_tags else "(无标签)"
        layout.addWidget(BodyLabel(f"当前标签: {tags_text}"))

        layout.addWidget(BodyLabel("新标签（逗号分隔，以 - 开头表示删除）:"))
        entry = LineEdit()
        entry.setPlaceholderText("例如: 重要, 工作, -旧标签")
        layout.addWidget(entry)

        status_label = CaptionLabel("")
        layout.addWidget(status_label)

        def _apply():
            instruction = entry.text().strip()
            if not instruction:
                return
            if win and win.agent:
                worker = TagWorker(win.agent.process, instruction, {"selected_files": [fp]})
                worker.finished.connect(lambda r: _on_result(r))
                worker.start()

        def _on_result(res):
            if res.get('success'):
                InfoBar.success(title="成功", content="标签已更新", parent=self)
                dialog.close()
            else:
                status_label.setText(f"失败: {res.get('message', res.get('error', '未知错误'))}")
                status_label.setStyleSheet("color: #e74c3c;")

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = TransparentPushButton("取消")
        cancel_btn.clicked.connect(dialog.close)
        btn_layout.addWidget(cancel_btn)
        save_btn = PrimaryPushButton("保存")
        save_btn.clicked.connect(_apply)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        dialog.exec()

    def _rename_file(self, fp, file_name=""):
        win = self._window
        original_name = file_name or os.path.basename(fp)
        dir_p = os.path.dirname(fp)

        dialog = Dialog("重命名文件", win if win else self)
        dialog.setMinimumSize(450, 180)
        layout = QVBoxLayout(dialog)

        layout.addWidget(CaptionLabel(f"路径: {dir_p}"))
        layout.addWidget(BodyLabel("新文件名:"))
        name_entry = LineEdit()
        name_entry.setText(original_name)
        name_entry.selectAll()
        layout.addWidget(name_entry)

        status_label = CaptionLabel("")
        layout.addWidget(status_label)

        def _do_rename():
            new_name = name_entry.text().strip()
            if not new_name or new_name == original_name:
                dialog.close()
                return
            new_path = os.path.join(dir_p, new_name)
            if os.path.exists(new_path) and os.path.normpath(new_path) != os.path.normpath(fp):
                status_label.setText("目标文件已存在！")
                status_label.setStyleSheet("color: #e74c3c;")
                return
            try:
                os.rename(fp, new_path)
                dialog.close()
                InfoBar.success(title="成功", content=f"已重命名为 {new_name}", parent=self)
                if win and win.tag_manager:
                    try:
                        win.tag_manager.update_path(fp, new_path)
                    except Exception:
                        pass
                for item in self._search_results:
                    if item.get('full_path', '') == fp:
                        item['full_path'] = new_path
                        item['name'] = new_name
                        _, ext = os.path.splitext(new_name)
                        item['extension'] = ext.lstrip('.').lower()
                        break
                self._render_search_results({'success': True, 'results': self._search_results, 'total': len(self._search_results)})
            except OSError as e:
                status_label.setText(f"重命名失败: {e}")
                status_label.setStyleSheet("color: #e74c3c;")

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = TransparentPushButton("取消")
        cancel_btn.clicked.connect(dialog.close)
        btn_layout.addWidget(cancel_btn)
        ok_btn = PrimaryPushButton("重命名")
        ok_btn.clicked.connect(_do_rename)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        dialog.exec()

    def _mark_not_relevant(self, fp, file_name=""):
        win = self._window
        if not win or not win._not_relevant_cache or not self._last_query:
            InfoBar.warning(title="提示", content="无法标记，缺少搜索上下文", parent=self)
            return
        win._not_relevant_cache.mark_not_relevant(self._last_query, fp)
        name = file_name or os.path.basename(fp)
        before = len(self._search_results)
        self._search_results = [r for r in self._search_results
                                if r.get('full_path', '').replace('\\', '/') != fp.replace('\\', '/')]
        if len(self._search_results) < before:
            self._render_search_results({'success': True, 'results': self._search_results,
                                         'total': len(self._search_results)})
            self.results_count_label.setText(f"{len(self._search_results)} 个结果")
            InfoBar.info(title="已标记", content=f"已标记为非本项: {name}", parent=self)


# ============ 标签管理界面 ============
class TagsInterface(QWidget):
    """标签管理界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TagsInterface")
        self._window = None

        self._setup_ui()

    def set_window(self, win):
        self._window = win

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== 左侧标签栏 =====
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(6)

        sidebar_layout.addWidget(SubtitleLabel("🏷 标签管理"))

        self.tag_search_input = LineEdit()
        self.tag_search_input.setPlaceholderText("搜索标签...")
        self.tag_search_input.setFixedHeight(32)
        self.tag_search_input.textChanged.connect(self._filter_tags)
        sidebar_layout.addWidget(self.tag_search_input)

        sidebar_layout.addWidget(StrongBodyLabel("自定义标签"))
        self.custom_tags_scroll = SmoothScrollArea()
        self.custom_tags_container = QWidget()
        self.custom_tags_layout = QVBoxLayout(self.custom_tags_container)
        self.custom_tags_layout.setSpacing(2)
        self.custom_tags_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.custom_tags_scroll.setWidget(self.custom_tags_container)
        sidebar_layout.addWidget(self.custom_tags_scroll, 1)

        sidebar_layout.addWidget(StrongBodyLabel("格式标签"))
        fmt_frame = QWidget()
        fmt_layout = QVBoxLayout(fmt_frame)
        fmt_layout.setSpacing(1)
        for name, query in FORMAT_FILTERS:
            btn = TransparentPushButton(name)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked=False, q=query, n=name: self._select_format_tag(q, n))
            fmt_layout.addWidget(btn)
        sidebar_layout.addWidget(fmt_frame)

        create_btn = PrimaryPushButton("＋ 新建标签")
        create_btn.clicked.connect(self._show_create_tag)
        sidebar_layout.addWidget(create_btn)

        layout.addWidget(sidebar)

        # ===== 右侧内容区 =====
        content = QFrame()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(8)

        content_header = QHBoxLayout()
        self.tag_content_title = SubtitleLabel("选择一个标签查看文件")
        content_header.addWidget(self.tag_content_title)
        self.tag_file_count = CaptionLabel("")
        content_header.addWidget(self.tag_file_count)
        content_header.addStretch()
        content_layout.addLayout(content_header)

        # AI 操作栏
        ai_bar = QHBoxLayout()
        self.tag_ai_input = LineEdit()
        self.tag_ai_input.setPlaceholderText("AI标签指令：如 '给所有PDF添加文档标签'")
        self.tag_ai_input.setFixedHeight(32)
        self.tag_ai_input.returnPressed.connect(self._execute_tag_ai)
        ai_bar.addWidget(self.tag_ai_input, 1)
        exec_btn = PrimaryPushButton("🤖 执行")
        exec_btn.setFixedWidth(70)
        exec_btn.clicked.connect(self._execute_tag_ai)
        ai_bar.addWidget(exec_btn)
        content_layout.addLayout(ai_bar)

        # 文件列表
        self.tag_file_scroll = SmoothScrollArea()
        self.tag_file_container = QWidget()
        self.tag_file_layout = QVBoxLayout(self.tag_file_container)
        self.tag_file_layout.setSpacing(4)
        self.tag_file_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tag_file_scroll.setWidget(self.tag_file_container)

        self.tag_empty_label = BodyLabel("🏷\n从左侧选择标签查看关联文件")
        self.tag_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tag_empty_label.setStyleSheet("padding: 80px;")
        self.tag_file_layout.addWidget(self.tag_empty_label)

        content_layout.addWidget(self.tag_file_scroll, 1)
        layout.addWidget(content, 1)

    def refresh_tags_sidebar(self):
        win = self._window
        if not win or not win.tag_manager:
            return
        worker = TagWorker(win.tag_manager.get_all_tags)
        worker.finished.connect(self._render_custom_tags)
        worker.start()

    def _render_custom_tags(self, result):
        # 清除旧内容
        while self.custom_tags_layout.count() > 0:
            item = self.custom_tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tags = result.get('tags', []) if isinstance(result, dict) else (result or [])
        if not tags:
            self.custom_tags_layout.addWidget(CaptionLabel("暂无标签"))
            return

        for tag in tags:
            row = QHBoxLayout()
            btn = TransparentPushButton(f"🏷 {tag}")
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked=False, t=tag: self._select_tag(t))
            row.addWidget(btn, 1)

            rename_btn = TransparentPushButton("✏")
            rename_btn.setFixedSize(24, 24)
            rename_btn.clicked.connect(lambda checked=False, t=tag: self._show_rename_tag(t))
            row.addWidget(rename_btn)

            del_btn = TransparentPushButton("🗑")
            del_btn.setFixedSize(24, 24)
            del_btn.clicked.connect(lambda checked=False, t=tag: self._delete_tag(t))
            row.addWidget(del_btn)

            row_widget = QWidget()
            row_widget.setLayout(row)
            self.custom_tags_layout.addWidget(row_widget)

    def _filter_tags(self, text):
        win = self._window
        if not win or not win.tag_manager:
            return
        tags = win.tag_manager.get_all_tags() or []
        if text:
            tags = [t for t in tags if text.strip().lower() in t.lower()]
        self._render_custom_tags({'tags': tags})

    def _select_tag(self, tag):
        self.tag_content_title.setText(f"🏷 {tag}")
        win = self._window
        if not win or not win.tag_manager:
            return

        worker = TagWorker(win.tag_manager.search_by_tag, tag)
        worker.finished.connect(lambda r: self._on_tag_search_done(tag, r))
        worker.start()

    def _on_tag_search_done(self, tag, result):
        paths = result.get('results', []) if isinstance(result, dict) else (result or [])
        paths = paths if isinstance(paths, list) else []
        results = []
        win = self._window
        for p in paths:
            name = os.path.basename(p)
            dir_p = os.path.dirname(p)
            _, ext = os.path.splitext(name)
            results.append({
                'name': name, 'path': dir_p, 'full_path': p,
                'extension': ext.lstrip('.').lower(),
                'tags': win.tag_manager.get_tags(p) if win and win.tag_manager else [],
                'is_folder': os.path.isdir(p) if os.path.exists(p) else False
            })
        self._render_tag_files(results, f"{len(results)} 个文件")

    def _select_format_tag(self, ext_query, name):
        self.tag_content_title.setText(f"📄 格式: {name}")
        win = self._window
        if not win or not win.agent:
            return
        worker = SearchWorker(win.agent, ext_query, fast_mode=True)
        worker.finished.connect(lambda r: self._on_format_search_done(r))
        worker.start()

    def _on_format_search_done(self, result):
        if result.get('success'):
            items = result.get('results', [])
            self._render_tag_files(items, f"{result.get('total', 0)} 个文件")

    def _render_tag_files(self, results, count_text):
        self.tag_file_count.setText(count_text)

        while self.tag_file_layout.count() > 0:
            item = self.tag_file_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not results:
            self.tag_file_layout.addWidget(self.tag_empty_label)
            return

        for item in results:
            card = TagFileCard(item)
            card.double_clicked.connect(lambda fp=item.get('full_path', ''): self._open_file(fp))
            self.tag_file_layout.addWidget(card)

    def _open_file(self, fp):
        try:
            if os.path.exists(fp):
                os.startfile(fp)
        except Exception as e:
            InfoBar.error(title="错误", content=f"打开失败: {e}", parent=self)

    def _delete_tag(self, tag):
        win = self._window
        if not win or not win.tag_manager:
            return

        if MessageBox("删除标签", f"确定删除标签 \"{tag}\" 吗？", self).exec():
            worker = TagWorker(win.tag_manager.delete_tag, tag)
            worker.finished.connect(lambda r: self._on_tag_deleted(r, tag))
            worker.start()

    def _on_tag_deleted(self, result, tag):
        if result.get('success'):
            InfoBar.success(title="成功", content=f"标签 \"{tag}\" 已删除", parent=self)
        else:
            InfoBar.error(title="失败", content=result.get('message', '删除失败'), parent=self)
        self.refresh_tags_sidebar()

    def _show_create_tag(self):
        dialog = Dialog("新建标签", self._window if self._window else self)
        dialog.setMinimumSize(350, 150)
        layout = QVBoxLayout(dialog)
        layout.addWidget(BodyLabel("输入新标签名称："))
        entry = LineEdit()
        layout.addWidget(entry)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = TransparentPushButton("取消")
        cancel_btn.clicked.connect(dialog.close)
        btn_layout.addWidget(cancel_btn)
        ok_btn = PrimaryPushButton("创建")
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        def _create():
            name = entry.text().strip()
            if name:
                win = self._window
                if win and win.agent:
                    worker = TagWorker(win.agent.process, name, {"selected_files": ["__create_tag__"]})
                    worker.finished.connect(lambda r: self._on_tag_created(r, name, dialog))
                    worker.start()

        ok_btn.clicked.connect(_create)
        entry.returnPressed.connect(_create)
        dialog.exec()

    def _on_tag_created(self, result, name, dialog):
        if result.get('success'):
            InfoBar.success(title="成功", content=f"标签 \"{name}\" 已创建", parent=self)
            dialog.close()
            self.refresh_tags_sidebar()
        else:
            InfoBar.error(title="失败", content=result.get('message', '创建失败'), parent=self)

    def _show_rename_tag(self, old_name):
        dialog = Dialog(f"重命名标签 \"{old_name}\"", self._window if self._window else self)
        dialog.setMinimumSize(350, 150)
        layout = QVBoxLayout(dialog)
        layout.addWidget(BodyLabel(f"重命名标签 \"{old_name}\" 为："))
        entry = LineEdit()
        layout.addWidget(entry)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = TransparentPushButton("取消")
        cancel_btn.clicked.connect(dialog.close)
        btn_layout.addWidget(cancel_btn)
        ok_btn = PrimaryPushButton("重命名")
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        def _rename():
            new_name = entry.text().strip()
            if new_name and new_name != old_name:
                win = self._window
                if win and win.tag_manager:
                    worker = TagWorker(win.tag_manager.rename_tag, old_name, new_name)
                    worker.finished.connect(lambda r: self._on_tag_renamed(r, new_name, dialog))
                    worker.start()

        ok_btn.clicked.connect(_rename)
        entry.returnPressed.connect(_rename)
        dialog.exec()

    def _on_tag_renamed(self, result, new_name, dialog):
        if result.get('success'):
            InfoBar.success(title="成功", content=f"已重命名为 \"{new_name}\"", parent=self)
            dialog.close()
            self.refresh_tags_sidebar()
        else:
            InfoBar.error(title="失败", content=result.get('message', '重命名失败'), parent=self)

    def _execute_tag_ai(self):
        instruction = self.tag_ai_input.text().strip()
        if not instruction:
            InfoBar.warning(title="提示", content="请输入AI标签指令", parent=self)
            return
        self.tag_ai_input.clear()
        InfoBar.info(title="AI标签", content="正在执行...", parent=self)

        win = self._window
        if win and win.agent:
            worker = TagWorker(win.agent.process, instruction)
            worker.finished.connect(lambda r: self._on_tag_ai_done(r))
            worker.start()

    def _on_tag_ai_done(self, result):
        if result.get('success'):
            InfoBar.success(title="成功", content=result.get('message', '操作完成'), parent=self)
        else:
            InfoBar.error(title="失败", content=result.get('message', '操作失败'), parent=self)
        self.refresh_tags_sidebar()


# ============ 设置界面 ============
class SettingsInterface(QWidget):
    """设置界面 — 使用设置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsInterface")
        self._window = None

        self._setup_ui()

    def set_window(self, win):
        self._window = win

    def _make_group(self, title):
        """创建紧凑的设置分组"""
        group = QWidget()
        group.setStyleSheet("QWidget { background: transparent; }")
        glayout = QVBoxLayout(group)
        glayout.setContentsMargins(0, 0, 0, 0)
        glayout.setSpacing(4)
        label = BodyLabel(title)
        label.setStyleSheet("font-size: 15px; font-weight: bold; padding: 4px 0;")
        glayout.addWidget(label)
        cards = QWidget()
        cards.setObjectName("settingCards")
        cards_layout = QVBoxLayout(cards)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(2)
        glayout.addWidget(cards)
        return group, cards_layout

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        title = TitleLabel("⚙ 设置")
        layout.addWidget(title)

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)

        cfg = config.load_config()

        # ===== AI 设置 =====
        ai_group, ai_cards = self._make_group("🤖 AI 设置")
        ai_enabled = cfg.get('ai', {}).get('enabled', True)
        self._ai_enabled_card, self._ai_enabled_switch = self._make_switch_card(
            FluentIcon.ROBOT, "启用 AI", "", ai_enabled)
        ai_cards.addWidget(self._ai_enabled_card)

        self.base_url_edit = LineEdit()
        self.base_url_edit.setText(cfg.get('ai', {}).get('base_url', ''))
        self.base_url_edit.setPlaceholderText("https://api.deepseek.com")
        ai_cards.addWidget(self._make_edit_card("API 端点", self.base_url_edit))

        self.api_key_edit = LineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setText(cfg.get('ai', {}).get('api_key', ''))
        self.api_key_edit.setPlaceholderText("输入 API Key")
        ai_cards.addWidget(self._make_edit_card("API Key", self.api_key_edit))

        self.model_edit = LineEdit()
        self.model_edit.setText(cfg.get('ai', {}).get('model', 'gpt-4o-mini'))
        ai_cards.addWidget(self._make_edit_card("模型", self.model_edit))
        container_layout.addWidget(ai_group)

        # ===== 搜索引擎选择 =====
        search_group, search_cards = self._make_group("🔍 搜索引擎")
        self.search_engine_combo = ComboBox()
        self.search_engine_combo.addItems(["自动（优先 fd）", "fd（轻量，无需后台服务）", "Everything SDK", "Everything ES.exe"])
        engine_choice = cfg.get('search_engine', 'auto')
        idx_map = {"auto": 0, "fd": 1, "everything_dll": 2, "everything_es": 3}
        self.search_engine_combo.setCurrentIndex(idx_map.get(engine_choice, 0))
        search_cards.addWidget(self._make_edit_card("搜索后端", self.search_engine_combo))
        container_layout.addWidget(search_group)

        # ===== Everything 服务 =====
        evsvc_group, evsvc_cards = self._make_group("⚡ Everything 服务")
        evsvc_enabled = cfg.get('everything_service', {}).get('enabled', False)
        self._evsvc_enabled_card, self._evsvc_enabled_switch = self._make_switch_card(
            FluentIcon.ROBOT, "启用 Everything 内部服务",
            "Everything 随 Faind 启动；扫描期间使用 fd 过渡", evsvc_enabled)
        evsvc_cards.addWidget(self._evsvc_enabled_card)

        # 手动控制按钮 + 状态
        ev_control_card = SimpleCardWidget()
        ev_control_layout = QHBoxLayout(ev_control_card)
        ev_control_layout.setContentsMargins(16, 8, 16, 8)
        ev_control_layout.setSpacing(12)
        self.ev_status_label = BodyLabel("Everything 状态: ---")
        ev_control_layout.addWidget(self.ev_status_label)
        ev_control_layout.addStretch()
        self.ev_start_btn = PrimaryPushButton("启动 Everything")
        self.ev_start_btn.setFixedWidth(150)
        self.ev_start_btn.clicked.connect(self._toggle_everything_service)
        ev_control_layout.addWidget(self.ev_start_btn)
        evsvc_cards.addWidget(ev_control_card)
        container_layout.addWidget(evsvc_group)

        # 连接开关信号，实时更新按钮状态
        self._evsvc_enabled_switch.checkedChanged.connect(self._on_evsvc_switch_changed)

        # ===== Everything 设置 =====
        ev_group, ev_cards = self._make_group("⚙ Everything 后端设置")
        self.dll_path_edit = LineEdit()
        self.dll_path_edit.setText(cfg.get('everything', {}).get('dll_path', ''))
        self.dll_path_edit.setPlaceholderText("留空自动检测")
        ev_cards.addWidget(self._make_edit_card("DLL 路径", self.dll_path_edit))
        container_layout.addWidget(ev_group)

        # ===== 界面设置 =====
        ui_group, ui_cards = self._make_group("🖥 界面设置")
        self.max_results_edit = LineEdit()
        self.max_results_edit.setText(str(cfg.get('ui', {}).get('max_results', 100)))
        ui_cards.addWidget(self._make_edit_card("最大结果数", self.max_results_edit))
        container_layout.addWidget(ui_group)

        # ===== 搜索过滤 =====
        sf_cfg = cfg.get('search_filters', config.DEFAULT_CONFIG.get('search_filters', {}))
        filter_group, filter_cards = self._make_group("🔽 搜索过滤")
        self._filter_enabled_card, self._filter_enabled_switch = self._make_switch_card(
            FluentIcon.FILTER, "启用过滤器", "", sf_cfg.get('enabled', True))
        filter_cards.addWidget(self._filter_enabled_card)

        self.exclude_edit = TextEdit()
        _default_exclude = config.DEFAULT_CONFIG.get('search_filters', {}).get('exclude_folders', [])
        _user_exclude = sf_cfg.get('exclude_folders', [])
        self.exclude_edit.setPlainText('\n'.join(_user_exclude if _user_exclude else _default_exclude))
        self.exclude_edit.setFixedHeight(80)
        exc_card = SimpleCardWidget()
        exc_layout = QVBoxLayout(exc_card)
        exc_layout.setContentsMargins(12, 6, 12, 6)
        exc_layout.addWidget(BodyLabel("排除文件夹（每行一个）"))
        exc_layout.addWidget(self.exclude_edit)
        filter_cards.addWidget(exc_card)
        container_layout.addWidget(filter_group)

        # ===== 内容搜索设置 =====
        cr_cfg = cfg.get('content_reader', config.DEFAULT_CONFIG.get('content_reader', {}))
        cr_group, cr_cards = self._make_group("📄 内容搜索设置")

        win = self._window
        cr_enabled = win.searchInterface._content_reader_enabled if win else cr_cfg.get('enabled', False)
        self._cr_enabled_card, self._cr_enabled_switch = self._make_switch_card(
            FluentIcon.DOCUMENT, "启用文档内容搜索", "", cr_enabled)
        cr_cards.addWidget(self._cr_enabled_card)

        ai_summary = win.searchInterface._ai_summary_enabled if win else cr_cfg.get('ai_summary_enabled', False)
        self._ai_summary_card, self._ai_summary_switch = self._make_switch_card(
            FluentIcon.ROBOT, "启用 AI 内容总结", "需要 AI 已启用", ai_summary)
        cr_cards.addWidget(self._ai_summary_card)

        self.max_chars_edit = LineEdit()
        self.max_chars_edit.setText(str(cr_cfg.get('max_chars_per_file', 5000)))
        cr_cards.addWidget(self._make_edit_card("每个文件最大读取字符数", self.max_chars_edit))
        container_layout.addWidget(cr_group)

        # ===== 日志窗口 =====
        log_group, log_cards = self._make_group("📋 运行日志")
        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(120)
        self.log_text.setStyleSheet("QTextEdit { font-family: 'Consolas', monospace; font-size: 10px; }")

        log_card = SimpleCardWidget()
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(12, 6, 12, 6)
        log_layout.addWidget(BodyLabel("运行日志"))
        log_layout.addWidget(self.log_text)
        log_cards.addWidget(log_card)
        container_layout.addWidget(log_group)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # ===== 保存按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = PrimaryPushButton("💾 保存")
        save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        # 启动日志刷新
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._refresh_log)
        self._log_timer.start(1000)

        # Everything 状态刷新
        self._ev_status_timer = QTimer(self)
        self._ev_status_timer.timeout.connect(self._refresh_everything_status)
        self._ev_status_timer.start(2000)

        # 首次刷新状态
        QTimer.singleShot(500, self._refresh_everything_status)

    def _make_edit_card(self, title, edit):
        card = SimpleCardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(2)
        card_layout.addWidget(BodyLabel(title))
        card_layout.addWidget(edit)
        return card

    def _make_switch_card(self, icon, title, content, checked):
        card = SimpleCardWidget()
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(16, 8, 16, 8)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(BodyLabel(title))
        if content:
            left.addWidget(CaptionLabel(content))
        card_layout.addLayout(left, 1)
        switch = SwitchButton()
        switch.setChecked(checked)
        card_layout.addWidget(switch)
        card_layout.addStretch()
        return card, switch

    def _refresh_log(self):
        capture = LogCapture()
        new_text = capture.get_text(tail=200)
        if not new_text:
            return

        # 保存滚动位置，避免刷新后跳回顶端
        v_scroll = self.log_text.verticalScrollBar()
        was_at_bottom = v_scroll.maximum() > 0 and v_scroll.value() >= v_scroll.maximum()
        old_ratio = v_scroll.value() / max(v_scroll.maximum(), 1)

        self.log_text.setPlainText(new_text)

        if was_at_bottom or not hasattr(self, '_log_initial_scroll_done'):
            # 用户在底部 → 自动跟随末尾；首次加载也滚到底部
            v_scroll.setValue(v_scroll.maximum())
            self._log_initial_scroll_done = True
        elif old_ratio > 0:
            # 用户手动上翻查看历史 → 按比例还原滚动位置
            new_val = int(old_ratio * v_scroll.maximum())
            v_scroll.setValue(max(new_val - 1, 0))

    def _refresh_everything_status(self):
        """刷新 Everything 服务状态显示"""
        win = self._window
        if not win or not win.search_engine:
            return

        engine = win.search_engine
        status = engine.get_everything_status()

        detail = engine.get_status_detail()
        started_by_us = detail.get('started_by_us', False)

        status_map = {
            'not_enabled': ('未启用', '🔴'),
            'not_started': ('未启动', '🔴'),
            'starting': ('启动中...', '🟡'),
            'scanning': ('扫描中', '🟡'),
            'working': ('正在工作', '🟢'),
            'error': ('错误', '⛔'),
        }
        label, icon = status_map.get(status, ('未知', '❓'))

        # 标注 Everything 来源：本地（用户安装） 或 内部（内嵌便携版）
        source = ''
        if status in ('working', 'scanning', 'starting'):
            if started_by_us:
                source = ' [内部]'
            else:
                source = ' [本地]'
        self.ev_status_label.setText(f"Everything 状态: {icon} {label}{source}")

        # 更新按钮文字和状态
        if status == 'not_enabled':
            self.ev_start_btn.setText("启动 Everything")
            self.ev_start_btn.setEnabled(False)
        elif status == 'not_started':
            self.ev_start_btn.setText("启动 Everything")
            self.ev_start_btn.setEnabled(True)
        elif status in ('starting', 'scanning'):
            self.ev_start_btn.setText("停止 Everything")
            self.ev_start_btn.setEnabled(True)
        elif status == 'working':
            self.ev_start_btn.setText("重启 Everything")
            self.ev_start_btn.setEnabled(True)
        elif status == 'error':
            self.ev_start_btn.setText("重试 Everything")
            self.ev_start_btn.setEnabled(True)

    def _on_evsvc_switch_changed(self, checked):
        """Everything 服务开关切换"""
        win = self._window
        if not win or not win.search_engine:
            return
        engine = win.search_engine
        engine.everything_service_enabled = checked
        self._refresh_everything_status()

    def _toggle_everything_service(self):
        """手动启动/停止/重启 Everything 服务"""
        win = self._window
        if not win or not win.search_engine:
            return

        engine = win.search_engine
        status = engine.get_everything_status()

        if status == 'not_started':
            # 启动
            if not engine.everything_service_enabled:
                engine.everything_service_enabled = True
                self._evsvc_enabled_switch.setChecked(True)
            success = engine.start_everything_service()
            if success:
                InfoBar.success(
                    title="Everything",
                    content="Everything 服务正在启动，扫描完成前使用 fd 搜索",
                    parent=self,
                    duration=4000
                )
            else:
                InfoBar.error(title="Everything", content="启动失败，请检查 library/Everything/ 下是否有 Everything.exe 或 Everything64.exe", parent=self)
        elif status in ('starting', 'scanning'):
            # 停止
            engine._stop_monitoring()
            engine.shutdown()
            engine._everything_status = 'not_started'
            engine._transitional = False
            engine._use_fd = True
            engine._index_ready = True
            InfoBar.info(title="Everything", content="Everything 服务已停止，当前使用 fd 搜索", parent=self)
        elif status == 'working':
            # 重启
            engine.shutdown()
            engine._everything_status = 'not_started'
            engine._transitional = True
            engine._use_fd = True
            engine._index_ready = True
            if not engine.everything_service_enabled:
                engine.everything_service_enabled = True
            engine.start_everything_service()
            InfoBar.info(title="Everything", content="正在重启 Everything 服务...", parent=self)
        elif status == 'error':
            # 重试
            engine._everything_status = 'not_started'
            engine._transitional = True
            engine._use_fd = True
            engine._index_ready = True
            engine.start_everything_service()
            InfoBar.info(title="Everything", content="正在重试启动 Everything...", parent=self)
        self._refresh_everything_status()

    def _save_settings(self):
        win = self._window
        new_cfg = {
            'search_engine': {"auto": "auto", "fd": "fd", "everything_dll": "everything_dll", "everything_es": "everything_es"}.get(
                {0: "auto", 1: "fd", 2: "everything_dll", 3: "everything_es"}.get(self.search_engine_combo.currentIndex(), "auto"), "auto"
            ),
            'everything_service': {
                'enabled': self._evsvc_enabled_switch.isChecked(),
            },
            'ai': {
                'enabled': self._ai_enabled_switch.isChecked(),
                'base_url': self.base_url_edit.text().strip(),
                'api_key': self.api_key_edit.text().strip(),
                'model': self.model_edit.text().strip() or 'gpt-4o-mini',
                'max_tokens': 1500, 'temperature': 0.2
            },
            'everything': {'dll_path': self.dll_path_edit.text().strip()},
            'ui': {
                'max_results': int(self.max_results_edit.text()) if self.max_results_edit.text().isdigit() else 100,
                'theme': 'Dark' if isDarkTheme() else 'Light'
            },
            'search_filters': {
                'enabled': self._filter_enabled_switch.isChecked(),
                'exclude_folders': [l.strip() for l in self.exclude_edit.toPlainText().strip().split('\n') if l.strip()],
                'exclude_paths': [],
                'folder_sort_order': 'first'
            },
            'content_reader': {
                'enabled': self._cr_enabled_switch.isChecked(),
                'max_chars_per_file': int(self.max_chars_edit.text()) if self.max_chars_edit.text().isdigit() else 5000,
                'supported_formats': [
                    '.pdf', '.docx', '.doc', '.xlsx', '.xls',
                    '.pptx', '.ppt', '.txt', '.md', '.rtf',
                    '.epub', '.html', '.htm', '.odt', '.ods', '.odp'
                ],
                'ai_summary_enabled': self._ai_summary_switch.isChecked()
            }
        }
        config.save_config(new_cfg)

        # 更新搜索界面状态
        if win:
            cr_enabled = self._cr_enabled_switch.isChecked()
            ai_summary = self._ai_summary_switch.isChecked()
            win.searchInterface._content_reader_enabled = cr_enabled
            win.searchInterface._ai_summary_enabled = ai_summary
            win.searchInterface.update_content_toggle_buttons()

            if win.content_reader:
                win.content_reader.enabled = cr_enabled

            # 重新初始化 Agent
            from ai_parser import SearchAgent
            win.agent = SearchAgent(win.search_engine, win.tag_manager, win.content_reader)

            win._search_filters = new_cfg['search_filters']

        engine_changed = new_cfg.get('search_engine', 'auto') != config.get_config_value('search_engine', 'auto')
        evsvc_changed = new_cfg.get('everything_service', {}).get('enabled') != config.get_config_value('everything_service.enabled', False)

        # 应用 Everything 服务设置到运行时
        if win and win.search_engine:
            win.search_engine.everything_service_enabled = new_cfg.get('everything_service', {}).get('enabled', False)
            # 如果启用了服务且尚未就绪，触发启动/检测
            if new_cfg.get('everything_service', {}).get('enabled', False):
                win.search_engine.ensure_everything_running()

        messages = []
        if engine_changed:
            messages.append("搜索后端")
        if evsvc_changed:
            messages.append("Everything 服务")

        if engine_changed:
            InfoBar.warning(
                title="搜索后端已更改",
                content="重启 Faind 后生效",
                parent=self,
                duration=5000
            )
        elif messages and evsvc_changed:
            InfoBar.success(
                title="Everything 服务设置已更新",
                content="新的设置已生效",
                parent=self,
                duration=3000
            )
        else:
            InfoBar.success(title="成功", content="配置已保存", parent=self)


# ============ 主窗口 ============
class FaindWindow(FluentWindow):
    """Faind 主窗口 — FluentUI 风格"""

    def __init__(self):
        # 主题设置（在创建UI前）
        _cfg = config.load_config()
        _theme = _cfg.get('ui', {}).get('theme', 'Dark')
        setTheme(Theme.DARK if _theme == 'Dark' else Theme.LIGHT)

        # 创建子界面
        self.searchInterface = SearchInterface()
        self.tagsInterface = TagsInterface()
        self.settingsInterface = SettingsInterface()

        super().__init__()

        # 注册子界面到导航 (必须在 super().__init__() 之后，因为需要 navigationInterface 已创建)
        self.initNavigation()

        # 相互引用
        self.searchInterface.set_window(self)
        self.tagsInterface.set_window(self)
        self.settingsInterface.set_window(self)

        # 状态 (必须在 _setup_window 前初始化，因为 _update_sort_buttons 依赖 _search_filters)
        self._search_history = []
        self._selected_files = set()
        _sf = _cfg.get('search_filters', {})
        _default_sf = config.DEFAULT_CONFIG.get('search_filters', {})
        if not _sf.get('exclude_folders'):
            _sf['exclude_folders'] = _default_sf.get('exclude_folders', [])
        self._search_filters = _sf

        # 模块引用
        self.search_engine = None
        self.agent = None
        self.tag_manager = None
        self.content_reader = None
        self._not_relevant_cache = None

        self._setup_window()

    def _setup_window(self):
        self.setWindowTitle("Faind - 智能文件定位与标签系统")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        self.navigationInterface.setExpandWidth(200)
        self.navigationInterface.setMinimumExpandWidth(200)

        self.searchInterface._update_sort_buttons()
        self.searchInterface._update_search_filter_btn()

    def initNavigation(self):
        self.addSubInterface(self.searchInterface, FluentIcon.SEARCH, '搜索')
        self.addSubInterface(self.tagsInterface, FluentIcon.TAG, '标签管理')
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.settingsInterface, FluentIcon.SETTING, '设置',
                            NavigationItemPosition.BOTTOM)

    def set_modules(self, search_engine, agent, tag_manager, content_reader=None):
        self.search_engine = search_engine
        self.agent = agent
        self.tag_manager = tag_manager
        self.content_reader = content_reader
        self._not_relevant_cache = NotRelevantCache()

    def start_indexing(self):
        if not self.search_engine or not self.search_engine._initialized:
            return

        # fd 模式无需索引，直接标记就绪
        if self.search_engine._use_fd:
            self._on_index_ready(True)
            return

        self.worker = IndexWaitWorker(self.search_engine, timeout=180)
        self.worker.finished.connect(self._on_index_ready)
        self.worker.start()

    def _on_index_ready(self, ok):
        if ok:
            backend = self.search_engine.get_status_detail().get("backend", "")
            if backend == "fd":
                print("[Faind] fd 搜索后端就绪（无需索引）")
            else:
                print("[Faind] Everything 索引就绪")
        else:
            print("[Faind] 警告: 索引建立超时，搜索结果可能不完整")
        self.check_status()

    def check_status(self):
        if not self.search_engine:
            return
        detail = self.search_engine.get_status_detail()

    def _save_search_filters(self):
        cfg = config.load_config()
        cfg['search_filters'] = self._search_filters
        config.save_config(cfg)

    def closeEvent(self, event):
        logger.info("正在关闭 Faind...")
        if self.search_engine:
            self.search_engine.shutdown()
        super().closeEvent(event)


# ============ 向后兼容 ============
FaindApp = FaindWindow
