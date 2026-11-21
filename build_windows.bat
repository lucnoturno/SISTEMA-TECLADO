@echo off
REM Compila o PianoVideo e gera o instalador PianoVideo-Setup.exe
REM Requisitos: Python 3.12 (python.org) e Inno Setup 6 (jrsoftware.org)
cd /d "%~dp0"
py -3.12 -m venv .venv-win || python -m venv .venv-win
call .venv-win\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller || goto :erro
python download_assets.py || goto :erro
pyinstaller --noconfirm PianoVideo.spec || goto :erro
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer_windows.iss || goto :erro
echo.
echo Pronto! Instalador em: Output\PianoVideo-Setup.exe
pause
exit /b 0
:erro
echo Algo deu errado. Veja as mensagens acima.
pause
