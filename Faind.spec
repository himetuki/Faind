# -*- mode: python ; coding: utf-8 -*-
"""
Faind PyInstaller 打包配置 - 单文件模式
使用方法: pyinstaller Faind.spec
输出: dist/Faind.exe（单文件，包含所有依赖）
"""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)


def _try_import_certifi():
    """尝试获取 certifi 证书路径，用于 SSL 验证"""
    try:
        import certifi
        cacert = Path(certifi.__file__).parent / 'cacert.pem'
        if cacert.exists():
            return True
    except ImportError:
        pass
    return False


# 过滤 datas 中的 None（certifi 未安装时）
CERTIFI_DATAS = []
if _try_import_certifi():
    import certifi as _certifi
    CERTIFI_DATAS = [(str(Path(_certifi.__file__).parent / 'cacert.pem'), 'certifi')]


def _collect_library_datas():
    """收集 library/ 下的 datas，缺少的目录自动跳过（CI 环境容错）。"""
    datas = []

    # fd 搜索后端（可选，CI 环境/用户本地可能未下载）
    fd_path = ROOT / 'library' / 'fd'
    if fd_path.exists():
        datas.append((str(fd_path), 'library/fd'))

    # Everything SDK DLL（运行时必需）
    dll_path = ROOT / 'library' / 'Everything-SDK' / 'dll' / 'Everything64.dll'
    if dll_path.exists():
        datas.append((str(dll_path), 'library/Everything-SDK/dll'))

    # ES CLI（DLL降级备用）
    es_path = ROOT / 'library' / 'ES-1.1.0.30.x64'
    if es_path.exists():
        datas.append((str(es_path), 'library/ES-1.1.0.30.x64'))

    # 内嵌 Everything 便携版
    everything_path = ROOT / 'library' / 'Everything'
    if everything_path.exists():
        datas.append((str(everything_path), 'library/Everything'))

    return datas


a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=_collect_library_datas() + CERTIFI_DATAS,
    hiddenimports=[
        'PySide6',
        'qfluentwidgets',
        'openai',
        'requests',
        'dotenv',
        'sqlite3',
        # openai 依赖链（PyInstaller 静态分析可能遗漏）
        'httpx',
        'httpcore',
        'h11',
        'certifi',
        'pydantic',
        'pydantic_core',
        'tqdm',
        'anyio',
        'sniffio',
        'annotated_types',
        # pyxtxt 文档读取（try/except 中动态导入）
        'pyxtxt',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除不需要的大型包，大幅减小打包体积
    excludes=[
        # 科学计算（Faind不需要）
        'numpy', 'pandas', 'scipy', 'matplotlib', 'numba', 'llvmlite',
        # 深度学习（Faind不需要）
        'torch', 'tensorflow', 'keras', 'onnx',
        # 其他 Qt 绑定（仅需 PySide6）
        'PyQt5', 'PyQt6', 'PySide2', 'qtpy',
        # 图像处理（Faind不需要）
        'PIL', 'Pillow', 'opencv', 'cv2',
        # Web/爬虫（Faind不需要）
        'selenium', 'playwright', 'lxml', 'bs4', 'beautifulsoup4',
        # 其他大型包
        'jinja2', 'pygments', 'IPython', 'jupyter', 'notebook',
        'pytest', 'py', 'openpyxl', 'xlrd', 'xlsxwriter',
        'fsspec', 'pyarrow', 'tables', 'h5py',
        # 不需要的标准库
        'tkinter.test', 'unittest', 'pydoc', 'doctest',
        'http.server', 'xmlrpc', 'py_compile', 'compileall',
        'pip', 'setuptools',
        # Win32 COM（Faind不需要）
        'win32com', 'pythoncom', 'pywintypes',
        # 其他（anyio/sniffio/httptools 是 openai→httpx 的必需依赖，不能排除）
        'tensorboard', 'networkx', 'sympy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Faind',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可添加 .ico 图标文件
)