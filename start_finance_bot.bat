@echo off
cd /d "%~dp0"
echo Starting finance agent bot...
python main.py --agent finance
pause
