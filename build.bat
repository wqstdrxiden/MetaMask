@echo off
setlocal
rem ------------------------------------------------------------------
rem  MetaMask US - Nuitka build script (Windows)
rem    build.bat test : standalone folder WITH console (debug)
rem    build.bat      : release, single MetaMaskUS.exe with persistent cache
rem  Keep next to main.py, the HTML file, the tools\ folder, logo and fonts.
rem  Keep VERSION here equal to VERSION in main.py.
rem ------------------------------------------------------------------
set VERSION=1.0.0
set HTML=metadata_changer_ui_pywebview.html
set EXE=MetaMaskUS.exe
if not exist venv (
echo Creating virtual environment...
python -m venv venv || goto :fail
)
call venv\Scripts\activate.bat || goto :fail
python -m pip install -q --upgrade pip || goto :fail
python -m pip install -q --upgrade nuitka ordered-set zstandard pywebview pythonnet || goto :fail
rem --- input checks ---------------------------------------------------
if not exist main.py            (echo ERROR: main.py not found & goto :fail)
if not exist %HTML%             (echo ERROR: %HTML% not found & goto :fail)
if not exist tools\ffmpeg.exe   (echo ERROR: tools\ffmpeg.exe not found & goto :fail)
if not exist tools\ffprobe.exe  (echo ERROR: tools\ffprobe.exe not found & goto :fail)
if not exist tools\exiftool.exe (echo ERROR: tools\exiftool.exe not found & goto :fail)
findstr /c:"def ensure_tools" main.py >nul || (echo ERROR: main.py has no ensure_tools^(^) - add it first & goto :fail)
rem --- logo flags (optional, applied only if files exist) -------------
set ICON_FLAG=
if exist logo.ico set "ICON_FLAG=--windows-icon-from-ico=logo.ico"
set LOGO_DATA=
if exist logo.ico set LOGO_DATA=%LOGO_DATA% --include-data-files=logo.ico=logo.ico
if exist logo.png set LOGO_DATA=%LOGO_DATA% --include-data-files=logo.png=logo.png
rem --- pack tools into tools.zip -------------------------------------
if exist tools.zip del /q tools.zip
python -c "import shutil; shutil.make_archive('tools','zip','tools')" || goto :fail
if not exist tools.zip (echo ERROR: tools.zip was not created & goto :fail)
rem --- clean old output ----------------------------------------------
if exist dist rmdir /s /q dist
if exist main.build rmdir /s /q main.build
if exist main.onefile-build rmdir /s /q main.onefile-build
rem --onefile-cache-mode exists only in newer Nuitka; empty otherwise
set CACHE_MODE=
python -m nuitka --help 2>nul | findstr /c:"--onefile-cache-mode" >nul && set "CACHE_MODE=--onefile-cache-mode=cached"
if /i "%~1"=="test" goto :test
echo === Release build: onefile with persistent cache ===
python -m nuitka ^
--standalone ^
--onefile ^
--assume-yes-for-downloads ^
--windows-console-mode=disable ^
%ICON_FLAG% ^
--onefile-tempdir-spec="{CACHE_DIR}/MetaMaskUS/%VERSION%" %CACHE_MODE% ^
--include-data-files=%HTML%=%HTML% ^
--include-data-files=tools.zip=tools.zip ^
--include-data-files=geometria-light.woff=geometria-light.woff ^
--include-data-files=geometria-medium.woff=geometria-medium.woff ^
--include-data-files=geometria-bold.woff=geometria-bold.woff ^
--include-data-files=geometria-extrabold.woff=geometria-extrabold.woff ^
--include-data-files=geometria-lightitalic.woff=geometria-lightitalic.woff ^
--include-data-files=geometria-mediumitalic.woff=geometria-mediumitalic.woff ^
--include-data-files=geometria-bolditalic.woff=geometria-bolditalic.woff ^
%LOGO_DATA% ^
--include-package-data=webview ^
--include-module=webview.platforms.edgechromium ^
--include-module=webview.platforms.winforms ^
--include-package=pythonnet ^
--include-package-data=pythonnet ^
--include-package=clr_loader ^
--include-package-data=clr_loader ^
--nofollow-import-to=tkinter ^
--nofollow-import-to=PyQt5 ^
--nofollow-import-to=PyQt6 ^
--nofollow-import-to=PySide2 ^
--nofollow-import-to=PySide6 ^
--nofollow-import-to=matplotlib ^
--nofollow-import-to=numpy ^
--nofollow-import-to=pandas ^
--nofollow-import-to=scipy ^
--company-name="MetaMask US" ^
--product-name="MetaMask US" ^
--product-version=%VERSION%.0 ^
--file-version=%VERSION%.0 ^
--output-dir=dist ^
--output-filename=%EXE% ^
main.py || goto :fail
echo.
echo Done: dist\%EXE%
echo Nuitka cache: %LOCALAPPDATA%\MetaMaskUS\%VERSION%
echo Tools cache : %LOCALAPPDATA%\MetaMaskUS\tools_%VERSION%
echo Reset caches: rmdir /s /q "%LOCALAPPDATA%\MetaMaskUS"
goto :end
:test
echo === Test build: standalone folder with console ===
python -m nuitka ^
--standalone ^
--assume-yes-for-downloads ^
--windows-console-mode=force ^
%ICON_FLAG% ^
--include-data-files=%HTML%=%HTML% ^
--include-data-files=tools.zip=tools.zip ^
--include-data-files=geometria-light.woff=geometria-light.woff ^
--include-data-files=geometria-medium.woff=geometria-medium.woff ^
--include-data-files=geometria-bold.woff=geometria-bold.woff ^
--include-data-files=geometria-extrabold.woff=geometria-extrabold.woff ^
--include-data-files=geometria-lightitalic.woff=geometria-lightitalic.woff ^
--include-data-files=geometria-mediumitalic.woff=geometria-mediumitalic.woff ^
--include-data-files=geometria-bolditalic.woff=geometria-bolditalic.woff ^
%LOGO_DATA% ^
--include-package-data=webview ^
--include-module=webview.platforms.edgechromium ^
--include-module=webview.platforms.winforms ^
--include-package=pythonnet ^
--include-package-data=pythonnet ^
--include-package=clr_loader ^
--include-package-data=clr_loader ^
--nofollow-import-to=tkinter ^
--nofollow-import-to=PyQt5 ^
--nofollow-import-to=PyQt6 ^
--nofollow-import-to=PySide2 ^
--nofollow-import-to=PySide6 ^
--nofollow-import-to=matplotlib ^
--nofollow-import-to=numpy ^
--nofollow-import-to=pandas ^
--nofollow-import-to=scipy ^
--output-dir=dist ^
main.py || goto :fail
echo.
echo Done: dist\main.dist\main.exe
goto :end
:fail
echo.
echo BUILD FAILED. Copy the error text above and send it for a fix.
exit /b 1
:end
endlocal