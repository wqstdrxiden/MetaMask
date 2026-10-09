#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

[ -f "tools_mac/ffmpeg" ]   || { echo "ОШИБКА: tools_mac/ffmpeg не найден"; exit 1; }
[ -f "tools_mac/ffprobe" ]  || { echo "ОШИБКА: tools_mac/ffprobe не найден"; exit 1; }
[ -f "tools_mac/exiftool" ] || { echo "ОШИБКА: tools_mac/exiftool не найден"; exit 1; }
[ -d "tools_mac/lib" ]      || { echo "ОШИБКА: tools_mac/lib не найден (exiftool нужен с lib/)"; exit 1; }

chmod +x tools_mac/ffmpeg tools_mac/ffprobe tools_mac/exiftool
chmod -R +r tools_mac

codesign --force --sign - tools_mac/ffmpeg   || true
codesign --force --sign - tools_mac/ffprobe  || true
codesign --force --sign - tools_mac/exiftool || true

rm -f tools_mac.zip
(cd tools_mac && zip -q -r ../tools_mac.zip .)
echo "ГОТОВО: tools_mac.zip ($(du -h tools_mac.zip | cut -f1))"