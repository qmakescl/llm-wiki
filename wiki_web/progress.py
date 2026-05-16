"""Ingest 작업 관리 — 버퍼링 + 재연결 지원 SSE.

IngestJob:
  - 모든 메시지를 self.messages 리스트에 누적
  - SSE stream()은 연결 시 누적 메시지부터 순차 전송 → 페이지 이동 후 재연결 가능
  - 복수 SSE 연결 동시 지원

JobStore (모듈 레벨):
  - create_job / get_job / list_jobs / cleanup_old_jobs
"""

from __future__ import annotations

import asyncio
import html
from collections.abc import AsyncGenerator
from datetime import datetime


class IngestJob:
    def __init__(
        self,
        job_id: str,
        filename: str,
        domain_name: str = "",
        slug: str = "",
    ) -> None:
        self.id = job_id
        self.filename = filename
        self.domain_name = domain_name
        self.slug = slug
        self.status = "running"          # running | done | failed
        self.messages: list[str] = []    # 누적 HTML 메시지
        self.started_at = datetime.now().strftime("%H:%M:%S")
        self._done = False
        self._loop = asyncio.get_running_loop()
        self._waiters: list[asyncio.Queue] = []

    # ── emit 메서드 (스레드에서 안전하게 호출) ──────────────────────────────

    def emit(self, message: str) -> None:
        safe = html.escape(message)
        self._push(f'<p class="log-step">▶ {safe}</p>')

    def emit_error(self, message: str) -> None:
        safe = html.escape(message)
        self._push(f'<p class="log-step log-error">✗ {safe}</p>')
        self.status = "failed"

    def complete(self) -> None:
        if self.status != "failed":
            self.status = "done"
        self._done = True
        self._notify(None)  # waiters에 종료 신호

    def _push(self, html_msg: str) -> None:
        self.messages.append(html_msg)
        self._notify(html_msg)

    def _notify(self, msg: str | None) -> None:
        for q in self._waiters:
            self._loop.call_soon_threadsafe(q.put_nowait, msg)

    # ── SSE 스트리밍 ─────────────────────────────────────────────────────────

    async def stream(self) -> AsyncGenerator[str, None]:
        """연결 시 누적 메시지 먼저 전송 후 실시간 메시지 전달 (재연결 안전)."""
        q: asyncio.Queue[str | None] = asyncio.Queue()
        self._waiters.append(q)
        offset = 0
        try:
            while True:
                # 누적된 미전송 메시지 모두 전송
                while offset < len(self.messages):
                    yield f"data: {self.messages[offset]}\n\n"
                    offset += 1

                if self._done:
                    return

                # 새 메시지 대기 (keepalive 포함)
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if msg is None:  # complete() 신호
                    # 마지막으로 남은 메시지 전송
                    while offset < len(self.messages):
                        yield f"data: {self.messages[offset]}\n\n"
                        offset += 1
                    return
                # 실제 메시지는 self.messages에 이미 추가됨 → 다음 루프에서 offset으로 처리
        finally:
            try:
                self._waiters.remove(q)
            except ValueError:
                pass


# ── 글로벌 Job Store ─────────────────────────────────────────────────────────

_store: dict[str, IngestJob] = {}


def create_job(
    job_id: str,
    filename: str,
    domain_name: str = "",
    slug: str = "",
) -> IngestJob:
    job = IngestJob(job_id, filename, domain_name, slug)
    _store[job_id] = job
    cleanup_old_jobs()
    return job


def get_job(job_id: str) -> IngestJob | None:
    return _store.get(job_id)


def list_jobs() -> list[IngestJob]:
    return list(_store.values())


def list_running_jobs() -> list[IngestJob]:
    return [j for j in _store.values() if j.status == "running"]


def clear_jobs_for_domain(domain_name: str) -> None:
    """Remove buffered ingest jobs for a domain after delete/re-init."""
    for job_id, job in list(_store.items()):
        if job.domain_name == domain_name:
            del _store[job_id]


def cleanup_old_jobs(max_done: int = 30) -> None:
    """완료/실패 작업 중 오래된 것을 최대 max_done개로 제한."""
    finished = [j for j in _store.values() if j.status in ("done", "failed")]
    for job in finished[:-max_done]:
        del _store[job.id]


# ── ProgressChannel (query 라우터용 경량 채널) ──────────────────────────────

class ProgressChannel:
    """query 라우터 전용 SSE 진행 채널 (answer_holder 없는 단순 버전)."""

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._done = False
        self._loop = asyncio.get_running_loop()
        self._waiters: list[asyncio.Queue] = []

    def emit(self, message: str) -> None:
        safe = html.escape(message)
        self._push(f'data: <p class="log-step">▶ {safe}</p>\n\n')

    def emit_error(self, message: str) -> None:
        safe = html.escape(message)
        self._push(f'data: <p class="log-step log-error">✗ {safe}</p>\n\n')

    def close(self) -> None:
        self._done = True
        for q in self._waiters:
            self._loop.call_soon_threadsafe(q.put_nowait, None)

    def _push(self, chunk: str) -> None:
        self._messages.append(chunk)
        for q in self._waiters:
            self._loop.call_soon_threadsafe(q.put_nowait, chunk)

    async def stream(self) -> AsyncGenerator[str, None]:
        """SSE 청크를 순서대로 yield."""
        q: asyncio.Queue[str | None] = asyncio.Queue()
        self._waiters.append(q)
        offset = 0
        try:
            while True:
                while offset < len(self._messages):
                    yield self._messages[offset]
                    offset += 1

                if self._done:
                    return

                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if msg is None:
                    while offset < len(self._messages):
                        yield self._messages[offset]
                        offset += 1
                    return
        finally:
            try:
                self._waiters.remove(q)
            except ValueError:
                pass
