@echo off
cd /d "%~dp0"
echo Starting Ops Agent bot...
python main.py --agent ops
pause
