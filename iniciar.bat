@echo off
title Financiera - Sistema de Gastos Fijos
echo.
echo ========================================
echo   SISTEMA FINANCIERO - GASTOS FIJOS
echo ========================================
echo.
echo Iniciando servidor...
echo Abra en el navegador: http://localhost:5050
echo.
echo Para detener: presione Ctrl+C
echo ----------------------------------------
echo.
cd /d %~dp0
call venv\Scripts\activate
python run.py
pause
