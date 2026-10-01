"""允许 `python -m wxbot <子命令>`。"""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
