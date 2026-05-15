"""Obsidian remotely-save 동기화 트리거.

ingest/query --save 완료 후 Obsidian CLI로 remotely-save 동기화를 시작합니다.
환경변수 WIKI_OBSIDIAN_SYNC=off 로 비활성화할 수 있습니다.
Obsidian이 실행 중이지 않으면 경고만 출력하고 계속 진행합니다.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_PLUGIN_ID = "remotely-save:start-sync"


def _sync_enabled() -> bool:
    val = os.environ.get("WIKI_OBSIDIAN_SYNC", "on").strip().lower()
    return val not in ("0", "false", "no", "off")


def trigger_sync(wiki_root: Path) -> None:
    """wiki_root 경로에서 vault 이름을 추론해 remotely-save 동기화를 트리거한다.

    wiki_root 구조: ws_root/wiki/{domain_folder}
    Obsidian vault = ws_root/wiki/ → vault name = "wiki"

    비동기(fire-and-forget): 동기화 완료를 기다리지 않는다.
    실패해도 ingest/query 흐름에 영향을 주지 않는다.
    """
    if not _sync_enabled():
        logger.debug("WIKI_OBSIDIAN_SYNC=off — 동기화 건너뜀")
        return

    # ws_root/wiki/{folder} 구조에서 vault 이름은 부모의 이름("wiki")
    vault_name = wiki_root.parent.name

    try:
        subprocess.Popen(
            ["obsidian", f"vault={vault_name}", f"command", f"id={_PLUGIN_ID}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Obsidian remotely-save 동기화 트리거됨 (vault=%s)", vault_name)
    except FileNotFoundError:
        logger.warning("obsidian CLI를 찾을 수 없습니다 — 동기화 건너뜀")
    except Exception as exc:
        logger.warning("Obsidian 동기화 트리거 실패: %s", exc)
