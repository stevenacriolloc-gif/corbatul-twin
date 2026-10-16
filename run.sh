#!/usr/bin/env bash
# Arranca el servidor y abre la app:  ./run.sh [puerto]
cd "$(dirname "$0")"
PORT="${1:-8765}"
python3 -m pip install -q -r requirements.txt
( sleep 2; (command -v open >/dev/null && open "http://localhost:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://localhost:$PORT") ) &
python3 -m corbatul.server --port "$PORT"
