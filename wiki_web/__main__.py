"""python -m wiki_web 진입점."""

from __future__ import annotations

import logging
import webbrowser
import threading

import uvicorn

from wiki_web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _open_browser() -> None:
    import time
    time.sleep(1.5)
    webbrowser.open("http://localhost:8000")


def main() -> None:
    app = create_app()
    threading.Thread(target=_open_browser, daemon=True).start()
    print("=" * 50)
    print("  llm-wiki 웹 서버 시작")
    print("  브라우저: http://localhost:8000")
    print("  종료: Ctrl+C")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
