#!/usr/bin/env bash
# 기업 재무분석 도구 — macOS / Linux 실행 런처
# 가상환경 생성 + 패키지 설치 + 실행을 자동으로 진행합니다.
#   실행: chmod +x run.sh && ./run.sh
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo "Python 3가 필요합니다. 먼저 설치해 주세요 (https://www.python.org)."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[설정] 가상환경 생성 및 패키지 설치 중... 처음 한 번만 걸립니다."
    "$PY" -m venv .venv
    # shellcheck disable=SC1091
    source .venv/bin/activate
    python -m pip install --upgrade pip >/dev/null
    pip install -r requirements.txt
else
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

echo "[실행] 기업 재무분석 도구를 시작합니다..."
python dart_gui.py
