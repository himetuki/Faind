# Faind

智能文件定位与标签系统 — 用自然语言找到你的文件。

Faind 结合 Everything SDK / [fd](https://github.com/sharkdp/fd) 的极速文件搜索与 AI 语义理解，让你用自然语言描述即可精确定位文件，并为文件添加标签进行组织管理。

## 特性

- **自然语言搜索** — 输入"上周在E盘修改的MD文件"，AI 自动解析为搜索查询
- **多后端搜索** — 自动选择最优引擎：Everything SDK（DLL 直连）> fd CLI > ES CLI，支持热切换
- **智能查询转换** — Everything 语法无损转换为 fd 参数（日期`dm:` → `--changed-within`，大小`size:` → `--size`，路径排除`!path:` → `-E`）
- **路径优先搜索** — 搜索时优先匹配路径/文件夹名，搜索范围智能限定（"在E盘" → 仅搜 E:\）
- **文件标签系统** — 基于 SQLite 的标签管理
- **深色/浅色主题** — 一键切换，设置自动持久化
- **Fluent Design 界面** — 基于 PySide6 + qfluentwidgets 的现代化桌面界面，侧边栏导航
- **零浏览器依赖** — 原生桌面应用，无需 Chrome/WebView
- **零前置依赖** — 内嵌 Everything 便携版，启动时自动后台运行，无需用户单独安装
- **便携分发** — 单 exe 文件，所有依赖内嵌，配置跟随 exe
- **文档内容搜索** — 支持 PDF、Office、文本等格式的全文检索，可选 AI 内容总结

## 前置要求

- Windows 10/11

> Faind 已内嵌 Everything 便携版（MIT 许可），启动时自动在后台拉起，无需手动安装 Everything。
> 首次启动时 Everything 会扫描磁盘建立索引（通常几十秒），后续启动即可秒搜。
>
> fd.exe 为可选的轻量替代引擎，无需索引，适合 Everything 不可用时的回退方案。

## 快速开始

### 直接使用

1. 从 [Releases](../../releases) 下载 `Faind.exe`
2. 双击运行，首次启动自动创建 `config.json`
3. Everything 会在后台自动启动（系统托盘可见图标），稍等索引建立即可搜索

### 从源码运行

```bash
git clone https://github.com/himetuki/Faind.git
cd Faind

# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 下载 Everything 便携版（一次性）
#    从 https://www.voidtools.com/downloads/ 下载 Everything Portable Zip x64
#    解压后将 Everything64.exe 放到 library/Everything/ 目录下

# 2a. (可选) 下载 fd
#    从 https://github.com/sharkdp/fd/releases 下载 fd-vX.X.X-x86_64-pc-windows-msvc.zip
#    解压后将 fd.exe 放到 library/fd/ 目录下

# 3. 运行
python main.py
```

### 打包为 exe

双击 `build.bat`，或手动执行：

```bash
pip install pyinstaller
pyinstaller Faind.spec --noconfirm
# 输出: dist/Faind.exe
```

## 配置

首次运行会在 exe 旁边生成 `config.json`，主要配置项：

| 配置域 | 说明 |
|--------|------|
| `search_engine` | 搜索后端：`auto`（自动选择）/ `fd`（fd CLI）/ `everything_dll`（SDK 直连）/ `everything_es`（ES CLI） |
| `ai` | AI 提供商、API Key、模型等 |
| `everything` | Everything SDK DLL / ES CLI 路径（留空则自动检测内置工具） |
| `fd` | fd.exe 路径（留空则自动检测 `library/fd/fd.exe`） |
| `ui` | 主题（Dark/Light）、最大结果数 |
| `search_filters` | 排除文件夹、排序方式等 |

AI 默认使用智谱 GLM-4.7-Flash，也可切换为任何 OpenAI 兼容 API。

## 项目结构

```
Faind/
├── main.py              # 主入口（PySide6 事件循环）
├── gui.py               # PySide6 + qfluentwidgets FluentUI 界面
├── ai_parser.py         # AI 搜索 Agent
├── ai_cache.py          # AI 缓存（避免重复请求）
├── ai_response_logger.py # AI 响应日志
├── content_reader.py    # 文档内容读取（PDF/Office/文本等）
├── everything_search.py # 多后端搜索封装（Everything DLL / fd CLI / ES CLI）
├── tag_manager.py       # 标签管理（SQLite）
├── config.py            # 配置管理
├── config.example.json  # 配置模板
├── Faind.spec           # PyInstaller 打包配置
├── build.bat            # 一键打包脚本
├── build.ps1            # PowerShell 打包脚本
├── requirements.txt     # Python 依赖
├── LICENSE              # MIT License
├── NOTICE.txt           # 第三方许可证汇总
└── library/             # 外部依赖
    ├── fd/              # fd.exe （MIT）— 轻量替代引擎
    ├── Everything/      # Everything 便携版（MIT）— 自动后台运行
    ├── Everything-SDK/  # Everything SDK DLL（MIT）
    └── ES-1.1.0.30.x64/ # Everything ES CLI 工具（MIT）
```

## 致谢与开源许可

本项目使用以下开源项目，感谢它们的作者：

### Everything

- 作者：David Carpenter
- 许可证：MIT License
- 项目主页：https://www.voidtools.com/
- 源码位置：`library/Everything/`、`library/Everything-SDK/`

> Copyright (C) 2018 David Carpenter
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

### fd

- 作者：David Peter (sharkdp)
- 许可证：MIT License / Apache License 2.0（双许可）
- 项目主页：https://github.com/sharkdp/fd
- 源码位置：`library/fd/`

> fd 是 Everything 不可用时的轻量替代引擎，支持正则匹配、文件类型过滤、日期/大小筛选等。

## 许可证

Faind 以 MIT License 发布，详见 [LICENSE](LICENSE) 文件。

本软件内嵌了 Everything、fd 等第三方组件，完整许可证列表见 [NOTICE.txt](NOTICE.txt)。
