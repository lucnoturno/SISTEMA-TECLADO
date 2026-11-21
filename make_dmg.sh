#!/bin/bash
# Empacota dist/PianoVideo.app em Output/PianoVideo-Mac.dmg (arrastar para Aplicativos)
set -e
cd "$(dirname "$0")"
STAGE=$(mktemp -d)
ditto --norsrc --noextattr --noacl dist/PianoVideo.app "$STAGE/PianoVideo.app"
codesign --force --deep -s - "$STAGE/PianoVideo.app"
ln -s /Applications "$STAGE/Aplicativos"
mkdir -p Output && rm -rf Output/dmg Output/PianoVideo-Mac.dmg
hdiutil create -volname PianoVideo -srcfolder "$STAGE" -ov -format UDZO Output/PianoVideo-Mac.dmg
rm -rf "$STAGE"
echo "Instalador: Output/PianoVideo-Mac.dmg"
