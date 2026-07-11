Faind 项目迭代更新文档
版本：v1.1.0
日期：2026-07-11

📌 更新概述
本次迭代新增两大核心能力：

文档内容读取：搜索结果支持对文档类文件（PDF、Word、Excel 等）进行内容提取，为后续 AI 深度阅读和摘要打下基础。开关直接放在主界面搜索框左侧，用户可一键开启/关闭，无需进入设置页面。

AI 意图缓存：建立本地缓存层，显著降低对 DeepSeek/OpenAI 等 API 的重复调用，提升响应速度并节省 Token 消耗。

一、文档内容读取模块 (content_reader.py)
1.1 功能描述
对 Everything SDK 搜索返回的文件列表，在用户双击或选中文件时，自动提取文件的纯文本内容。仅支持文档类格式，忽略可执行文件、图片等非文档格式。

交互方式：

主界面搜索框左侧有一个 📄 开关按钮

开启状态（蓝色高亮）：双击文件时自动提取并显示内容预览

关闭状态（灰色）：双击文件仅打开文件所在位置或调用默认程序打开文件

状态实时保存到 config.json，下次启动自动恢复

1.2 技术选型：PyxTxt
安装命令：

bash
# 基础安装
pip install pyxtxt

# 按需安装各格式解析器
pip install pyxtxt[pdf,docx,presentation,spreadsheet,image,audio,video]
核心接口示例：

python
from pyxtxt import xtxt

# 从文件路径提取
text = xtxt("C:/Documents/报告.pdf")

# 返回值为纯文本字符串，失败时返回空字符串
1.3 配置项设计（合并到 config.json）
json
{
  "ai": { ... },
  "everything": { ... },
  "tmsu": { ... },
  "content_reader": {
    "enabled": false,
    "max_chars_per_file": 5000,
    "supported_formats": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".md", ".rtf", ".epub", ".html", ".htm", ".odt", ".ods", ".odp"]
  },
  "ui": { ... }
}
配置项	类型	默认值	说明
enabled	bool	false	总开关，由搜索框左侧按钮控制
max_chars_per_file	int	5000	单文件最大提取字符数
supported_formats	list	见上	支持的文件扩展名白名单
1.4 模块接口设计
python
# content_reader.py

from pathlib import Path
from typing import Optional, List
import logging
from pyxtxt import xtxt

# 默认支持的文件扩展名白名单
DEFAULT_SUPPORTED_EXTENSIONS = {
    '.pdf', '.docx', '.doc', '.xlsx', '.xls', 
    '.pptx', '.ppt', '.txt', '.md', '.rtf',
    '.epub', '.html', '.htm', '.odt', '.ods', '.odp'
}

class ContentReader:
    """文档内容读取器"""
    
    def __init__(self, config: dict):
        self.enabled = config.get('enabled', False)
        self.max_chars = config.get('max_chars_per_file', 5000)
        self.supported_extensions = set(config.get('supported_formats', DEFAULT_SUPPORTED_EXTENSIONS))
        self.logger = logging.getLogger(__name__)
    
    def toggle(self, enabled: bool):
        """切换开关状态（由搜索框左侧按钮调用）"""
        self.enabled = enabled
        # 同时保存到配置文件
        from config import load_config, save_config
        config = load_config()
        config['content_reader']['enabled'] = enabled
        save_config(config)
        self.logger.info(f"📄 内容读取开关: {'开启' if enabled else '关闭'}")
    
    def is_ready(self) -> bool:
        return self.enabled
    
    def is_supported(self, file_path: str) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
    
    def extract_text(self, file_path: str, max_chars: Optional[int] = None) -> str:
        if not self.enabled:
            return ""
        
        if not self.is_supported(file_path):
            return ""
        
        try:
            raw_text = xtxt(file_path)
            max_chars = max_chars or self.max_chars
            if len(raw_text) > max_chars:
                return raw_text[:max_chars] + "\n... (内容已截断)"
            return raw_text
        except Exception as e:
            self.logger.error(f"提取失败: {file_path}, 错误: {e}")
            return ""
    
    def extract_batch(self, file_paths: List[str]) -> dict:
        if not self.enabled:
            return {path: "" for path in file_paths}
        results = {}
        for path in file_paths:
            results[path] = self.extract_text(path)
        return results
