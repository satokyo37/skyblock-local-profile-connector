@echo off
chcp 65001 >nul
cd /d "%~dp0"
py skyblock_connector.py setup-key
pause

