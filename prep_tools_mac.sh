#!/bin/bash
# Готовит tools_mac.zip с macOS-бинарниками ffmpeg/ffprobe/exiftool.
# Положи рядом: ffmpeg и ffprobe (universal builds, например evermeet.cx) в tools_mac/
# и распакованный tarball exiftool (https://exiftool.org/Image-ExifTool-*.tar.gz) в exiftool_src/
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p tools_mac

# --- ffmpeg / ffprobe: просто положи бинарники в tools_mac/ ---
for t in ffmpeg ffprobe; do
  [ -f "tools_mac/$t" ] || { echo "ОШИБКА: положи macOS-бинарник в tools_mac/$t"; exit 1; }
done

# --- exiftool: собираем самодостаточный набор (perl-скрипт + либы) ---
if [ -d exiftool_src ]; then
  rm -rf tools_mac/exiftool_lib
  mkdir -p tools_mac/exiftool_lib
  cp exiftool_src/exiftool tools_mac/exiftool_lib/exiftool
  cp -R exiftool_src/lib/* tools_mac/exiftool_lib/
  cat > tools_mac/exiftool <<'WRAP'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec /usr/bin/perl -I "$DIR/exiftool_lib" "$DIR/exiftool_lib/exiftool" "$@"
WRAP
elif [ ! -f tools_mac/exiftool ]; then
  echo "ОШИБКА: нет exiftool_src/ (tarball с exiftool.org) и нет tools_mac/exiftool"
  exit 1
fi

chmod +x tools_mac/ffmpeg tools_mac/ffprobe tools_mac/exiftool
chmod -R +r tools_mac
# ad-hoc подпись, чтобы Gatekeeper не ругался на неподписанные бинарники
codesign --force --sign - tools_mac/ffmpeg  || true
codesign --force --sign - tools_mac/ffprobe || true
codesign --force --sign - tools_mac/exiftool || true

rm -f tools_mac.zip
(cd tools_mac && zip -q -r ../tools_mac.zip .)
echo "ГОТОВО: tools_mac.zip ($(du -h tools_mac.zip | cut -f1))"