@echo off
cd /d "%~dp0"
echo Starting Image Tagger (Web) ...
echo Browser will open automatically at http://127.0.0.1:8000
python server.py
pause
