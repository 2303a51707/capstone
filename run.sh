#!/usr/bin/env bash
# NyayaVoice - one-command setup and launch.
#
#   ./run.sh setup   /path/to/indian_ipc_statute_identification.csv
#   ./run.sh start
#   ./run.sh test
#
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
PORT=${PORT:-8000}

banner() { printf "\n\033[1;34m==> %s\033[0m\n" "$1"; }

case "${1:-start}" in

setup)
  CSV="${2:-}"
  if [ -z "$CSV" ] || [ ! -f "$CSV" ]; then
    echo "Usage: ./run.sh setup /path/to/indian_ipc_statute_identification.csv"
    exit 1
  fi

  banner "Creating virtual environment"
  [ -d .venv ] || "$PY" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate

  banner "Installing dependencies (this takes a few minutes)"
  pip install --upgrade pip -q
  pip install -r requirements.txt

  banner "Downloading Noto fonts for Indic PDF output"
  python scripts/fetch_fonts.py || echo "Font download failed - regional PDFs will be skipped until you re-run this."

  banner "Building the legal knowledge base from the dataset"
  python backend/ml/build_kb.py --csv "$CSV"

  banner "Training the statute-identification model (about 2 minutes)"
  python backend/ml/train.py --csv "$CSV"

  banner "Running the self-test"
  python scripts/selftest.py || true

  banner "Setup complete.  Start the app with:  ./run.sh start"
  ;;

start)
  [ -d .venv ] && source .venv/bin/activate
  if [ ! -f backend/data/legal_kb.json ]; then
    echo "The legal knowledge base is missing. Run:  ./run.sh setup <dataset.csv>"
    exit 1
  fi
  banner "NyayaVoice running at http://localhost:${PORT}   (API docs at /docs)"
  exec uvicorn backend.app:app --reload --port "$PORT"
  ;;

test)
  [ -d .venv ] && source .venv/bin/activate
  exec python scripts/selftest.py
  ;;

demo)
  [ -d .venv ] && source .venv/bin/activate
  exec python scripts/demo.py "${@:2}"
  ;;

*)
  echo "Usage: ./run.sh {setup <csv>|start|test|demo}"
  exit 1
  ;;
esac
