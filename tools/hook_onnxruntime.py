"""PyInstaller runtime hook：让 onnxruntime 在冻结后的 exe 里能正常加载。

为什么需要：onnxruntime 的 `capi/` 目录里有 `onnxruntime.dll` /
`onnxruntime_pybind11_state.pyd`，而 pyd 加载 DLL 时只搜**它自己所在目录**
和系统 PATH。源码运行时它就在 site-packages 里，自然能找到；
冻结后这些文件被散落到 bundle 的各个子目录，`import onnxruntime` 就会
以 "DLL load failed" 失败 —— 表现为界面上那句
「OCR 引擎不可用（请确认已安装 rapidocr-onnxruntime）」。

这里在 Python 启动**之前**把相关目录都加进 DLL 搜索路径。
"""

import os
import sys

_base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
_dirs = [
    _base,
    os.path.join(_base, "onnxruntime", "capi"),
    os.path.join(_base, "lib"),
    os.path.join(_base, "Library", "bin"),
]
for _d in _dirs:
    if os.path.isdir(_d):
        try:
            os.add_dll_directory(_d)
        except (AttributeError, OSError):
            pass
        if _d not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")