1.5 主界面 UI 设计
text
┌─────────────────────────────────────────────────────────────────────────────┐
│  [📄]  [🔍 搜索框：输入自然语言搜索文件...]  [设置⚙️]                     │
│   ↑                                                                       │
│   开关按钮：点亮=开启内容预览，灰色=关闭                                    │
│   hover 提示："开启后双击文档可预览内容（可能消耗 Token）"                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  结果列表 (共 15 个文件)                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  📄 高数笔记.pdf          C:\Docs\  2026-07-10  2.3MB             │  │
│  │  📄 线性代数.pdf          C:\Docs\  2026-07-08  1.8MB             │  │
│  │  📄 概率论.docx           C:\Docs\  2026-07-05  856KB             │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│  预览面板（双击文件后展开，仅当开关开启时显示）                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  📄 高数笔记.pdf  [关闭×]                                          │  │
│  │  ────────────────────────────────────────────────────────────────── │  │
│  │  高等数学 第一章 函数与极限                                       │  │
│  │  1.1 函数的概念 ...                                               │  │
│  │  1.2 数列的极限 ...                                               │  │
│  │  ... (截断至 5000 字符)                                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
1.6 前端实现 (web/index.html + web/style.css + web/script.js)
index.html 关键部分：

html
<!-- 搜索栏区域 -->
<div class="search-bar">
    <!-- 内容预览开关 -->
    <button id="contentToggle" class="toggle-btn" title="开启后双击文档可预览内容（可能消耗 Token）">
        📄
    </button>
    <!-- 搜索输入框 -->
    <input type="text" id="searchInput" placeholder="输入自然语言搜索文件...">
    <!-- 设置按钮 -->
    <button id="settingsBtn">⚙️</button>
</div>

<!-- 结果列表 -->
<div id="resultList">
    <!-- 动态渲染 -->
</div>

<!-- 预览面板 -->
<div id="previewPanel" style="display:none;">
    <div class="preview-header">
        <span id="previewFileName">📄 文件名称</span>
        <button id="previewClose">×</button>
    </div>
    <div class="preview-body" id="previewContent">
        <!-- 提取的文本内容 -->
    </div>
</div>
style.css 关键样式：

css
.toggle-btn {
    width: 40px;
    height: 40px;
    border: none;
    border-radius: 8px;
    font-size: 20px;
    cursor: pointer;
    background: #f0f0f0;
    color: #999;
    transition: all 0.2s;
    flex-shrink: 0;
}

.toggle-btn.active {
    background: #4A90D9;
    color: #fff;
    box-shadow: 0 0 8px rgba(74, 144, 217, 0.4);
}

.toggle-btn:hover {
    transform: scale(1.05);
}

.toggle-btn.active:hover {
    background: #3a7bc8;
}

/* 预览面板 - 从底部滑出 */
#previewPanel {
    border-top: 2px solid #4A90D9;
    background: #fafafa;
    max-height: 300px;
    overflow-y: auto;
    animation: slideUp 0.25s ease;
}

@keyframes slideUp {
    from { max-height: 0; opacity: 0; }
    to { max-height: 300px; opacity: 1; }
}
script.js 核心逻辑：

javascript
// ========== 内容读取开关 ==========
let contentReaderEnabled = false;

// 从配置加载初始状态
eel.load_config()(function(config) {
    contentReaderEnabled = config.content_reader?.enabled || false;
    updateToggleUI();
});

// 切换按钮
document.getElementById('contentToggle').addEventListener('click', function() {
    contentReaderEnabled = !contentReaderEnabled;
    updateToggleUI();
    // 通知后端保存状态
    eel.toggle_content_reader(contentReaderEnabled)();
    showToast(contentReaderEnabled ? '📄 内容预览已开启' : '📄 内容预览已关闭', 'info');
});

function updateToggleUI() {
    const btn = document.getElementById('contentToggle');
    if (contentReaderEnabled) {
        btn.classList.add('active');
        btn.title = '点击关闭内容预览（当前已开启）';
    } else {
        btn.classList.remove('active');
        btn.title = '开启后双击文档可预览内容（可能消耗 Token）';
    }
}

// ========== 双击文件行 ==========
function onFileDoubleClick(filePath, fileName) {
    if (contentReaderEnabled) {
        // 开启预览模式：提取内容并显示
        eel.preview_file(filePath)(function(response) {
            if (response.success) {
                showPreviewPanel(fileName, response.content);
            } else {
                // 提取失败，回退到打开文件
                showToast('预览失败: ' + response.error, 'error');
                eel.open_file(filePath)();
            }
        });
    } else {
        // 关闭预览模式：直接打开文件
        eel.open_file(filePath)();
    }
}

