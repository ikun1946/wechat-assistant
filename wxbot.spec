# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：wxbot → 单文件 exe（无控制台窗口）。

单文件（onefile）的好处是"发给别人就能双击跑"；代价是每次启动要解包到
%TEMP%，慢 1~2 秒。配置 / 聊天记忆 / 日志都写在 exe 旁边（见 config._app_dir），
所以升级 exe 不会丢用户数据。

构建：tools\build_exe.bat   或   .venv\Scripts\python -m PyInstaller wxbot.spec --noconfirm
"""

import os
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

# onnxruntime 的原生扩展：把 DLL **额外**放到 bundle 根目录（"."）。
# 只放在 onnxruntime/capi/ 子目录里的话，冻结后的 exe 常常
# "DLL load failed"（pyd 加载 DLL 只搜自己所在目录）。
# 再配合 tools/hook_onnxruntime.py 补 DLL 搜索路径，双保险。
_ort_capi = Path(sys.prefix) / "Lib" / "site-packages" / "onnxruntime" / "capi"
if _ort_capi.is_dir():
    for _f in _ort_capi.glob("*"):
        if _f.suffix.lower() in (".dll", ".pyd"):
            binaries.append((str(_f), "."))
    for _root, _dirs, _files in os.walk(_ort_capi):
        for _name in _files:
            if _name.lower().endswith((".dll", ".pyd")):
                _p = Path(_root) / _name
                binaries.append((str(_p), os.path.relpath(_p.parent, _ort_capi).replace("\\", ".")))

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

# RapidOCR 自带的数据文件：config.yaml + 三个 .onnx 模型（约 15MB）。
# ⚠ 两个要点，都是实测踩出来的：
#  1) 目标目录必须是 **rapidocr_onnxruntime**（包自己的目录），不是 "."。
#     它按包内相对路径读 `os.path.join(__file__.parent, "config.yaml")`，
#     放错地方就是 FileNotFoundError（表现为界面只说"OCR 引擎不可用"）。
#  2) **只能在这里加一次**。早先同一个文件既在 binaries 又在 datas 里各加了一遍
#     （一个放 "."、一个放包目录），PyInstaller 去重时留下的是 "." 那份，
#     结果 config.yaml 到位、.onnx 却没进包目录 —— 半对半错更难查。
rapidocr_datas = []
try:
    import rapidocr_onnxruntime as _roc

    _pkg_dir = Path(_roc.__file__).parent
    for _pattern in ("*.onnx", "*.txt", "*.yaml", "*.yml"):
        for _p in _pkg_dir.rglob(_pattern):
            # ⚠ dest 是**相对 bundle 根目录（_internal）**的，不是相对包目录 ——
            # 少写包名前缀，文件就会落到 _internal\models\ 而不是
            # _internal\rapidocr_onnxruntime\models\，报的错是
            # "...\rapidocr_onnxruntime\models\xxx.onnx does not exists."
            _rel = _p.relative_to(_pkg_dir).parent.as_posix()
            _dest = "rapidocr_onnxruntime" if _rel == "." else f"rapidocr_onnxruntime/{_rel}"
            rapidocr_datas.append((str(_p), _dest))
except Exception:
    pass

a = Analysis(
    # 用 app_entry 而不是 __main__：双击 exe 不带参数时它直接开图形界面，
    # 而 __main__ 走的 argparse 子命令是 required=True，会"缺参数"直接退出。
    [str(ROOT / "wxbot" / "app_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=rapidocr_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "tools" / "hook_onnxruntime.py")],
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ---- 目录版（onedir），不是单文件 ----
# 单文件（onefile）每次启动都要把整个包解到 %TEMP%，带来两个实际问题：
#   1. 启动慢 1~2 秒；
#   2. **onnxruntime 的 DLL 层级会被打散** —— `onnxruntime.dll` 与
#      `onnxruntime_pybind11_state.pyd` 找不到彼此，import 直接 "DLL load failed"，
#      界面上只显示「OCR 引擎不可用」。
# 目录版保持原有包结构，依赖加载正常，启动也快。代价是分发时是整个文件夹（可以压缩）。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,     # ← onedir：二进制交给下面的 COLLECT
    name="微信自动回复助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,              # ← 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                  # 用代码里画的图标，不依赖外部 .ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="微信自动回复助手",
)
