# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：wxbot → 单文件 exe（无控制台窗口）。

单文件（onefile）的好处是"发给别人就能双击跑"；代价是每次启动要解包到
%TEMP%，慢 1~2 秒。配置 / 聊天记忆 / 日志都写在 exe 旁边（见 config._app_dir），
所以升级 exe 不会丢用户数据。

构建：tools\build_exe.bat   或   .venv\Scripts\python -m PyInstaller wxbot.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH)

# RapidOCR 会把 onnxruntime 的一堆 dll 带进来；不显式收集会在别人机器上
# 报 "DLL load failed"。mss / windows_capture 是纯扩展模块 + ctypes。
binaries = []
for package in ("onnxruntime", "mss", "windows_capture", "pywintypes", "win32timezone"):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass

hiddenimports = []
for package in ("rapidocr_onnxruntime", "onnxruntime", "pywinauto", "pywintypes"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

hiddenimports += [
    "wxbot",
    "wxbot.wechat.input",
    "wxbot.wechat.capture",
    "wxbot.wechat.vision_client",
    "wxbot.tray",
    "win32con",
    "win32gui",
]

# RapidOCR 的模型权重（.onnx）不在源码目录里，在用户缓存下。
# 打包时把它们复制进临时目录再带进去，否则离线环境识别不了。
rapidocr_models = []
try:
    from rapidocr_onnxruntime import (
        DEFAULT_CFG_PATH,  # noqa: F401
    )

    import rapidocr_onnxruntime as _roc

    for root in (Path(_roc.__file__).parent,):
        for pattern in ("*.onnx", "*.txt", "*.yaml"):
            rapidocr_models += [(str(p), ".") for p in root.rglob(pattern)]
except Exception:
    pass

a = Analysis(
    # 用 app_entry 而不是 __main__：双击 exe 不带参数时它直接开图形界面，
    # 而 __main__ 走的 argparse 子命令是 required=True，会"缺参数"直接退出。
    [str(ROOT / "wxbot" / "app_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries + rapidocr_models,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="微信自动回复助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # ← 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # 用代码里画的图标，不依赖外部 .ico
)
