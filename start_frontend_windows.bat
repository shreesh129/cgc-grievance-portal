@echo off
cd /d "%~dp0frontend"
py -3 -m http.server 5500
