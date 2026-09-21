#!/usr/bin/env bash
# macOS / Linux 실행 스크립트:  bash run.sh
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/streamlit" ]; then
  echo "[1/2] 처음 실행입니다. 파이썬 환경을 준비합니다. 1~3분 걸립니다..."
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt --quiet
  # 3D 모델(메시) 기능용 선택 패키지. 실패해도 앱은 돌아간다.
  .venv/bin/python -m pip install -r requirements-mesh.txt --quiet || true
fi

echo "[2/2] 앱을 켭니다. 브라우저가 자동으로 열립니다."
echo "       주소: http://localhost:8501      종료: 이 창에서 Ctrl+C"
exec .venv/bin/streamlit run app.py
