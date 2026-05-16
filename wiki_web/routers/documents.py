"""문서 관리 라우터 — 파일 목록, 업로드, Ingest SSE 스트리밍.

Ingest 작업은 asyncio Task로 실행되어 페이지를 이동해도 서버에서 계속 진행됩니다.
재접속 시 /documents/ingest/{job_id}/stream 으로 누적 로그를 이어받을 수 있습니다.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_web import progress as jobs
from wiki_cli import fs, source_registry
from wiki_cli.ops.ingest import run_ingest, DuplicateSourceError

router = APIRouter(prefix="/documents")


def _raw_files(wiki_root: Path, data_root: Path) -> list[dict]:
    """raw/ 하위 모든 파일 정보를 반환."""
    raw = fs.raw_dir(data_root)
    if not raw.exists():
        return []
    files = []
    for f in sorted(raw.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            slug = fs.file_slug(f.stem)
            record = source_registry.find_record_for_source(data_root, f)
            ingested = bool(record and source_registry.record_is_complete(record, wiki_root))
            partial = (wiki_root / "sources" / f"{slug}.md").exists() and not ingested
            files.append({
                "path": f,
                "name": f.name,
                "rel": str(f.relative_to(raw)),
                "size": _fmt_size(f.stat().st_size),
                "slug": slug,
                "ingested": ingested,
                "partial": partial,
            })
    return files


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def _running_jobs_for_domain(domain_name: str) -> list[jobs.IngestJob]:
    return [j for j in jobs.list_jobs() if j.domain_name == domain_name and j.status == "running"]


@router.get("", response_class=HTMLResponse)
async def documents_page(request: Request):
    wiki_root = cfg.get_wiki_root()
    data_root = cfg.get_data_root()
    domain = cfg.get_active_domain() or {}
    domain_name = domain.get("name", "")
    running = _running_jobs_for_domain(domain_name)
    return templates.TemplateResponse(
        request,
        "documents.html",
        {
            "files": _raw_files(wiki_root, data_root),
            "wiki_root": str(wiki_root),
            "running_jobs": running,
        },
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_file(files: list[UploadFile] = File(...)):
    wiki_root = cfg.get_wiki_root()
    data_root = cfg.get_data_root()
    raw = fs.raw_dir(data_root)
    raw.mkdir(parents=True, exist_ok=True)

    rows_html = []
    for file in files:
        try:
            dest = fs.resolve_upload_path(raw, file.filename or "")
        except fs.UnsafeUploadError as e:
            rows_html.append(
                f'<p class="log-error">업로드 거부 ({file.filename!r}): {e}</p>'
            )
            continue

        content = await file.read()
        dest.write_bytes(content)
        source_registry.register_uploaded_source(data_root, dest)

        slug = fs.file_slug(dest.stem)
        record = source_registry.find_record_for_source(data_root, dest)
        ingested = bool(record and source_registry.record_is_complete(record, wiki_root))
        partial = (wiki_root / "sources" / f"{slug}.md").exists() and not ingested
        file_info = {
            "path": dest,
            "name": dest.name,
            "rel": dest.name,
            "size": _fmt_size(len(content)),
            "slug": slug,
            "ingested": ingested,
            "partial": partial,
        }
        rows_html.append(
            templates.env.get_template("partials/file_row.html").render({"f": file_info})
        )

    return HTMLResponse("".join(rows_html))


@router.post("/ingest/{slug}", response_class=HTMLResponse)
async def start_ingest(request: Request, slug: str):
    """Ingest 작업 시작 — SSE 리스너 HTML 즉시 반환. 페이지 이동 후에도 작업 계속."""
    wiki_root = cfg.get_wiki_root()
    data_root = cfg.get_data_root()
    domain = cfg.get_active_domain() or {}
    domain_name = domain.get("name", "")

    source = _find_source(data_root, slug)
    if source is None:
        return HTMLResponse(
            f'<p class="log-error">파일을 찾을 수 없습니다: {slug}</p>',
            status_code=404,
        )

    job_id = str(uuid.uuid4())[:8]
    job = jobs.create_job(job_id, source.name, domain_name)

    settings = cfg.load()
    model = settings.get("model") or None

    async def _run() -> None:
        try:
            await asyncio.to_thread(run_ingest, wiki_root, source, model, job.emit, data_root)
            job.emit(f"✓ Ingest 완료: {source.name}")
        except DuplicateSourceError as e:
            job.emit_error(str(e))
        except Exception as e:
            job.emit_error(f"오류: {e}")
        finally:
            job.complete()

    asyncio.create_task(_run())

    return templates.TemplateResponse(
        request,
        "partials/ingest_progress.html",
        {"job_id": job_id, "filename": source.name},
    )


@router.get("/ingest/{job_id}/stream")
async def ingest_stream(job_id: str):
    """SSE 스트리밍 — 재연결 시 누적 로그부터 이어받음."""
    job = jobs.get_job(job_id)
    if job is None:
        return HTMLResponse("job not found", status_code=404)

    async def event_stream():
        async for chunk in job.stream():
            yield chunk
        done_class = "ingest-ok" if job.status == "done" else "ingest-err"
        done_text = "완료 ✓" if job.status == "done" else "실패 ✗"
        yield f"event: done\ndata: <span class='{done_class}'>{done_text}</span>\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_panel(request: Request):
    """실행 중 및 최근 완료 작업 목록 (폴링용 HTML 프래그먼트)."""
    domain = cfg.get_active_domain() or {}
    domain_name = domain.get("name", "")
    all_jobs = [j for j in jobs.list_jobs() if j.domain_name == domain_name]
    # 최신 20개만 역순으로
    recent = list(reversed(all_jobs))[:20]
    return templates.TemplateResponse(
        request,
        "partials/jobs_panel.html",
        {"jobs": recent},
    )


def _find_source(data_root: Path, slug: str) -> Path | None:
    raw = fs.raw_dir(data_root)
    for f in raw.rglob("*"):
        if f.is_file() and fs.file_slug(f.stem) == slug:
            return f
    return None