function showPreviewPanel(fileName, content) {
    document.getElementById('previewFileName').textContent = '📄 ' + fileName;
    document.getElementById('previewContent').textContent = content;
    document.getElementById('previewPanel').style.display = 'block';
    // 滚动到预览面板
    document.getElementById('previewPanel').scrollIntoView({ behavior: 'smooth', block: 'end' });
}

document.getElementById('previewClose').addEventListener('click', function() {
    document.getElementById('previewPanel').style.display = 'none';
});
1.7 后端 Eel 接口 (main.py)
python
import eel
from content_reader import ContentReader
from config import load_config, save_config

# 初始化
config = load_config()
reader = ContentReader(config.get('content_reader', {}))

@eel.expose
def toggle_content_reader(enabled: bool):
    """切换内容读取开关（由前端按钮调用）"""
    reader.toggle(enabled)
    return {"success": True}

@eel.expose
def preview_file(file_path: str) -> dict:
    """
    预览文件内容
    :return: {"success": bool, "content": str, "error": str}
    """
    if not reader.is_ready():
        return {"success": False, "error": "内容预览未开启"}
    
    if not reader.is_supported(file_path):
        return {"success": False, "error": "不支持的文件格式"}
    
    content = reader.extract_text(file_path)
    if content:
        return {"success": True, "content": content}
    else:
        return {"success": False, "error": "内容提取失败，文件可能已加密或损坏"}

@eel.expose
def open_file(file_path: str):
    """用系统默认程序打开文件"""
    import os
    os.startfile(file_path)
二、AI 意图缓存模块 (ai_cache.py)
2.1 功能描述
避免对相同或相似的输入重复调用 AI API。将用户自然语言 → 搜索词 的映射关系缓存到本地 JSON 文件中。

2.2 缓存策略
策略项	说明
缓存内容	仅缓存 action=="search" 的意图解析结果
缓存键	用户输入的归一化哈希值（去除语气词、标点）
过期时间	永久有效，但可通过 max_entries 淘汰旧记录
淘汰策略	LRU（最近最少使用），默认最大 1000 条
触发条件	仅当用户没有选中任何文件且输入不含打标指令时触发缓存
2.3 模块接口设计
python
# ai_cache.py

import json
import hashlib
import re
from pathlib import Path
from collections import OrderedDict
from typing import Optional, Dict, Any
import time

