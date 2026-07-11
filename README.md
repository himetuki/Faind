# Faind

智能文件定位与标签系统 — 用自然语言找到你的文件。

Faind 结合 [Everything](https://www.voidtools.com/) 的极速文件索引与 AI 语义理解，让你用自然语言描述即可精确定位文件，并为文件添加标签进行组织管理。

## 特性

- **自然语言搜索** — 输入"上周修改的PDF合同"，AI 自动解析为 Everything 查询语法
- **路径优先搜索** — 搜索时优先匹配路径/文件夹名，再搜索单独文件，大幅提升命中率
- **文件标签系统** — 基于 SQLite 的标签管理，支持 TMSU 双向同步
- **深色/浅色主题** — 一键切换，设置自动持久化
- **零浏览器依赖** — 基于 customtkinter 的原生桌面界面，无需 Chrome/WebView
- **便携分发** — 单 exe 文件，所有依赖内嵌，配置跟随 exe

## 前置要求

- Windows 10/11（依赖 Everything 的文件索引）
- [Everything](https://www.voidtools.com/) 需在后台运行（免费，安装后自动常驻）

## 快速开始

### 直接使用

1. 确保 Everything 已安装并运行
2. 从 [Releases](../../releases) 下载 `Faind.exe`
3. 双击运行，首次启动自动创建 `config.json`

### 从源码运行

```bash
git clone https://github.com/<your-username>/Faind.git
cd Faind
pip install -r requirements.txt
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
| `ai` | AI 提供商、API Key、模型等 |
| `everything` | Everything SDK DLL / ES CLI 路径 |
| `tmsu` | TMSU 可执行文件和数据库路径 |
| `ui` | 主题（Dark/Light）、最大结果数 |
| `search_filters` | 排除文件夹、排序方式等 |

AI 默认使用智谱 GLM-4.7-Flash，也可切换为任何 OpenAI 兼容 API。

## 项目结构

```
Faind/
├── main.py              # 主入口
├── gui.py               # customtkinter 界面
├── ai_parser.py         # AI 搜索 Agent
├── everything_search.py # Everything 搜索封装
├── tag_manager.py       # 标签管理（SQLite + TMSU）
├── config.py            # 配置管理
├── Faind.spec           # PyInstaller 打包配置
├── build.bat            # 一键打包脚本
├── requirements.txt     # Python 依赖
└── library/             # 外部依赖
    ├── Everything-SDK/  # Everything SDK（MIT）
    ├── ES-1.1.0.30.x64/ # Everything ES CLI 工具
    └── tmsu/            # TMSU（GPL v3）
```

## 致谢与开源许可

本项目使用以下开源项目，感谢它们的作者：

### Everything SDK

- 作者：David Carpenter
- 许可证：MIT License
- 项目主页：https://www.voidtools.com/
- 源码位置：`library/Everything-SDK/`

> Copyright (C) 2016 David Carpenter
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

### TMSU

- 作者：oniony
- 许可证：GNU General Public License v3.0
- 项目主页：https://github.com/oniony/TMSU
- 源码位置：`library/tmsu/`
- 完整许可证文本：`library/tmsu/COPYING.md`

> TMSU is licensed under the GNU General Public License version 3.

## 许可证

由于本项目包含 TMSU（GPL v3）的组件，根据 GPL v3 的 copyleft 条款，**Faind 整体以 GNU General Public License v3.0 发布**。

详见 [LICENSE](LICENSE) 文件。