#!/bin/bash
# MetaMask US - сборка под macOS (Nuitka, standalone .app bundle)
# Запуск: ./build_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

VERSION=1.0.0
HTML=metadata_changer_ui_pywebview.html
APP_NAME="MetaMask US"

echo "=== MetaMask US: macOS build ==="

# --- окружение ---
if [ ! -d venv_mac ]; then python3 -m venv venv_mac; fi
source venv_mac/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q --upgrade nuitka ordered-set zstandard pywebview \
    pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-WebKit

# --- проверки ---
[ -f main.py ]       || { echo "ОШИБКА: main.py не найден"; exit 1; }
[ -f "$HTML" ]       || { echo "ОШИБКА: $HTML не найден"; exit 1; }
[ -f tools_mac.zip ] || { echo "ОШИБКА: tools_mac.zip не найден (сначала ./prep_tools_mac.sh)"; exit 1; }

# --- иконка: собираем .icns из logo.png, если ещё нет ---
if [ ! -f logo.icns ] && [ -f logo.png ]; then
  echo "Создаю logo.icns из logo.png..."
  rm -rf icon.iconset && mkdir -p icon.iconset
  sips -z 16 16     logo.png --out icon.iconset/icon_16x16.png      >/dev/null
  sips -z 32 32     logo.png --out icon.iconset/icon_16x16@2x.png   >/dev/null
  sips -z 32 32     logo.png --out icon.iconset/icon_32x32.png      >/dev/null
  sips -z 64 64     logo.png --out icon.iconset/icon_32x32@2x.png   >/dev/null
  sips -z 128 128   logo.png --out icon.iconset/icon_128x128.png    >/dev/null
  sips -z 256 256   logo.png --out icon.iconset/icon_128x128@2x.png >/dev/null
  sips -z 256 256   logo.png --out icon.iconset/icon_256x256.png    >/dev/null
  sips -z 512 512   logo.png --out icon.iconset/icon_256x256@2x.png >/dev/null
  sips -z 512 512   logo.png --out icon.iconset/icon_512x512.png    >/dev/null
  sips -z 1024 1024 logo.png --out icon.iconset/icon_512x512@2x.png >/dev/null
  iconutil -c icns icon.iconset -o logo.icns
  rm -rf icon.iconset
fi
ICON_FLAG=""
[ -f logo.icns ] && ICON_FLAG="--macos-app-icon=logo.icns"

# --- данные: html, tools (внутри бандла как tools.zip), шрифты, логотип ---
DATA_FLAGS="--include-data-files=$HTML=$HTML --include-data-files=tools_mac.zip=tools.zip"
for f in geometria-light geometria-medium geometria-bold geometria-extrabold \
         geometria-lightitalic geometria-mediumitalic geometria-bolditalic; do
  [ -f "$f.woff" ] && DATA_FLAGS="$DATA_FLAGS --include-data-files=$f.woff=$f.woff"
done
[ -f logo.png ] && DATA_FLAGS="$DATA_FLAGS --include-data-files=logo.png=logo.png"

# --- чистая сборка ---
rm -rf dist main.build

echo "=== Nuitka: standalone .app ==="
python -m nuitka \
  --standalone \
  --macos-create-app-bundle \
  --macos-app-name="$APP_NAME" \
  --macos-app-version="$VERSION" \
  $ICON_FLAG \
  $DATA_FLAGS \
  --output-filename=MetaMaskUS \
  --include-package-data=webview \
  --include-module=webview.platforms.cocoa \
  --include-package=objc \
  --include-package=PyObjCTools \
  --include-package=Cocoa \
  --include-package=AppKit \
  --include-package=Foundation \
  --include-package=CoreFoundation \
  --include-package=Quartz \
  --include-package=WebKit \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=PyQt5 \
  --nofollow-import-to=PyQt6 \
  --nofollow-import-to=PySide2 \
  --nofollow-import-to=PySide6 \
  --nofollow-import-to=matplotlib \
  --nofollow-import-to=numpy \
  --nofollow-import-to=pandas \
  --nofollow-import-to=scipy \
  --output-dir=dist \
  main.py

APP="$(ls -d dist/*.app | head -n1)"
if [ "$(basename "$APP")" != "$APP_NAME.app" ]; then
  mv "$APP" "dist/$APP_NAME.app"
  APP="dist/$APP_NAME.app"
fi

echo "=== Ad-hoc подпись ==="
codesign --force --deep --sign - "$APP"

echo
echo "ГОТОВО: $APP"
echo "Запуск GUI:  open \"$APP\""
echo "Запуск CLI:  \"$APP/Contents/MacOS/MetaMaskUS\" clean \"/путь/к/файлу.mp4\""
echo "Если macOS блокирует: xattr -cr \"$APP\""