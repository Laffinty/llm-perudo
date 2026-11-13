"""宿主启动入口（04 §1 / F-05）：本机单用户、绑定 localhost、无鉴权。

用法：uv run python scripts/run_host.py [--port 8900] [--data-root data]
前端构建产物（frontend/dist）存在时由宿主托管（04 §7）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from perudo.host.app import create_app

_DEFAULT_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="llm-perudo Web 宿主")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--dist-dir", type=Path, default=_DEFAULT_DIST)
    args = parser.parse_args(argv)

    app = create_app(args.data_root, dist_dir=args.dist_dir)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
