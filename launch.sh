#!/bin/bash
# llm-wiki 원클릭 실행 스크립트 (macOS / Linux)
# 사용법: 이 파일을 더블클릭하거나 터미널에서 ./launch.sh 실행

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================"
echo "  llm-wiki 시작"
echo "================================================"

# Python 3.11+ 확인
if ! command -v python3 &> /dev/null; then
    echo "[오류] Python 3가 설치되지 않았습니다."
    echo "       https://www.python.org 에서 Python 3.11 이상을 설치하세요."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        osascript -e 'display alert "Python 3가 필요합니다. python.org에서 설치하세요." as critical' 2>/dev/null || true
    fi
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PYTHON_VERSION" -lt 11 ]; then
    echo "[오류] Python 3.11 이상이 필요합니다. (현재: 3.$PYTHON_VERSION)"
    exit 1
fi

# 가상환경 생성 및 패키지 설치 (최초 1회 또는 설치 실패 시 재시도)
if [ ! -d ".venv" ] || ! .venv/bin/python -c "import wiki_web, fastapi, uvicorn" 2>/dev/null; then
    echo "[설정] 첫 실행입니다. 가상환경을 설정합니다 (약 1~2분)..."
    # 이전 실패한 venv가 있으면 삭제 후 재생성
    rm -rf .venv
    python3 -m venv .venv
    echo "[설정] 패키지 설치 중..."
    .venv/bin/pip install --upgrade pip setuptools wheel -q
    .venv/bin/pip install -e . -q
    echo "[설정] 완료!"
fi

# 서버 시작
echo "[시작] 브라우저에서 http://localhost:8000 이 열립니다..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: 백그라운드 실행 후 브라우저 열기
    .venv/bin/python -m wiki_web &
    SERVER_PID=$!
    sleep 2
    open http://localhost:8000
    wait $SERVER_PID
else
    # Linux
    .venv/bin/python -m wiki_web &
    SERVER_PID=$!
    sleep 2
    xdg-open http://localhost:8000 2>/dev/null || true
    wait $SERVER_PID
fi
