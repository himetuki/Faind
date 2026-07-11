# Faind —— 智能文件定位与标签系统 项目开发文档

## 1. 项目概述

**Faind** 是一款轻量级、AI 驱动的 Windows 桌面工具，旨在帮助用户通过自然语言快速定位本地文件，并利用 AI 辅助管理文件标签。用户只需像聊天一样输入需求（如“找一下高数课程”），Faind 即可自动生成 Everything 搜索语法并呈现结果；同时，用户可对选中的文件批量添加或修改标签，AI 会根据语义自动建议标签。

核心目标：
- **极速搜索**：基于 Everything SDK 实现毫秒级文件定位。
- **自然语言交互**：利用可配置的 AI API（兼容 OpenAI 接口）将口语转为结构化搜索/标签指令。
- **轻量高效**：不使用 Electron，采用轻量级前端技术，后台占用小，打包体积控制在 50MB 以内。
- **可配置性**：支持用户自定义 AI 服务端点、API Key 和模型名称。
- **可扩展标签**：集成成熟的命令行标签工具（如 TMSU），不依赖 Everything 1.5 自带的标签功能。

## 2. 功能需求

### 2.1 核心功能
- **AI 驱动的搜索**：用户在主输入框输入自然语言（如“上周修改的PDF合同”），系统调用 AI 解析出 Everything 搜索语法（如 `*.pdf dm:lastweek`），然后通过 Everything SDK 执行搜索，并展示文件列表。
- **文件标签管理**：
  - 用户可在结果列表中多选文件，通过自然语言指令（如“将这些标记为 高数资料”）批量添加标签。
  - AI 会根据文件名/路径自动推荐标签，用户可修改确认。
  - 支持查看、删除文件的已有标签。
- **标签系统集成**：使用 TMSU（或 TagSpaces CLI）作为底层标签存储引擎，保证标签数据独立、可移植。

### 2.2 辅助功能
- **搜索历史**：保存用户输入的查询历史，便于快速重用。
- **快速筛选**：在结果列表上方提供文件类型快捷筛选（文档、图片、音频、视频、压缩包等），这些筛选条件会与 AI 生成的搜索词结合。
- **标签云**：展示所有已使用的标签，点击可快速搜索具有该标签的文件。

### 2.3 非功能需求
- **轻量占用**：后台常驻内存 < 100MB，空闲时 CPU 占用接近 0。
- **响应迅速**：从输入到结果显示 < 1 秒（不含 AI 调用网络延迟）。
- **隐私保护**：所有标签数据本地存储，AI API 密钥保存在本地配置文件中，不上传任何文件内容。
- **可配置**：提供设置界面，允许用户修改 AI 端点、API Key、模型、Everything 路径、标签工具路径等。

## 3. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| **GUI 框架** | **Eel** (Python + HTML/CSS/JS) | 轻量，使用系统 Edge/Chrome 内核，打包后体积小，Python 生态丰富，便于调用 AI 和 SDK。 |
| **后端语言** | Python 3.10+ | 易于开发，丰富的 AI 库，ctypes 可调用 Everything DLL。 |
| **搜索引擎** | **Everything SDK** (`Everything64.dll`) | 性能最佳，直接内存交互，比 es.exe 更高效。 |
| **标签系统** | **TMSU** (命令行工具) | 纯命令行，易于集成，标签存储在独立 SQLite 中，支持虚拟文件系统。 |
| **AI 客户端** | 自定义 OpenAI 兼容客户端 | 支持 OpenAI、Azure、本地 Ollama 等，用户可配置 base_url 和 api_key。 |
| **配置管理** | JSON 文件 (`config.json`) | 简单易读，支持热加载。 |
| **打包工具** | PyInstaller | 将 Python 代码和资源打包为单个 exe。 |
| **前端** | 原生 HTML + CSS + JavaScript (Vanilla) | 无需框架，减少依赖，减小体积。可使用简易图标库（如 FontAwesome）。 |

**备选方案**：
- 若希望更原生体验，可考虑 C# + WPF + WebView2，但开发周期较长。
- 若用户熟悉 Rust，可使用 Tauri + 前端框架，但学习成本较高。

## 4. 系统架构

### 4.1 整体架构图

```
+------------------+      +----------------------+      +-------------------+
|    用户界面      |      |    后端服务 (Python)  |      |   外部工具/服务   |
| (HTML/CSS/JS)   | <--> |  - Eel 暴露的 API    | <--> |  - Everything SDK |
|  - 搜索输入框    |      |  - AI 意图解析模块   |      |  - TMSU 命令行    |
|  - 结果列表      |      |  - 搜索执行模块      |      |  - AI API (远程)  |
|  - 标签面板      |      |  - 标签管理模块      |      |                   |
|  - 设置界面      |      |  - 配置管理模块      |      |                   |
+------------------+      +----------------------+      +-------------------+
```

