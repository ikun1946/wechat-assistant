"""一次性修掉 tests/*.py 与 wxbot/*.py 里被 PowerShell 写进去的 UTF-8 BOM。

PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会写 BOM，
Python 读源码时会直接 SyntaxError / 识别失败。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"

fixed = []
for path in list(ROOT.glob("tests/*.py")) + list(ROOT.glob("wxbot/**/*.py")):
    raw = path.read_bytes()
    if raw.startswith(BOM):
        path.write_bytes(raw[len(BOM):])
        fixed.append(str(path.relative_to(ROOT)))

if fixed:
    print("已去掉 BOM：")
    for name in fixed:
        print("  " + name)
else:
    print("没有文件带 BOM")
