#!/bin/bash
# Compila o PianoVideo no macOS. Precisa do Python 3.12 instalado (python.org).
cd "$(dirname "$0")"
python3.12 -m venv .venv-mac || exit 1
source .venv-mac/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python download_assets.py
pyinstaller --noconfirm PianoVideo.spec && bash make_dmg.sh
echo "Pronto! Instalador em Output/PianoVideo-Mac.dmg"
