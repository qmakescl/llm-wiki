"""마크다운 렌더링 공통 유틸리티."""

from __future__ import annotations

import re
import markdown as md_lib


# ── 위키링크 SVG 아이콘 ──────────────────────────────────────────────────────

_LINK_SVG = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'style="margin-right:2px; margin-bottom:1px">'
    '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>'
    '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>'
    '</svg>'
)

_TAG_SVG = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'style="margin-right:2px; margin-bottom:1px">'
    '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>'
    '<line x1="7" y1="7" x2="7.01" y2="7"></line>'
    '</svg>'
)


def _replace_wikilink(match: re.Match) -> str:
    """[[...]] 형태의 위키링크를 분류하여 HTML span으로 변환.

    - [[파일명.md]] → 출처(source) 버튼  (파일 확장자 .md 포함)
    - [[Entity Name]]  → 엔티티(entity) 태그  (공백·PascalCase·한글 등)
    """
    name = match.group(1)

    if name.endswith(".md"):
        # 출처 링크: 파일명에서 .md 제거하여 툴팁 표시
        label = name[:-3]
        return (
            f'<span class="wiki-source-btn" data-tooltip="{label}">'
            f'{_LINK_SVG}출처'
            f'</span>'
        )
    else:
        # 엔티티 링크: 이름 그대로 표시
        return (
            f'<span class="wiki-entity-tag" data-tooltip="wiki entity: {name}">'
            f'{_TAG_SVG}{name}'
            f'</span>'
        )


def _preprocess_md(raw: str) -> str:
    """LLM 출력의 마크다운 구조 문제를 전처리.

    Python markdown 라이브러리는 단락 바로 뒤에 리스트가 오면
    전체를 하나의 <p> 로 묶어버립니다.
    볼드 단락(**텍스트**) 이후 리스트(*/-) 사이에 빈 줄을 삽입해
    올바른 <ul>/<ol> 렌더링을 보장합니다.
    """
    # 패턴: 비어있지 않은 줄 끝 바로 다음 줄이 * 또는 - 로 시작하는 리스트
    # 단, 앞 줄이 이미 빈 줄이거나 리스트 항목이면 삽입하지 않음
    lines = raw.splitlines()
    result = []
    for i, line in enumerate(lines):
        result.append(line)
        if i < len(lines) - 1:
            next_line = lines[i + 1]
            # 다음 줄이 리스트 항목이고
            is_next_list = re.match(r'^(\s*)[*\-]\s+', next_line)
            # 현재 줄이 비어있지 않고 리스트 항목도 아니면
            is_cur_nonempty = line.strip() != ''
            is_cur_not_list = not re.match(r'^(\s*)[*\-]\s+', line)
            if is_next_list and is_cur_nonempty and is_cur_not_list:
                result.append('')  # 빈 줄 삽입
    return '\n'.join(result)


def render_answer(raw: str) -> str:
    """마크다운 원문을 HTML로 렌더링하고 위키링크를 변환."""
    preprocessed = _preprocess_md(raw)
    html = md_lib.markdown(preprocessed, extensions=["extra", "toc"])
    html = re.sub(r"\[\[([^\]]+)\]\]", _replace_wikilink, html)
    return html
