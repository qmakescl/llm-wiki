"""질문 답변 라우터 — SSE 진행상황 + 마크다운 답변 렌더링."""

from __future__ import annotations

import asyncio
import html as html_module
import uuid

import markdown as md_lib
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_web.progress import ProgressChannel
from wiki_web.render import render_answer
from wiki_cli import fs
from wiki_cli.ops.query import run_query, _save_synthesis

router = APIRouter(prefix="/query")

_jobs: dict[str, tuple[ProgressChannel, asyncio.Task, list[str]]] = {}


@router.get("", response_class=HTMLResponse)
async def query_page(request: Request):
    return templates.TemplateResponse(request, "query.html", {})


@router.post("", response_class=HTMLResponse)
async def submit_query(request: Request, question: str = Form(...), save: bool = Form(False)):
    """질문 제출 — SSE 리스너 HTML 반환."""
    job_id = str(uuid.uuid4())[:8]
    channel = ProgressChannel()

    settings = cfg.load()
    root = cfg.get_wiki_root()
    model = settings.get("model") or None

    answer_holder: list[str] = []

    async def _run() -> None:
        try:
            answer = await asyncio.to_thread(
                run_query,
                root,
                question,
                model,
                save,
                channel.emit,
            )
            answer_holder.append(answer)
        except Exception as e:
            channel.emit_error(f"오류: {e}")
            answer_holder.append("")
        finally:
            channel.close()

    task = asyncio.create_task(_run())
    _jobs[job_id] = (channel, task, answer_holder)

    return templates.TemplateResponse(
        request,
        "partials/query_progress.html",
        {"job_id": job_id, "question": question, "save": save},
    )


@router.get("/{job_id}/stream")
async def query_stream(request: Request, job_id: str, question: str = "", save: bool = False):
    """SSE 스트리밍 — 진행 메시지 + 최종 답변."""
    entry = _jobs.get(job_id)
    if entry is None:
        return HTMLResponse("job not found", status_code=404)

    channel, task, answer_holder = entry

    async def event_stream():
        # progress 이벤트 스트리밍
        async for chunk in channel.stream():
            yield chunk

        # task 완료 대기
        await task

        import re
        raw_answer = answer_holder[0] if answer_holder else ""
        if raw_answer:
            answer_html = render_answer(raw_answer)
        else:
            answer_html = '<p class="error">답변을 생성할 수 없습니다.</p>'

        # query_result.html 템플릿 렌더링 후 done 이벤트로 전송
        result_html = templates.get_template("partials/query_result.html").render(
            {
                "request": request,
                "question": question,
                "answer_html": answer_html,
                "raw_answer": raw_answer,
                "steps": [],
                "save": save,
            }
        )
        lines = result_html.splitlines(keepends=False)
        sse_data = "\ndata: ".join(lines)
        yield f"event: done\ndata: {sse_data}\n\n"

        _jobs.pop(job_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )



@router.post("/save", response_class=HTMLResponse)
async def save_answer(
    request: Request,
    question: str = Form(...),
    raw_answer: str = Form(...),
):
    """이미 생성된 답변을 LLM 재호출 없이 synthesis/ 에 저장."""
    root = cfg.get_wiki_root()
    try:
        saved_path = await asyncio.to_thread(_save_synthesis, root, question, raw_answer)
        # 저장 완료 후 결과 카드를 '저장됨' 상태로 다시 렌더링
        answer_html = render_answer(raw_answer)
        return templates.TemplateResponse(
            request,
            "partials/query_result.html",
            {
                "question": question,
                "answer_html": answer_html,
                "raw_answer": raw_answer,
                "steps": [],
                "save": True,  # 저장 완료 상태
            },
        )
    except Exception as e:
        return HTMLResponse(
            f'<p class="error">저장 실패: {html_module.escape(str(e))}</p>',
            status_code=500,
        )


@router.post("/ask", response_class=HTMLResponse)
async def ask_sync(request: Request, question: str = Form(...), save: bool = Form(False)):
    """동기식 질문 답변 — 스트리밍 없이 결과 반환 (간단한 UX용)."""
    root = cfg.get_wiki_root()
    settings = cfg.load()
    model = settings.get("model") or None

    steps: list[str] = []
    raw_answer = ""

    try:
        raw_answer = await asyncio.to_thread(
            run_query,
            root,
            question,
            model,
            save,
            steps.append,
        )
        answer_html = render_answer(raw_answer)
    except Exception as e:
        answer_html = f'<p class="error">오류: {html_module.escape(str(e))}</p>'
        steps = []

    return templates.TemplateResponse(
        request,
        "partials/query_result.html",
        {
            "question": question,
            "answer_html": answer_html,
            "raw_answer": raw_answer,
            "steps": steps,
            "save": save,
        },
    )
