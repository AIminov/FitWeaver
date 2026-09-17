@echo off
cd /d "%~dp0"
C:\Users\imino\.unsloth\studio\unsloth_studio\Scripts\python.exe docs\llm_finetune\finetune_simple.py --epochs 3 --batch-size 2
pause
