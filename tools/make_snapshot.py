"""打交付快照：把源码打成 zip，排除虚拟环境 / 日志 / 数据 / 备份。

用法：.venv/Scripts/python.exe tools/make_snapshot.py 2.3.1

默认输出到项目父目录：wechat-assistant-v<版本>-snapshot.zip
排除：.venv / logs / __pycache__ / data / .git / config.toml.bak / *.pyc
（data 与 config.toml 不入快照：前者是聊天记忆等隐私数据，后者含本机配置）
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

SKIP_DIRS = {".venv", "logs", "__pycache__", "data", ".git", ".idea", ".pytest_cache"}
SKIP_FILES = {"config.toml.bak", "secrets.toml", ".env"}


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else None
    project = Path(__file__).resolve().parents[1]
    if not version:
        sys.path.insert(0, str(project))
        from wxbot import __version__ as version

    out = project.parent / f"wechat-assistant-v{version}-snapshot.zip"

    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(project.rglob("*")):
            rel = path.relative_to(project)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if path.is_dir() or path.name in SKIP_FILES or path.suffix == ".pyc":
                continue
            zf.write(path, Path(project.name) / rel)
            count += 1

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"已打包 {count} 个文件 -> {out}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