### 4.2 数据流

1. **搜索流程**：
   - 用户输入自然语言 → Eel 调用 Python 函数 `search_files(natural_language)`。
   - Python 调用 AI 解析模块，获得结构化的 Everything 查询字符串。
   - 搜索模块通过 SDK 执行查询，返回文件列表（含路径、大小、修改日期）。
   - 结果传回前端渲染。

2. **打标流程**：
   - 用户选中文件 → 输入指令（如“标记为 高数”） → 调用 `apply_tags(file_paths, natural_language)`。
   - AI 解析出要添加/删除的标签列表。
   - 标签管理模块调用 TMSU 命令行对每个文件执行标签操作。
   - 结果反馈给前端。

3. **配置流程**：
   - 用户在设置界面修改 AI 参数 → 保存到 `config.json` → 后端重新加载配置。

## 5. 模块详细设计

### 5.1 AI 意图解析模块 (`ai_parser.py`)

**职责**：接收用户自然语言，返回结构化指令（搜索或标签）。

**接口**：
```python
def parse_intent(text: str, context: dict = None) -> dict:
    """
    解析用户意图
    :param text: 用户输入
    :param context: 可选上下文，如当前选中的文件列表
    :return: 结构化指令，示例：
        {
            "action": "search",   # 或 "tag"
            "everything_query": "*.pdf dm:today",
            "tags": ["高数"],     # 仅当 action=="tag" 时
            "files": ["C:/a.pdf"] # 仅当 action=="tag" 时（来自上下文）
        }
    """
```

**实现**：
- 使用 OpenAI 兼容客户端调用用户配置的模型。
- 设计系统提示词（system prompt）强制输出 JSON，限制输出格式。
- 示例系统提示：
  ```
  你是一个文件搜索与标签助手。用户会用自然语言描述需求，请分析意图并返回JSON。
  意图类型：
  1. 搜索文件：返回 {"action":"search", "everything_query":"<搜索语法>"}
     Everything语法支持：关键词、*.扩展名、path:、dm:日期、size:大小。
  2. 为文件打标签：仅当用户明确提到“标记”、“添加标签”等词，并且上下文提供了文件列表时，返回 {"action":"tag", "tags":["标签1","标签2"], "files":[...]}。
  3. 仅输出JSON，不要其他文字。
  ```

- 若解析失败，提供降级方案（如直接当作关键词搜索）。

### 5.2 Everything 搜索模块 (`everything_search.py`)

**职责**：封装 Everything SDK，提供搜索和文件信息获取功能。

**接口**：
```python
class EverythingSearch:
    def __init__(self, dll_path="Everything64.dll"):
        self.dll = ctypes.WinDLL(dll_path)
        self._init_sdk()
    
    def search(self, query: str, max_results: int = 100) -> list:
        """执行搜索，返回文件信息字典列表"""
        # 调用 SDK 函数
        # 返回 [{"path":..., "name":..., "size":..., "date_modified":...}, ...]
    
    def get_file_info(self, file_path: str) -> dict:
        """获取单个文件的属性"""
```

**实现要点**：
- 使用 `ctypes` 加载 `Everything64.dll`，调用 `Everything_SetSearchW`、`Everything_Query`、`Everything_GetNumResults`、`Everything_GetResultFullPathName` 等函数。
- 注意 Unicode 字符串处理。
- 错误处理：如果 Everything 未运行，给出提示。

### 5.3 标签管理模块 (`tag_manager.py`)

**职责**：与 TMSU 命令行交互，管理文件标签。

**接口**：
```python
class TagManager:
    def __init__(self, tmsu_path="tmsu.exe", db_path="~/.tmsu/default.db"):
        self.tmsu_path = tmsu_path
        self.db_path = db_path
    
    def add_tags(self, file_paths: list, tags: list) -> bool:
        """为文件添加标签"""
        # 调用 tmsu tag <file> <tag1> <tag2> ...
    
    def remove_tags(self, file_paths: list, tags: list) -> bool:
        """移除标签"""
    
    def get_tags(self, file_path: str) -> list:
        """获取文件所有标签"""
    
    def search_by_tag(self, tag: str) -> list:
        """列出具有某标签的所有文件路径"""
```

**实现**：
- 使用 `subprocess` 调用 TMSU 命令。
- 注意处理文件路径中的空格和特殊字符。
- 若 TMSU 未安装，首次运行时可自动下载（或提示用户）。

### 5.4 GUI 交互模块 (`main.py` + Eel)

**职责**：启动 Web 界面，暴露 Python 函数给前端。

