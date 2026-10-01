"""探查微信本地消息数据库是否可直接读取（只读，不解密、不修改）。

用法：.venv/Scripts/python.exe tools/probe_local_db.py

会做：
1) 列出账号目录下的 db_storage 结构与各库大小；
2) 判断每个库是否加密（文件头是否为 'SQLite format 3'）；
3) 对未加密的库尝试列出表结构与最近消息（只读连接）。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

DOCS = Path.home() / "Documents" / "xwechat_files"
SQLITE_MAGIC = b"SQLite format 3\x00"


def find_accounts() -> list[Path]:
    if not DOCS.exists():
        return []
    return sorted(p for p in DOCS.glob("wxid_*") if p.is_dir())


def inspect_db(path: Path) -> dict:
    info = {"path": path, "size_mb": path.stat().st_size / 1024 / 1024}
    try:
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError as exc:
        info["error"] = str(exc)
        return info
    info["encrypted"] = head != SQLITE_MAGIC
    if not info["encrypted"]:
        try:
            uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
            con = sqlite3.connect(uri, uri=True, timeout=3)
            cur = con.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' LIMIT 12"
            )
            info["tables"] = [row[0] for row in cur.fetchall()]
            con.close()
        except Exception as exc:  # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def main() -> int:
    accounts = find_accounts()
    if not accounts:
        print(f"没有找到账号目录：{DOCS}")
        return 2

    for account in accounts:
        storage = account / "db_storage"
        print("=" * 72)
        print(f"账号目录: {account.name}")
        if not storage.exists():
            print("  （无 db_storage）")
            continue
        dbs = sorted(storage.rglob("*.db"), key=lambda p: -p.stat().st_size)
        print(f"  数据库 {len(dbs)} 个：")
        for db in dbs[:12]:
            info = inspect_db(db)
            state = "🔒 已加密" if info.get("encrypted") else "✅ 可直接读"
            line = f"    {state}  {db.relative_to(storage)!s:<34} {info['size_mb']:6.1f} MB"
            if info.get("tables"):
                line += f"  表: {', '.join(info['tables'][:5])}"
            if info.get("error"):
                line += f"  [{info['error'][:40]}]"
            print(line)

    print()
    print("说明：微信 4.x 的聊天库使用 SQLCipher 加密，直接用 sqlite 读不了；")
    print("      密钥在微信进程内存中，需要从内存提取（属于进程读取，风险与本项目定位不同）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
