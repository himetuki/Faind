"""
Faind GUI - 基于 customtkinter 的原生桌面界面
替代 Eel+Chrome 架构，零浏览器依赖，微小占用
"""

import os
import sys
import threading
import customtkinter as ctk
from pathlib import Path

import config

# ============ 主题感知颜色 ============
def _tc():
    """返回当前主题适配的颜色字典"""
    dark = ctk.get_appearance_mode() == "Dark"
    return {
        'bg':          '#2b2b2b' if dark else '#ffffff',
        'bg_hover':    '#3a3a3a' if dark else '#f0f2f5',
        'border':      '#505050' if dark else '#e0e4e8',
        'border_light':'#404040' if dark else '#f0f2f5',
        'text_sec':    '#a0a0a0' if dark else '#7f8c8d',
        'text_dim':    '#707070' if dark else '#bdc3c7',
        'text_dark':   '#e0e0e0' if dark else '#2c3e50',
        'accent_bg':   '#1e3a5f' if dark else '#e8f0fe',
        'accent_hover':'#2a4a70' if dark else '#d0e4f7',
    }


# ============ 文件类型图标映射 ============
FILE_ICON_MAP = {
    'pdf': ('📄', '#e3f2fd'), 'doc': ('📝', '#e3f2fd'), 'docx': ('📝', '#e3f2fd'),
    'xls': ('📊', '#e8f5e9'), 'xlsx': ('📊', '#e8f5e9'), 'csv': ('📊', '#e8f5e9'),
    'ppt': ('📑', '#e8f5e9'), 'pptx': ('📑', '#e8f5e9'),
    'jpg': ('🖼', '#fce4ec'), 'jpeg': ('🖼', '#fce4ec'), 'png': ('🖼', '#fce4ec'),
    'gif': ('🖼', '#fce4ec'), 'bmp': ('🖼', '#fce4ec'), 'svg': ('🖼', '#fce4ec'),
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


# ============ Toast 通知 ============
class ToastManager:
    """轻量 Toast 通知"""
    def __init__(self, root):
        self.root = root
        self._after_id = None

    def show(self, message, level='info', duration=2500):
        if self._after_id:
            self.root.after_cancel(self._after_id)

        colors = {'info': '#4a90d9', 'success': '#27ae60', 'warning': '#f39c12', 'error': '#e74c3c'}
        color = colors.get(level, colors['info'])

        toast = ctk.CTkFrame(self.root, fg_color=color, corner_radius=8, height=36)
        toast.place(relx=0.5, rely=0.95, anchor='center')

        label = ctk.CTkLabel(toast, text=message, text_color='white', font=ctk.CTkFont(size=13))
        label.pack(padx=16, pady=6)

        def _remove():
            try:
                toast.place_forget()
                toast.destroy()
            except Exception:
                pass

        self._after_id = self.root.after(duration, _remove)


# ============ 主应用窗口 ============
class FaindApp(ctk.CTk):
    """Faind 主窗口"""

    def __init__(self):
        super().__init__()
        self.title("Faind - 智能文件定位与标签系统")
        self.geometry("1200x800")
        self.minsize(900, 600)

        # 设置主题（从配置加载）
        _cfg = config.load_config()
        _theme = _cfg.get('ui', {}).get('theme', 'Dark')
        ctk.set_appearance_mode(_theme)
        ctk.set_default_color_theme("blue")

        # 全局引用（由 main.py 注入）
        self.search_engine = None
        self.agent = None
        self.tag_manager = None

        # 状态
        self._search_history = []
        self._selected_files = set()
        # 从配置加载搜索过滤器（含默认排除文件夹）
        _cfg = config.load_config()
        _sf = _cfg.get('search_filters', {})
        # 如果用户配置中 exclude_folders 为空，使用默认值
        _default_sf = config.DEFAULT_CONFIG.get('search_filters', {})
        if not _sf.get('exclude_folders'):
            _sf['exclude_folders'] = _default_sf.get('exclude_folders', [])
        self._search_filters = _sf
        self._active_filter = None
        self._search_results = []
        self._is_searching = False

        # Toast
        self.toast = ToastManager(self)

        # 构建 UI
        self._build_ui()

    def set_modules(self, search_engine, agent, tag_manager):
        """注入模块实例"""
        self.search_engine = search_engine
        self.agent = agent
        self.tag_manager = tag_manager

    def _build_ui(self):
        # 顶部栏
        header = ctk.CTkFrame(self, height=48, corner_radius=0)
        header.pack(fill='x', side='top')
        header.pack_propagate(False)

        header_left = ctk.CTkFrame(header, fg_color='transparent')
        header_left.pack(side='left', padx=12)

        ctk.CTkLabel(header_left, text="🔍 Faind", font=ctk.CTkFont(size=20, weight='bold'),
                      text_color='#4a90d9').pack(side='left', pady=10)

        self._status_label = ctk.CTkLabel(header_left, text="●", font=ctk.CTkFont(size=10),
                                           text_color=_tc()['text_dim'])
        self._status_label.pack(side='left', padx=8)

        # 视图切换标签
        header_center = ctk.CTkFrame(header, fg_color='transparent')
        header_center.pack(side='left', expand=True)

        self._tab_search = ctk.CTkButton(header_center, text="🔍 搜索", width=100, height=32,
                                          fg_color='#4a90d9', hover_color='#357abd',
                                          font=ctk.CTkFont(size=13), command=lambda: self._switch_view('search'))
        self._tab_search.pack(side='left', padx=4, pady=8)

        self._tab_tags = ctk.CTkButton(header_center, text="🏷 标签管理", width=100, height=32,
                                        fg_color='transparent', hover_color=_tc()['bg_hover'],
                                        text_color=_tc()['text_sec'], border_width=1, border_color=_tc()['border'],
                                        font=ctk.CTkFont(size=13), command=lambda: self._switch_view('tags'))
        self._tab_tags.pack(side='left', padx=4, pady=8)

        # 右侧按钮
        header_right = ctk.CTkFrame(header, fg_color='transparent')
        header_right.pack(side='right', padx=12)

        ctk.CTkButton(header_right, text="🌙", width=36, height=32,
                       fg_color='transparent', hover_color=_tc()['bg_hover'],
                       font=ctk.CTkFont(size=14), command=self._toggle_theme).pack(side='left', padx=2)

        ctk.CTkButton(header_right, text="📋", width=36, height=32,
                       fg_color='transparent', hover_color=_tc()['bg_hover'],
                       font=ctk.CTkFont(size=14), command=self._show_history).pack(side='left', padx=2)

        ctk.CTkButton(header_right, text="⚙", width=36, height=32,
                       fg_color='transparent', hover_color=_tc()['bg_hover'],
                       font=ctk.CTkFont(size=14), command=self._show_settings).pack(side='left', padx=2)

        # 内容区域
        self._content = ctk.CTkFrame(self, fg_color='transparent')
        self._content.pack(fill='both', expand=True)

        # 搜索视图
        self._search_view = self._build_search_view()
        self._search_view.pack(fill='both', expand=True, in_=self._content)

        # 标签视图
        self._tags_view = self._build_tags_view()
        # 不 pack，默认隐藏

        self._current_view = 'search'

    def _toggle_theme(self):
        """切换深色/浅色主题"""
        current = ctk.get_appearance_mode()  # 返回 "Dark" 或 "Light"
        new_mode = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        # 持久化到配置
        _cfg = config.load_config()
        _cfg.setdefault('ui', {})['theme'] = new_mode
        config.save_config(_cfg)
        self.toast.show(f"已切换为{'深色' if new_mode == 'Dark' else '浅色'}主题", 'info')

    def _switch_view(self, view):
        if view == self._current_view:
            return
        self._current_view = view

        if view == 'search':
            self._search_view.pack(fill='both', expand=True, in_=self._content)
            self._tags_view.pack_forget()
            self._tab_search.configure(fg_color='#4a90d9', text_color='white', border_width=0)
            self._tab_tags.configure(fg_color='transparent', text_color=_tc()['text_sec'], border_width=1)
        else:
            self._tags_view.pack(fill='both', expand=True, in_=self._content)
            self._search_view.pack_forget()
            self._tab_tags.configure(fg_color='#4a90d9', text_color='white', border_width=0)
            self._tab_search.configure(fg_color='transparent', text_color=_tc()['text_sec'], border_width=1)
            self._refresh_tags_sidebar()

    # ============ 搜索视图构建 ============
    def _build_search_view(self):
        frame = ctk.CTkFrame(self._content, fg_color='transparent')

        # 搜索区域
        search_section = ctk.CTkFrame(frame, corner_radius=0)
        search_section.pack(fill='x', padx=0, pady=0)

        # 搜索框
        search_box = ctk.CTkFrame(search_section, fg_color='transparent')
        search_box.pack(fill='x', padx=16, pady=(12, 4))

        self._search_var = ctk.StringVar()
        self._search_entry = ctk.CTkEntry(search_box, textvariable=self._search_var,
                                           placeholder_text="输入自然语言搜索，如：上周修改的PDF合同",
                                           font=ctk.CTkFont(size=15), height=40, corner_radius=8,
                                           border_color=_tc()['border'])
        self._search_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self._search_entry.bind('<Return>', lambda e: self._perform_search())

        ctk.CTkButton(search_box, text="搜索", width=80, height=40,
                       font=ctk.CTkFont(size=14), command=self._perform_search).pack(side='right')

        # 筛选条
        filter_bar = ctk.CTkFrame(search_section, fg_color='transparent')
        filter_bar.pack(fill='x', padx=16, pady=(0, 8))

        self._filter_buttons = []
        for name, query in FORMAT_FILTERS:
            btn = ctk.CTkButton(filter_bar, text=name, width=60, height=28,
                                 fg_color='transparent', hover_color=_tc()['accent_hover'],
                                 text_color=_tc()['text_sec'], border_width=1, border_color=_tc()['border'],
                                 font=ctk.CTkFont(size=12), corner_radius=14,
                                 command=lambda q=query, b=None: self._toggle_filter(q))
            btn.pack(side='left', padx=3)
            self._filter_buttons.append((btn, query))

        # 标签操作栏（选中文件时显示）
        self._tag_action_bar = ctk.CTkFrame(frame, fg_color=_tc()['accent_bg'], height=40, corner_radius=0)
        self._tag_action_bar.pack_forget()  # 默认隐藏

        self._selected_count_label = ctk.CTkLabel(self._tag_action_bar, text="0 个文件已选中",
                                                    font=ctk.CTkFont(size=13), text_color='#4a90d9')
        self._selected_count_label.pack(side='left', padx=12)

        self._tag_input_var = ctk.StringVar()
        tag_input = ctk.CTkEntry(self._tag_action_bar, textvariable=self._tag_input_var,
                                  placeholder_text="输入标签指令，如：标记为 高数资料",
                                  font=ctk.CTkFont(size=13), height=32, width=300)
        tag_input.pack(side='left', padx=8, fill='x', expand=True)
        tag_input.bind('<Return>', lambda e: self._apply_tags())

        ctk.CTkButton(self._tag_action_bar, text="🏷 添加标签", width=90, height=32,
                       font=ctk.CTkFont(size=13), command=self._apply_tags).pack(side='right', padx=12)

        # AI 回复区（默认隐藏）
        self._ai_response_frame = ctk.CTkFrame(frame, fg_color=_tc()['accent_bg'], corner_radius=0)
        self._ai_response_frame.pack_forget()

        ai_header = ctk.CTkFrame(self._ai_response_frame, fg_color='transparent')
        ai_header.pack(fill='x', padx=12, pady=(8, 0))
        ctk.CTkLabel(ai_header, text="🤖 AI 助手", font=ctk.CTkFont(size=13, weight='bold'),
                      text_color='#4a90d9').pack(side='left')
        ctk.CTkButton(ai_header, text="✕", width=24, height=24,
                       fg_color='transparent', hover_color=_tc()['accent_hover'],
                       font=ctk.CTkFont(size=12), command=self._hide_ai_response).pack(side='right')

        self._ai_response_label = ctk.CTkLabel(self._ai_response_frame, text="",
                                                 font=ctk.CTkFont(size=13), wraplength=1100,
                                                 justify='left', text_color=_tc()['text_dark'])
        self._ai_response_label.pack(fill='x', padx=12, pady=8)

        # 结果区域
        results_section = ctk.CTkFrame(frame, fg_color='transparent')
        results_section.pack(fill='both', expand=True, padx=16, pady=8)

        # 结果头部
        results_header = ctk.CTkFrame(results_section, fg_color='transparent')
        results_header.pack(fill='x', pady=(0, 4))

        self._results_count_label = ctk.CTkLabel(results_header, text="0 个结果",
                                                   font=ctk.CTkFont(size=13), text_color=_tc()['text_sec'])
        self._results_count_label.pack(side='left')

        self._query_label = ctk.CTkLabel(results_header, text="",
                                          font=ctk.CTkFont(family='Courier', size=12), text_color=_tc()['text_sec'])
        self._query_label.pack(side='left', padx=12)

        # 排序按钮
        sort_frame = ctk.CTkFrame(results_header, fg_color='transparent')
        sort_frame.pack(side='right')

        self._sort_first_btn = ctk.CTkButton(sort_frame, text="📁↑", width=36, height=28,
                                               fg_color=_tc()['accent_bg'], hover_color=_tc()['accent_hover'],
                                               font=ctk.CTkFont(size=11),
                                               command=lambda: self._change_sort('first'))
        self._sort_first_btn.pack(side='left', padx=2)

        self._sort_last_btn = ctk.CTkButton(sort_frame, text="📁↓", width=36, height=28,
                                              fg_color='transparent', hover_color=_tc()['bg_hover'],
                                              text_color=_tc()['text_sec'], font=ctk.CTkFont(size=11),
                                              command=lambda: self._change_sort('last'))
        self._sort_last_btn.pack(side='left', padx=2)

        self._sort_none_btn = ctk.CTkButton(sort_frame, text="🚫", width=36, height=28,
                                              fg_color='transparent', hover_color=_tc()['bg_hover'],
                                              text_color=_tc()['text_sec'], font=ctk.CTkFont(size=11),
                                              command=lambda: self._change_sort('none'))
        self._sort_none_btn.pack(side='left', padx=2)

        # 过滤器开关
        self._filter_toggle_btn = ctk.CTkButton(sort_frame, text="🔽", width=36, height=28,
                                                   fg_color=_tc()['accent_bg'], hover_color=_tc()['accent_hover'],
                                                   font=ctk.CTkFont(size=11),
                                                   command=self._toggle_search_filter)
        self._filter_toggle_btn.pack(side='left', padx=(8, 2))

        # 结果列表（可滚动）
        self._results_frame = ctk.CTkScrollableFrame(results_section, fg_color='transparent')
        self._results_frame.pack(fill='both', expand=True)

        # 空状态
        self._empty_label = ctk.CTkLabel(self._results_frame, text="🔍\n输入关键词开始搜索",
                                          font=ctk.CTkFont(size=16), text_color=_tc()['text_dim'],
                                          justify='center')
        self._empty_label.pack(pady=80)

        return frame

    # ============ 标签管理视图构建 ============
    def _build_tags_view(self):
        frame = ctk.CTkFrame(self._content, fg_color='transparent')

        # 左侧标签栏
        sidebar = ctk.CTkFrame(frame, width=240, corner_radius=0)
        sidebar.pack(side='left', fill='y', padx=(0, 1))
        sidebar.pack_propagate(False)

        # 标签搜索
        search_frame = ctk.CTkFrame(sidebar, fg_color='transparent')
        search_frame.pack(fill='x', padx=8, pady=8)

        self._tag_search_var = ctk.StringVar()
        self._tag_search_var.trace_add('write', lambda *_: self._filter_tags_sidebar())
        ctk.CTkEntry(search_frame, textvariable=self._tag_search_var,
                      placeholder_text="搜索标签...", font=ctk.CTkFont(size=13),
                      height=32, corner_radius=6).pack(fill='x')

        # 自定义标签列表
        ctk.CTkLabel(sidebar, text="🏷 自定义标签", font=ctk.CTkFont(size=13, weight='bold'),
                      text_color=_tc()['text_sec']).pack(anchor='w', padx=12, pady=(8, 4))

        self._custom_tags_frame = ctk.CTkScrollableFrame(sidebar, fg_color='transparent', height=300)
        self._custom_tags_frame.pack(fill='x', padx=8)

        # 格式标签
        ctk.CTkLabel(sidebar, text="📄 格式标签", font=ctk.CTkFont(size=13, weight='bold'),
                      text_color=_tc()['text_sec']).pack(anchor='w', padx=12, pady=(12, 4))

        fmt_frame = ctk.CTkScrollableFrame(sidebar, fg_color='transparent', height=150)
        fmt_frame.pack(fill='x', padx=8)

        for name, query in FORMAT_FILTERS:
            btn = ctk.CTkButton(fmt_frame, text=name, width=200, height=28,
                                 fg_color='transparent', hover_color=_tc()['bg_hover'],
                                 text_color=_tc()['text_sec'], anchor='w',
                                 font=ctk.CTkFont(size=12),
                                 command=lambda q=query, n=name: self._select_format_tag(q, n))
            btn.pack(fill='x', pady=1)

        # 新建标签按钮
        ctk.CTkButton(sidebar, text="＋ 新建标签", height=32,
                       font=ctk.CTkFont(size=13), command=self._show_create_tag).pack(fill='x', padx=8, pady=12)

        # 右侧内容区
        content = ctk.CTkFrame(frame, corner_radius=0)
        content.pack(side='left', fill='both', expand=True)

        content_header = ctk.CTkFrame(content, fg_color='transparent')
        content_header.pack(fill='x', padx=16, pady=12)

        self._tag_content_title = ctk.CTkLabel(content_header, text="选择一个标签查看文件",
                                                 font=ctk.CTkFont(size=16, weight='bold'))
        self._tag_content_title.pack(side='left')

        self._tag_file_count = ctk.CTkLabel(content_header, text="",
                                              font=ctk.CTkFont(size=13), text_color=_tc()['text_sec'])
        self._tag_file_count.pack(side='left', padx=12)

        # 标签AI操作栏
        ai_bar = ctk.CTkFrame(content, fg_color='transparent')
        ai_bar.pack(fill='x', padx=16, pady=(0, 8))

        self._tag_ai_var = ctk.StringVar()
        ai_entry = ctk.CTkEntry(ai_bar, textvariable=self._tag_ai_var,
                                 placeholder_text="AI标签指令：如 '给所有PDF添加文档标签'",
                                 font=ctk.CTkFont(size=13), height=32)
        ai_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        ai_entry.bind('<Return>', lambda e: self._execute_tag_ai())

        ctk.CTkButton(ai_bar, text="🤖 执行", width=70, height=32,
                       font=ctk.CTkFont(size=13), command=self._execute_tag_ai).pack(side='right')

        # 标签文件列表
        self._tag_file_frame = ctk.CTkScrollableFrame(content, fg_color='transparent')
        self._tag_file_frame.pack(fill='both', expand=True, padx=16, pady=(0, 12))

        self._tag_empty_label = ctk.CTkLabel(self._tag_file_frame, text="🏷\n从左侧选择标签查看关联文件",
                                               font=ctk.CTkFont(size=16), text_color=_tc()['text_dim'],
                                               justify='center')
        self._tag_empty_label.pack(pady=80)

        return frame

    # ============ 搜索功能 ============
    def _perform_search(self):
        query = self._search_var.get().strip()
        if not query:
            self.toast.show("请输入搜索内容", "warning")
            return
        if self._is_searching:
            return
        self._is_searching = True

        full_query = query
        if self._active_filter:
            full_query = query + ' ' + self._active_filter

        self._results_count_label.configure(text="搜索中...")
        self._hide_ai_response()

        # 清空结果
        for w in self._results_frame.winfo_children():
            w.destroy()

        ctk.CTkLabel(self._results_frame, text="⏳ 搜索中...",
                      font=ctk.CTkFont(size=14), text_color=_tc()['text_sec']).pack(pady=40)

        def _do_search():
            try:
                result = self.agent.process(full_query)
                # 添加标签信息
                if result.get('success') and result.get('results'):
                    for item in result['results']:
                        fp = item.get('full_path', '')
                        if fp and 'tags' not in item:
                            item['tags'] = self.tag_manager.get_tags(fp)

                self.after(0, lambda: self._on_search_done(result, full_query))
            except Exception as e:
                self.after(0, lambda: self._on_search_error(str(e)))
            finally:
                self._is_searching = False

        threading.Thread(target=_do_search, daemon=True).start()

    def _on_search_done(self, result, query):
        for w in self._results_frame.winfo_children():
            w.destroy()

        if result.get('success'):
            self._search_results = result.get('results', [])
            total = result.get('total', 0)
            self._results_count_label.configure(text=f"{total} 个结果")
            self._query_label.configure(text=query)
            self._render_results(self._search_results)
            if result.get('message'):
                self._show_ai_response(result['message'])
        else:
            self._results_count_label.configure(text="搜索失败")
            ctk.CTkLabel(self._results_frame, text=f"❌ {result.get('error', '搜索失败')}",
                          font=ctk.CTkFont(size=14), text_color='#e74c3c').pack(pady=40)

    def _on_search_error(self, error):
        for w in self._results_frame.winfo_children():
            w.destroy()
        self._results_count_label.configure(text="搜索出错")
        ctk.CTkLabel(self._results_frame, text=f"❌ {error}",
                      font=ctk.CTkFont(size=14), text_color='#e74c3c').pack(pady=40)

    def _render_results(self, results):
        for w in self._results_frame.winfo_children():
            w.destroy()

        if not results:
            ctk.CTkLabel(self._results_frame, text="📂\n未找到匹配的文件",
                          font=ctk.CTkFont(size=16), text_color=_tc()['text_dim'],
                          justify='center').pack(pady=80)
            return

        for item in results:
            self._create_result_item(item)

    def _create_result_item(self, item):
        row = ctk.CTkFrame(self._results_frame, corner_radius=8,
                            border_width=1, border_color=_tc()['border_light'], height=56)
        row.pack(fill='x', pady=2, padx=2)

        # 复选框
        fp = item.get('full_path', '')
        is_selected = fp in self._selected_files

        chk_var = ctk.BooleanVar(value=is_selected)
        chk = ctk.CTkCheckBox(row, variable=chk_var, width=20, height=20, text="",
                               checkbox_width=18, checkbox_height=18,
                               command=lambda: self._toggle_file_selection(fp, chk_var.get()))
        chk.pack(side='left', padx=(8, 4), pady=8)

        # 图标
        ext = item.get('extension', '')
        is_folder = item.get('is_folder', False)
        icon = get_file_icon(ext, is_folder)
        ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=20), width=32).pack(side='left', padx=4)

        # 文件信息
        info_frame = ctk.CTkFrame(row, fg_color='transparent')
        info_frame.pack(side='left', fill='x', expand=True, padx=4, pady=6)

        name_text = item.get('name', '')
        ctk.CTkLabel(info_frame, text=name_text, font=ctk.CTkFont(size=14, weight='bold'),
                      anchor='w').pack(fill='x')

        path_text = item.get('path', '')
        ctk.CTkLabel(info_frame, text=path_text, font=ctk.CTkFont(size=11),
                      text_color=_tc()['text_sec'], anchor='w').pack(fill='x')

        # 标签
        tags = item.get('tags', [])
        if tags:
            tags_frame = ctk.CTkFrame(row, fg_color='transparent')
            tags_frame.pack(side='right', padx=8)
            for tag in tags[:3]:
                ctk.CTkButton(tags_frame, text=tag, width=len(tag)*8+16, height=22,
                               fg_color=_tc()['accent_bg'], hover_color=_tc()['accent_hover'],
                               text_color='#4a90d9', font=ctk.CTkFont(size=11),
                               corner_radius=10,
                               command=lambda t=tag: self._search_by_tag(t)).pack(side='left', padx=2)

        # 双击打开
        row.bind('<Double-Button-1>', lambda e: self._open_file(fp))
        for child in row.winfo_children():
            child.bind('<Double-Button-1>', lambda e: self._open_file(fp))

    def _toggle_file_selection(self, fp, selected):
        if selected:
            self._selected_files.add(fp)
        else:
            self._selected_files.discard(fp)

        count = len(self._selected_files)
        if count > 0:
            self._selected_count_label.configure(text=f"{count} 个文件已选中")
            self._tag_action_bar.pack(fill='x', before=self._ai_response_frame if self._ai_response_frame.winfo_manager() else self._results_frame.winfo_parent())
        else:
            self._tag_action_bar.pack_forget()

    def _apply_tags(self):
        instruction = self._tag_input_var.get().strip()
        if not instruction:
            self.toast.show("请输入标签指令", "warning")
            return
        if not self._selected_files:
            self.toast.show("请先选中文件", "warning")
            return

        file_paths = list(self._selected_files)

        def _do():
            try:
                result = self.agent.process(instruction, {"selected_files": file_paths})
                self.after(0, lambda: self.toast.show(result.get('message', '操作成功'), 'success' if result.get('success') else 'error'))
                self.after(0, lambda: self._tag_input_var.set(''))
            except Exception as e:
                self.after(0, lambda: self.toast.show(f"操作出错: {e}", 'error'))

        threading.Thread(target=_do, daemon=True).start()

    def _toggle_filter(self, query):
        if self._active_filter == query:
            self._active_filter = None
            for btn, q in self._filter_buttons:
                btn.configure(fg_color='transparent', text_color=_tc()['text_sec'], border_width=1)
        else:
            self._active_filter = query
            for btn, q in self._filter_buttons:
                if q == query:
                    btn.configure(fg_color=_tc()['accent_bg'], text_color='#4a90d9', border_width=0)
                else:
                    btn.configure(fg_color='transparent', text_color=_tc()['text_sec'], border_width=1)

        if self._search_var.get().strip():
            self._perform_search()

    def _change_sort(self, order):
        self._search_filters['folder_sort_order'] = order
        btn_map = {'first': self._sort_first_btn, 'last': self._sort_last_btn, 'none': self._sort_none_btn}
        for o, b in btn_map.items():
            if o == order:
                b.configure(fg_color=_tc()['accent_bg'], text_color='#4a90d9')
            else:
                b.configure(fg_color='transparent', text_color=_tc()['text_sec'])
        self._save_search_filters()
        if self._search_var.get().strip():
            self._perform_search()

    def _toggle_search_filter(self):
        self._search_filters['enabled'] = not self._search_filters['enabled']
        if self._search_filters['enabled']:
            self._filter_toggle_btn.configure(fg_color=_tc()['accent_bg'], text_color='#4a90d9')
        else:
            self._filter_toggle_btn.configure(fg_color='transparent', text_color=_tc()['text_sec'])
        self._save_search_filters()
        self.toast.show("过滤器已" + ("启用" if self._search_filters['enabled'] else "关闭"), 'info')

    def _save_search_filters(self):
        cfg = config.load_config()
        cfg['search_filters'] = self._search_filters
        config.save_config(cfg)

    def _open_file(self, fp):
        try:
            if os.path.exists(fp):
                os.startfile(fp)
            else:
                self.toast.show(f"文件不存在: {fp}", 'error')
        except Exception as e:
            self.toast.show(f"打开失败: {e}", 'error')

    def _search_by_tag(self, tag):
        self._search_var.set(f"标签:{tag}")
        self._switch_view('search')

        def _do():
            try:
                paths = self.tag_manager.search_by_tag(tag)
                results = []
                for p in paths:
                    name = os.path.basename(p)
                    dir_p = os.path.dirname(p)
                    _, ext = os.path.splitext(name)
                    results.append({'name': name, 'path': dir_p, 'full_path': p,
                                    'extension': ext.lstrip('.').lower(),
                                    'tags': self.tag_manager.get_tags(p),
                                    'is_folder': os.path.isdir(p) if os.path.exists(p) else False})
                self.after(0, lambda: self._on_search_done({'success': True, 'results': results, 'total': len(results)}, f"标签: {tag}"))
            except Exception as e:
                self.after(0, lambda: self._on_search_error(str(e)))

        threading.Thread(target=_do, daemon=True).start()

    def _show_ai_response(self, message):
        self._ai_response_label.configure(text=message)
        self._ai_response_frame.pack(fill='x', before=self._results_frame.winfo_parent())

    def _hide_ai_response(self):
        self._ai_response_frame.pack_forget()

    # ============ 标签管理功能 ============
    def _refresh_tags_sidebar(self):
        if not self.tag_manager:
            return

        def _do():
            try:
                tags = self.tag_manager.get_all_tags()
                self.after(0, lambda: self._render_custom_tags(tags or []))
            except Exception as e:
                print(f"[Faind] 刷新标签失败: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def _render_custom_tags(self, tags):
        for w in self._custom_tags_frame.winfo_children():
            w.destroy()

        if not tags:
            ctk.CTkLabel(self._custom_tags_frame, text="暂无标签",
                          font=ctk.CTkFont(size=12), text_color=_tc()['text_dim']).pack(pady=8)
            return

        for tag in tags:
            row = ctk.CTkFrame(self._custom_tags_frame, fg_color='transparent', height=32)
            row.pack(fill='x', pady=1)

            ctk.CTkButton(row, text=f"🏷 {tag}", fg_color='transparent', hover_color=_tc()['bg_hover'],
                           text_color=_tc()['text_dark'], anchor='w', font=ctk.CTkFont(size=12),
                           height=28, command=lambda t=tag: self._select_tag(t)).pack(side='left', fill='x', expand=True)

            # 重命名和删除按钮
            ctk.CTkButton(row, text="✏", width=24, height=24, fg_color='transparent',
                           hover_color=_tc()['bg_hover'], font=ctk.CTkFont(size=10),
                           command=lambda t=tag: self._show_rename_tag(t)).pack(side='right', padx=1)

            ctk.CTkButton(row, text="🗑", width=24, height=24, fg_color='transparent',
                           hover_color='#fde8e8', text_color='#e74c3c', font=ctk.CTkFont(size=10),
                           command=lambda t=tag: self._delete_tag(t)).pack(side='right', padx=1)

    def _filter_tags_sidebar(self):
        query = self._tag_search_var.get().strip().lower()
        if not self.tag_manager:
            return
        tags = self.tag_manager.get_all_tags() or []
        filtered = [t for t in tags if query in t.lower()]
        self._render_custom_tags(filtered)

    def _select_tag(self, tag):
        self._tag_content_title.configure(text=f"🏷 {tag}")

        def _do():
            try:
                paths = self.tag_manager.search_by_tag(tag)
                results = []
                for p in paths:
                    name = os.path.basename(p)
                    dir_p = os.path.dirname(p)
                    _, ext = os.path.splitext(name)
                    results.append({'name': name, 'path': dir_p, 'full_path': p,
                                    'extension': ext.lstrip('.').lower(),
                                    'tags': self.tag_manager.get_tags(p),
                                    'is_folder': os.path.isdir(p) if os.path.exists(p) else False})
                self.after(0, lambda: self._render_tag_files(results, f"{len(results)} 个文件"))
            except Exception as e:
                self.after(0, lambda: self.toast.show(f"加载失败: {e}", 'error'))

        threading.Thread(target=_do, daemon=True).start()

    def _select_format_tag(self, ext_query, name):
        self._tag_content_title.configure(text=f"📄 格式: {name}")

        def _do():
            try:
                result = self.agent.process(ext_query)
                if result.get('success'):
                    items = result.get('results', [])
                    self.after(0, lambda: self._render_tag_files(items, f"{result.get('total', 0)} 个文件"))
            except Exception as e:
                self.after(0, lambda: self.toast.show(f"搜索失败: {e}", 'error'))

        threading.Thread(target=_do, daemon=True).start()

    def _render_tag_files(self, results, count_text):
        self._tag_file_count.configure(text=count_text)
        for w in self._tag_file_frame.winfo_children():
            w.destroy()

        if not results:
            ctk.CTkLabel(self._tag_file_frame, text="📂\n该标签下暂无文件",
                          font=ctk.CTkFont(size=16), text_color=_tc()['text_dim'],
                          justify='center').pack(pady=80)
            return

        for item in results:
            row = ctk.CTkFrame(self._tag_file_frame, corner_radius=8,
                                border_width=1, border_color=_tc()['border_light'], height=48)
            row.pack(fill='x', pady=2, padx=2)

            ext = item.get('extension', '')
            is_folder = item.get('is_folder', False)
            icon = get_file_icon(ext, is_folder)
            ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=18), width=28).pack(side='left', padx=(8, 4))

            info = ctk.CTkFrame(row, fg_color='transparent')
            info.pack(side='left', fill='x', expand=True, padx=4, pady=4)
            ctk.CTkLabel(info, text=item.get('name', ''), font=ctk.CTkFont(size=13, weight='bold'),
                          anchor='w').pack(fill='x')
            ctk.CTkLabel(info, text=item.get('path', ''), font=ctk.CTkFont(size=11),
                          text_color=_tc()['text_sec'], anchor='w').pack(fill='x')

            fp = item.get('full_path', '')
            row.bind('<Double-Button-1>', lambda e, p=fp: self._open_file(p))

    def _delete_tag(self, tag):
        if not self.tag_manager:
            return
        # 简单确认
        dialog = ctk.CTkInputDialog(text=f"确定删除标签 \"{tag}\" 吗？\n输入 YES 确认：",
                                     title="删除标签")
        if dialog.get_input() != "YES":
            return

        def _do():
            try:
                result = self.tag_manager.delete_tag(tag)
                self.after(0, lambda: self.toast.show(result.get('message', '已删除'), 'success' if result.get('success') else 'error'))
                self.after(0, self._refresh_tags_sidebar)
            except Exception as e:
                self.after(0, lambda: self.toast.show(f"删除出错: {e}", 'error'))

        threading.Thread(target=_do, daemon=True).start()

    def _execute_tag_ai(self):
        instruction = self._tag_ai_var.get().strip()
        if not instruction:
            self.toast.show("请输入AI标签指令", "warning")
            return
        self._tag_ai_var.set('')
        self.toast.show("正在执行...", 'info')

        def _do():
            try:
                result = self.agent.process(instruction)
                self.after(0, lambda: self.toast.show(result.get('message', '操作完成'),
                             'success' if result.get('success') else 'error'))
                self.after(0, self._refresh_tags_sidebar)
            except Exception as e:
                self.after(0, lambda: self.toast.show(f"操作出错: {e}", 'error'))

        threading.Thread(target=_do, daemon=True).start()

    # ============ 弹窗 ============
    def _show_history(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("搜索历史")
        dialog.geometry("400x500")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="搜索历史", font=ctk.CTkFont(size=16, weight='bold')).pack(pady=12)

        scroll = ctk.CTkScrollableFrame(dialog, fg_color='transparent')
        scroll.pack(fill='both', expand=True, padx=16)

        if self._search_history:
            for q in self._search_history:
                ctk.CTkButton(scroll, text=q, fg_color='transparent', hover_color=_tc()['bg_hover'],
                               text_color=_tc()['text_dark'], anchor='w', font=ctk.CTkFont(size=13),
                               command=lambda query=q: (self._search_var.set(query), dialog.destroy(), self._perform_search())).pack(fill='x', pady=2)
        else:
            ctk.CTkLabel(scroll, text="暂无搜索历史", text_color=_tc()['text_dim']).pack(pady=40)

        btn_frame = ctk.CTkFrame(dialog, fg_color='transparent')
        btn_frame.pack(fill='x', padx=16, pady=12)
        ctk.CTkButton(btn_frame, text="清空历史", fg_color='transparent',
                       hover_color='#fde8e8', text_color='#e74c3c',
                       command=lambda: (self._search_history.clear(), dialog.destroy())).pack(side='left')
        ctk.CTkButton(btn_frame, text="关闭", command=dialog.destroy).pack(side='right')

    def _show_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("设置")
        dialog.geometry("520x600")
        dialog.transient(self)
        dialog.grab_set()

        cfg = config.load_config()

        scroll = ctk.CTkScrollableFrame(dialog, fg_color='transparent')
        scroll.pack(fill='both', expand=True, padx=16, pady=8)

        # AI 设置
        ctk.CTkLabel(scroll, text="🤖 AI 设置", font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(8, 4))

        ai_enabled = ctk.BooleanVar(value=cfg.get('ai', {}).get('enabled', True))
        ctk.CTkCheckBox(scroll, text="启用 AI", variable=ai_enabled).pack(anchor='w', padx=12)

        ctk.CTkLabel(scroll, text="API 端点", font=ctk.CTkFont(size=12)).pack(anchor='w', padx=12, pady=(8, 0))
        base_url = ctk.CTkEntry(scroll, height=32)
        base_url.pack(fill='x', padx=12)
        base_url.insert(0, cfg.get('ai', {}).get('base_url', ''))

        ctk.CTkLabel(scroll, text="API Key", font=ctk.CTkFont(size=12)).pack(anchor='w', padx=12, pady=(8, 0))
        api_key = ctk.CTkEntry(scroll, height=32, show='•')
        api_key.pack(fill='x', padx=12)
        api_key.insert(0, cfg.get('ai', {}).get('api_key', ''))

        ctk.CTkLabel(scroll, text="模型", font=ctk.CTkFont(size=12)).pack(anchor='w', padx=12, pady=(8, 0))
        model = ctk.CTkEntry(scroll, height=32)
        model.pack(fill='x', padx=12)
        model.insert(0, cfg.get('ai', {}).get('model', 'gpt-4o-mini'))

        # Everything 设置
        ctk.CTkLabel(scroll, text="🔍 Everything 设置", font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 4))
        ctk.CTkLabel(scroll, text="DLL 路径（留空自动检测）", font=ctk.CTkFont(size=12)).pack(anchor='w', padx=12)
        dll_path = ctk.CTkEntry(scroll, height=32)
        dll_path.pack(fill='x', padx=12)
        dll_path.insert(0, cfg.get('everything', {}).get('dll_path', ''))

        # 界面设置
        ctk.CTkLabel(scroll, text="🖥 界面设置", font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 4))
        ctk.CTkLabel(scroll, text="最大结果数", font=ctk.CTkFont(size=12)).pack(anchor='w', padx=12)
        max_results = ctk.CTkEntry(scroll, height=32)
        max_results.pack(fill='x', padx=12)
        max_results.insert(0, str(cfg.get('ui', {}).get('max_results', 100)))

        # 搜索过滤
        ctk.CTkLabel(scroll, text="🔽 搜索过滤", font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 4))

        filter_enabled = ctk.BooleanVar(value=cfg.get('search_filters', {}).get('enabled', True))
        ctk.CTkCheckBox(scroll, text="启用过滤器", variable=filter_enabled).pack(anchor='w', padx=12)

        ctk.CTkLabel(scroll, text="排除文件夹（每行一个）", font=ctk.CTkFont(size=12)).pack(anchor='w', padx=12, pady=(8, 0))
        _default_exclude = config.DEFAULT_CONFIG.get('search_filters', {}).get('exclude_folders', [])
        _user_exclude = cfg.get('search_filters', {}).get('exclude_folders', [])
        exclude_text = '\n'.join(_user_exclude if _user_exclude else _default_exclude)
        exclude_folders = ctk.CTkTextbox(scroll, height=100)
        exclude_folders.pack(fill='x', padx=12)
        exclude_folders.insert('1.0', exclude_text)

        # 保存按钮
        def _save():
            new_cfg = {
                'ai': {
                    'enabled': ai_enabled.get(),
                    'base_url': base_url.get().strip(),
                    'api_key': api_key.get().strip(),
                    'model': model.get().strip() or 'gpt-4o-mini',
                    'max_tokens': 1500, 'temperature': 0.2
                },
                'everything': {'dll_path': dll_path.get().strip()},
                'tmsu': cfg.get('tmsu', {}),
                'ui': {'max_results': int(max_results.get()) or 100, 'theme': ctk.get_appearance_mode()},
                'search_filters': {
                    'enabled': filter_enabled.get(),
                    'exclude_folders': [l.strip() for l in exclude_folders.get('1.0').strip().split('\n') if l.strip()],
                    'exclude_paths': [],
                    'folder_sort_order': cfg.get('search_filters', {}).get('folder_sort_order', 'first')
                }
            }
            config.save_config(new_cfg)
            # 重新初始化 Agent
            from ai_parser import SearchAgent
            self.agent = SearchAgent(self.search_engine, self.tag_manager)
            self._search_filters = new_cfg['search_filters']
            self.toast.show("配置已保存", 'success')
            dialog.destroy()

        btn_frame = ctk.CTkFrame(dialog, fg_color='transparent')
        btn_frame.pack(fill='x', padx=16, pady=12)
        ctk.CTkButton(btn_frame, text="保存", command=_save).pack(side='right', padx=4)
        ctk.CTkButton(btn_frame, text="取消", fg_color='transparent', hover_color=_tc()['bg_hover'],
                       text_color=_tc()['text_sec'], command=dialog.destroy).pack(side='right')

    def _show_create_tag(self):
        dialog = ctk.CTkInputDialog(text="输入新标签名称：", title="新建标签")
        name = dialog.get_input()
        if name and name.strip():
            def _do():
                try:
                    self.agent.process(name.strip(), {"selected_files": ["__create_tag__"]})
                    self.after(0, lambda: (self.toast.show(f"标签 \"{name.strip()}\" 已创建", 'success'),
                                            self._refresh_tags_sidebar()))
                except Exception as e:
                    self.after(0, lambda: self.toast.show(f"创建出错: {e}", 'error'))
            threading.Thread(target=_do, daemon=True).start()

    def _show_rename_tag(self, old_name):
        dialog = ctk.CTkInputDialog(text=f"重命名标签 \"{old_name}\" 为：", title="重命名标签")
        new_name = dialog.get_input()
        if new_name and new_name.strip() and new_name.strip() != old_name:
            def _do():
                try:
                    result = self.tag_manager.rename_tag(old_name, new_name.strip())
                    self.after(0, lambda: self.toast.show(result.get('message', '已重命名'),
                                 'success' if result.get('success') else 'error'))
                    self.after(0, self._refresh_tags_sidebar)
                except Exception as e:
                    self.after(0, lambda: self.toast.show(f"重命名出错: {e}", 'error'))
            threading.Thread(target=_do, daemon=True).start()

    # ============ 状态检查 ============
    def check_status(self):
        if not self.search_engine:
            self._status_label.configure(text_color='#e74c3c')
            return
        detail = self.search_engine.get_status_detail()
        if detail['everything_running']:
            self._status_label.configure(text_color='#27ae60')
        elif detail['cli_available'] or detail['dll_loaded']:
            self._status_label.configure(text_color='#f39c12')
        else:
            self._status_label.configure(text_color='#e74c3c')