**Eel 暴露的函数**：
- `eel.search(query)` -> 调用 `ai_parser.parse_intent` + `everything_search.search`，返回结果列表。
- `eel.apply_tags(file_paths, instruction)` -> 调用 `ai_parser.parse_intent` (带上下文) + `tag_manager.add_tags`。
- `eel.load_config()` -> 返回当前配置。
- `eel.save_config(config)` -> 保存配置到 `config.json`。
- `eel.get_all_tags()` -> 返回所有已使用的标签。

**前端页面**：
- 主界面：左侧输入框，右侧结果列表。
- 结果列表：每行显示文件名、路径、大小、修改日期、标签（可点击编辑）。
- 多选支持（复选框或 Ctrl+单击）。
- 底部标签云区域。
- 设置界面：弹出窗口，配置 AI 端点、Key、模型、TMSU 路径等。

### 5.5 配置管理模块 (`config.py`)

**职责**：读取/写入 `config.json`。

**配置文件结构**：
```json
{
  "ai": {
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx",
    "model": "gpt-4o-mini",
    "max_tokens": 200,
    "temperature": 0.2
  },
  "everything": {
    "dll_path": "C:/Program Files/Everything/Everything64.dll"
  },
  "tmsu": {
    "executable_path": "tmsu.exe",
    "db_path": "C:/Users/username/.tmsu/default.db"
  },
  "ui": {
    "max_results": 100,
    "theme": "light"
  }
}
```

**接口**：
- `load_config()` -> 返回字典
- `save_config(config_dict)`

## 6. 内部 API 接口（Eel 前后端通信）

| 前端调用 | Python 函数 | 参数 | 返回值 |
|---------|------------|------|--------|
| `eel.search(text)` | `search(text)` | `text`: 自然语言 | `[{"path":..., "name":..., ...}]` |
| `eel.apply_tags(files, instruction)` | `apply_tags(files, instruction)` | `files`: 路径列表，`instruction`: 自然语言 | `{"success": bool, "message": str}` |
| `eel.get_tags_for_file(file_path)` | `get_tags(file_path)` | `file_path`: 字符串 | `["tag1","tag2"]` |
| `eel.load_config()` | `load_config()` | 无 | 配置字典 |
| `eel.save_config(config)` | `save_config(config)` | `config`: 字典 | `{"success": bool}` |
| `eel.get_all_tags()` | `get_all_tags()` | 无 | `["tag1","tag2",...]` |
| `eel.open_file(file_path)` | `open_file(file_path)` | 路径 | 调用 `os.startfile` |

## 7. 数据存储

- **配置文件**：`%APPDATA%/Faind/config.json`（或用户目录下的 `.faind/config.json`）。
- **标签数据库**：由 TMSU 管理，默认在 `~/.tmsu/default.db`，可配置。
- **搜索历史**：可存储在配置文件中或独立文件 `history.json`，保存最近 50 条。
- **日志**：可选 `faind.log`，记录错误和调试信息。

## 8. 开发环境与构建

### 8.1 开发环境
- Python 3.10+
- 安装依赖：`pip install eel openai requests python-dotenv`
- 下载 Everything SDK 并放置 `Everything64.dll`。
- 下载 TMSU 可执行文件并加入 PATH。

### 8.2 项目目录结构
```
Faind/
├── main.py                 # 启动 Eel 服务
├── ai_parser.py            # AI 意图解析
├── everything_search.py    # Everything SDK 封装
├── tag_manager.py          # TMSU 封装
├── config.py               # 配置管理
├── web/                    # 前端资源
│   ├── index.html
│   ├── style.css
│   ├── script.js
│   └── assets/ (图标等)
├── config.json             # 默认配置（首次运行生成）
├── requirements.txt
└── README.md
```

### 8.3 构建为 exe（使用 PyInstaller）
- 安装 PyInstaller：`pip install pyinstaller`
- 执行：`pyinstaller --onefile --windowed --add-data "web;web" --name Faind main.py`
- 确保 `Everything64.dll` 与 exe 同目录或配置路径。

## 9. 开发计划（分阶段）

### Phase 1: 核心搜索（MVP）
- [ ] 完成 `everything_search.py`，实现 SDK 调用，测试搜索功能。
- [ ] 完成 `ai_parser.py`，硬编码测试（先不接 AI，用规则匹配）。
- [ ] 搭建 Eel 界面，实现输入框和结果列表。
- [ ] 整合：输入文本 → 调用 AI 解析（模拟）→ 搜索 → 显示结果。

### Phase 2: AI 集成与标签
- [ ] 接入真实 AI API，实现动态生成搜索词。
- [ ] 集成 TMSU，实现 `tag_manager.py`。
- [ ] 前端支持多选，添加“打标签”输入框，调用 AI 生成标签指令。
- [ ] 显示已有标签并支持删除。

