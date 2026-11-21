# -*- mode: python ; coding: utf-8 -*-
# Gera o executável com:  pyinstaller PianoVideo.spec
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("models", "models"), ("samples", "samples")]
binaries, hiddenimports = [], []
for pkg in ("piano_transcription_inference", "torchlibrosa", "librosa", "imageio_ffmpeg", "mido"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
hiddenimports += collect_submodules("pianovideo")

a = Analysis(["app/main.py"], pathex=["app"], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["torchvision", "torchaudio", "IPython", "jupyter"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PianoVideo",
          console=False, upx=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="PianoVideo", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="PianoVideo.app", bundle_identifier="com.pianovideo.app",
                 info_plist={"NSHighResolutionCapable": True})
