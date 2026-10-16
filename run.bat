@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
start "" "http://localhost:8765"
python -m corbatul.server --port 8765