class AICache:
    """AI 意图解析的本地缓存"""
    
    def __init__(self, cache_dir: str = "~/.faind", max_entries: int = 1000):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "ai_cache.json"
        self.max_entries = max_entries
        self.cache: Dict[str, Any] = self._load()
    
    def _load(self) -> dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save(self):
        if len(self.cache) > self.max_entries:
            ordered = OrderedDict(self.cache)
            while len(ordered) > self.max_entries:
                ordered.popitem(last=False)
            self.cache = dict(ordered)
        
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)
    
    def _normalize(self, text: str) -> str:
        """归一化用户输入，提高缓存命中率"""
        stopwords = ['帮我', '请', '一下', '那个', '这个', '看看', '找找', '我要', '我想', '帮忙']
        for word in stopwords:
            text = text.replace(word, '')
        text = re.sub(r'[，,。.！!？?、:：；;]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def _hash(self, text: str) -> str:
        normalized = self._normalize(text)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    def get(self, user_input: str) -> Optional[dict]:
        key = self._hash(user_input)
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        return None
    
    def set(self, user_input: str, value: dict):
        key = self._hash(user_input)
        value['_cached_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        self.cache[key] = value
        self._save()
    
    def clear(self):
        self.cache = {}
        self._save()
    
    def get_stats(self) -> dict:
        return {
            "total_entries": len(self.cache),
            "max_entries": self.max_entries,
            "cache_file": str(self.cache_file)
        }
2.4 集成到 AI 解析模块 (ai_parser.py)
python
# ai_parser.py 修改部分

from ai_cache import AICache
import logging

class AIParser:
    def __init__(self, config: dict):
        self.client = OpenAI(...)
        self.cache = AICache()
        self.logger = logging.getLogger(__name__)
    
    def parse(self, user_input: str, context_files: list = None) -> dict:
        """解析用户意图，优先从缓存读取"""
        is_tagging = any(kw in user_input for kw in ['标记', '添加标签', '打标签', '归类', '标签'])
        
        if not context_files and not is_tagging:
            cached = self.cache.get(user_input)
            if cached:
                self.logger.info(f"✅ 缓存命中: {user_input}")
                result = {k: v for k, v in cached.items() if not k.startswith('_')}
                return result
            self.logger.info(f"⏳ 缓存未命中，调用 AI: {user_input}")
        else:
            self.logger.info(f"⏳ 跳过缓存，调用 AI: {user_input}")
        
        result = self._call_ai(user_input, context_files)
        
        if result.get('action') == 'search' and not context_files:
            self.cache.set(user_input, result)
            self.logger.info(f"💾 已缓存: {user_input}")
        
        return result
    
    def clear_cache(self):
        self.cache.clear()
        self.logger.info("🗑️ AI 缓存已清空")
2.5 缓存文件示例 (~/.faind/ai_cache.json)
json
{
  "e8d6f8a3b7c...": {
    "action": "search",
    "everything_query": "高数|高等数学 *.pdf",
    "_cached_at": "2026-07-11T14:30:00"
  },
  "a1b2c3d4e5f...": {
    "action": "search",
    "everything_query": "报告 工作总结 dm:last30days",
    "_cached_at": "2026-07-11T15:00:00"
  }
}
三、修改文件清单
文件	操作	说明
content_reader.py	新增	文档内容提取模块，支持开关控制
ai_cache.py	新增	AI 意图缓存模块
ai_parser.py	修改	集成缓存逻辑
main.py	修改	新增 toggle_content_reader()、preview_file()、open_file() 接口
config.py	修改	配置文件增加 content_reader 配置段
web/index.html	修改	搜索框左侧增加开关按钮，底部增加预览面板
web/style.css	修改	开关按钮样式、预览面板样式、滑出动画
web/script.js	修改	开关切换逻辑、双击文件逻辑、预览面板控制
requirements.txt	修改	新增依赖 pyxtxt
四、测试用例
4.1 文档读取测试
测试场景	操作	预期结果
开关默认状态	首次启动	灰色（关闭），config.json 中 enabled: false
开启开关	点击左侧 📄 按钮	按钮变为蓝色高亮，hover 提示变化
关闭开关	再次点击	按钮变回灰色
开关开启 + 双击 PDF	双击结果中的 PDF	预览面板滑出，显示文本内容
开关关闭 + 双击 PDF	双击结果中的 PDF	直接调用系统默认程序打开 PDF
开关开启 + 双击 EXE	双击结果中的 EXE	提示"不支持的文件格式"
开关开启 + 双击加密 PDF	双击加密 PDF	提示"内容提取失败，文件可能已加密"
状态持久化	关闭软件重新打开	开关状态与关闭前一致
4.2 缓存测试
测试场景	预期结果
输入"高数资料" → 回车	第一次走 AI，耗时 ~1s
再次输入"高数资料" → 回车	直接命中缓存，耗时 <10ms
输入"帮我找高数资料"	归一化后命中缓存
选中文件后输入"高数资料"	有上下文，强制走 AI，不命中缓存
输入"给这些文件打标签 高数"	含打标动词，不走缓存
五、UI 交互细节
5.1 开关按钮状态
状态	样式	Hover 提示
关闭（默认）	灰色背景，灰色 📄	"开启后双击文档可预览内容（可能消耗 Token）"
开启	蓝色背景，白色 📄，带发光阴影	"点击关闭内容预览（当前已开启）"
开启 + 正在预览	蓝色背景，📄 带旋转加载动画	"正在提取文档内容..."
5.2 预览面板
双击文件行时从底部滑出（动画 0.25s）

最大高度 300px，超出滚动

右上角 × 按钮关闭

再次双击其他文件时，面板内容替换并保持在展开状态

关闭开关时，预览面板自动收起

六、后续扩展方向
全文检索：将提取的文档内容建立本地全文索引（如 SQLite FTS5），支持内容关键词搜索。

AI 智能问答：选中文件后，AI 可基于提取的内容回答用户提问。

OCR 图片文字识别：集成 Tesseract，从扫描版 PDF 或图片中提取文字。

缓存 TTL：为 AI 缓存添加有效期（如 30 天），自动清理过期映射。

Token 用量统计：在状态栏显示本月已用 Token 估算。

快捷键：Ctrl+Shift+P 快速切换内容预览开关。