### Phase 3: 配置与优化
- [ ] 实现设置界面，可修改 AI 参数、路径等。
- [ ] 添加搜索历史和标签云。
- [ ] 性能优化（缓存搜索结果、异步 AI 调用）。
- [ ] 错误处理与用户提示。

### Phase 4: 打包与发布
- [ ] 使用 PyInstaller 打包为单个 exe。
- [ ] 编写用户手册和安装说明。
- [ ] 测试在不同 Windows 版本上的兼容性。

## 10. 注意事项与风险

### 10.1 依赖风险
- **Everything 必须运行**：若未运行，SDK 调用会失败，需在程序中检测并提示用户启动。
- **TMSU 依赖**：需用户自行安装或自动下载（提供下载链接）。
- **AI API 可用性**：网络异常或 API 密钥失效时，应降级为直接关键词搜索（用户可关闭 AI 功能）。

### 10.2 权限问题
- Everything 需要以管理员权限运行才能索引系统目录，建议用户以管理员模式启动 Everything。
- 本应用不需要管理员权限。

### 10.3 隐私与安全
- AI API 密钥存储在本地，不要上传。
- 所有标签和搜索操作均在本地，不传输文件内容。

### 10.4 性能优化
- AI 调用是异步的，不应阻塞 UI。Eel 支持异步函数（`@eel.expose` 配合 `asyncio` 或使用线程）。
- 搜索结果缓存：避免重复搜索相同查询。
- 标签操作批量处理：一次 TMSU 调用可同时处理多个文件。

### 10.5 兼容性
- 仅支持 Windows（依赖 Everything 和 TMSU 的 Windows 版本）。
- Python 3.8+ 均可，推荐 3.10。

## 11. 附录

### 11.1 关键代码示例（给 AI Coding 的参考）

**everything_search.py 核心片段**：
```python
import ctypes
from ctypes import wintypes

class EverythingSearch:
    def __init__(self, dll_path="Everything64.dll"):
        self.dll = ctypes.WinDLL(dll_path)
        self._init_sdk()

    def _init_sdk(self):
        # 初始化 SDK，设置默认参数
        self.dll.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
        self.dll.Everything_Query.argtypes = [wintypes.BOOL]
        self.dll.Everything_Query.restype = wintypes.BOOL
        self.dll.Everything_GetNumResults.argtypes = []
        self.dll.Everything_GetNumResults.restype = ctypes.c_uint
        self.dll.Everything_GetResultFullPathNameW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        self.dll.Everything_GetResultFullPathNameW.restype = ctypes.c_uint
        self.dll.Everything_SetMaxResults.argtypes = [wintypes.DWORD]

    def search(self, query: str, max_results=100):
        self.dll.Everything_SetMaxResults(max_results)
        self.dll.Everything_SetSearchW(query)
        if self.dll.Everything_Query(True):  # 等待完成
            num = self.dll.Everything_GetNumResults()
            results = []
            for i in range(num):
                buf = ctypes.create_unicode_buffer(260)
                self.dll.Everything_GetResultFullPathNameW(i, buf, 260)
                # 也可以获取大小、修改时间等
                results.append({"path": buf.value})
            return results
        return []
```

**ai_parser.py 核心片段**：
```python
import openai
import json

class AIParser:
    def __init__(self, config):
        self.client = openai.OpenAI(
            base_url=config['base_url'],
            api_key=config['api_key']
        )
        self.model = config['model']
        self.system_prompt = """
        你是一个文件搜索与标签助手。用户会用自然语言描述需求，请分析意图并返回JSON。
        意图类型：
        1. 搜索文件：返回 {"action":"search", "everything_query":"<搜索语法>"}
           Everything语法支持：关键词、*.扩展名、path:、dm:日期、size:大小。
        2. 为文件打标签：仅当用户明确提到“标记”、“添加标签”等词，并且上下文提供了文件列表时，返回 {"action":"tag", "tags":["标签1","标签2"], "files":[...]}。
        3. 仅输出JSON，不要其他文字。
        """

    def parse(self, user_text, context_files=None):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_text}
        ]
        if context_files:
            messages.append({"role": "user", "content": f"上下文文件列表：{context_files}"})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"}  # 部分API支持
        )
        return json.loads(response.choices[0].message.content)
```

### 11.2 相关资源链接
- Everything SDK ：library\Everything-SDK
- Everything es.exe : library\ES-1.1.0.30.x64
- TMSU 官网：https://tmsu.org/
- Eel 文档：https://github.com/python-eel/Eel
- OpenAI Python 库：https://github.com/openai/openai-python

---

**文档版本**：1.0  
**最后更新**：2026-07-11  
**作者**：Faind 开发团队