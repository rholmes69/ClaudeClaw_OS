@echo off
cd /d "%~dp0"
echo Starting Content Agent bot...
python main.py --agent content
pause
