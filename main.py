# main.py - MetaMask US (pywebview 5.x; Windows: EdgeChromium/WebView2, macOS: WebKit)
# Внешние утилиты: ffmpeg, ffprobe, exiftool (из tools.zip или папки tools).
# Два режима: "change" (подмена Adobe XMP + бинарные патчи) и "clean" (stream copy + стирание).
# Оригинальный файл перезаписывается (с бэкапом .bak на время обработки).
# CLI: MetaMaskUS [--progress] [change|clean] "путь1" "путь2" ...

import os
import sys
import re
import json
import uuid
import time
import shutil
import atexit
import zipfile
import tempfile
import threading
import subprocess
import mmap
import random
import calendar
import queue
from datetime import datetime, timedelta

# ============================================================================
# 0. КОНСТАНТЫ И ПЛАТФОРМА
# ============================================================================
VERSION = "1.0.0"  # Синхронизировано с set VERSION= в build.bat / build_mac.sh
APP_TITLE = "MetaMask US"
HTML_FILE = "metadata_changer_ui_pywebview.html"
ICON_FILE = "logo.ico"

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

VIDEO = {".mp4", ".mov", ".avi", ".mkv"}
PHOTO = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp", ".jfif"}
SUPPORTED = VIDEO | PHOTO
FORBIDDEN_REGEX = r'[\x00-\x1F\\/:*?"<>|]'

SOFTWARE_PACKAGES = [
    {'name': 'Adobe Premiere Pro 2025', 'xmp_toolkit': 'Adobe XMP Core 10.0-c001 79.f0d4a17, 2025/01/16-08:32:00', 'year': 2025},
    {'name': 'Adobe Premiere Pro 2024', 'xmp_toolkit': 'Adobe XMP Core 9.1-c001 79.a8d4753, 2024-01-15-10:20:00', 'year': 2024},
    {'name': 'Adobe Premiere Pro 2023', 'xmp_toolkit': 'Adobe XMP Core 8.0-c001 79.c0204b2, 2023-02-09-06:26:14', 'year': 2023},
    {'name': 'Adobe After Effects 2025', 'xmp_toolkit': 'Adobe XMP Core 10.0-c001 79.f0d4a17, 2025/01/16-08:32:00', 'year': 2025},
    {'name': 'Adobe After Effects 2024', 'xmp_toolkit': 'Adobe XMP Core 9.1-c001 79.a8d4753, 2024-01-15-10:20:00', 'year': 2024},
]

PHOTOSHOP_VERSIONS = [
    {'creator': 'Adobe Photoshop 26.2 (Windows)',   'xmp_toolkit': 'Adobe XMP Core 10.0-c001 79.f0d4a17, 2025-01-16-08:32:00'},
    {'creator': 'Adobe Photoshop 26.0 (Macintosh)', 'xmp_toolkit': 'Adobe XMP Core 10.0-c001 79.f0d4a17, 2025-01-16-08:32:00'},
    {'creator': 'Adobe Photoshop 25.1 (Windows)',   'xmp_toolkit': 'Adobe XMP Core 9.1-c001 79.a8d4753, 2024-01-15-10:20:00'},
]

DC_FORMAT = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.jfif': 'image/jpeg', '.png': 'image/png',
             '.tif': 'image/tiff', '.tiff': 'image/tiff', '.heic': 'image/heic',
             '.heif': 'image/heif', '.webp': 'image/webp'}

LOCALES = ["en_US", "en_US", "en_GB", None]
META_LANGUAGES = ["en-US", "en-GB", None]

CONTAINER_SIG = {
    'brand': 'mp42', 'minor': '0', 'compat': ['mp42', 'avc1', 'isom', 'iso2'],
    'movie_timescale': '10000', 'video_handler': 'Video Media Handler', 'audio_handler': 'Sound Media Handler',
}

# ============================================================================
# 1. РЕСУРСЫ И КЭШ (кроссплатформенно)
# ============================================================================
def _candidate_dirs():
    dirs = []
    def add(d):
        if d and d not in dirs: dirs.append(d)
    try: add(os.path.dirname(os.path.abspath(__file__)))
    except Exception: pass
    try: add(__nuitka_binary_dir)  # noqa: F821
    except NameError: pass
    add(getattr(sys, "_MEIPASS", None))
    for probe in (getattr(sys, "executable", ""), (sys.argv or [""])[0]):
        try:
            if probe: add(os.path.dirname(os.path.abspath(probe)))
        except Exception: pass
    try: add(os.getcwd())
    except Exception: pass
    return dirs or [os.path.abspath(".")]

def find_data(rel):
    rel = rel.replace("/", os.sep)
    for d in _candidate_dirs():
        p = os.path.join(d, rel)
        if os.path.exists(p): return p
    return os.path.join(_candidate_dirs()[0], rel)

def _app_data_root():
    """Win -> %LOCALAPPDATA%\MetaMaskUS, mac -> ~/Library/Application Support/MetaMaskUS."""
    if IS_WIN:
        root = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    elif IS_MAC:
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(root, "MetaMaskUS")

_TOOLS_LOCK = threading.Lock()
_TOOLS_DIR = None

def ensure_tools():
    """Распаковывает tools.zip один раз в <app_data>/tools<VERSION>."""
    global _TOOLS_DIR
    with _TOOLS_LOCK:
        if _TOOLS_DIR: return _TOOLS_DIR
        base = os.path.join(_app_data_root(), "tools" + VERSION)
        marker = os.path.join(base, ".ok")
        if os.path.isfile(marker):
            _TOOLS_DIR = base
            return base
        z = find_data("tools.zip")
        if not os.path.isfile(z): return None   # запуск из исходников: папка tools/
        tmp = base + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(tmp)
        shutil.rmtree(base, ignore_errors=True)
        os.replace(tmp, base)
        if not IS_WIN:  # zip мог потерять бит исполнения — возвращаем
            for name in os.listdir(base):
                p = os.path.join(base, name)
                if os.path.isfile(p):
                    try: os.chmod(p, 0o755)
                    except Exception: pass
        open(marker, "w").close()
        _TOOLS_DIR = base
        return base

def get_tool(name):
    exe = name + ".exe" if IS_WIN else name
    d = ensure_tools()
    if d:
        p = os.path.join(d, exe)
        if os.path.isfile(p): return os.path.abspath(p)
    for rel in (os.path.join("tools", exe), exe):
        p = find_data(rel)
        if os.path.isfile(p): return os.path.abspath(p)
    found = shutil.which(name) or shutil.which(exe)
    return os.path.abspath(found) if found else None

def tail_log(path, n=12):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            lines = [ln.rstrip() for ln in fh if ln.strip()]
        return '\n'.join(lines[-n:])
    except Exception:
        return ''

def cleanup_files(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try: os.remove(p)
            except Exception: pass

# ============================================================================
# 2. УПРАВЛЕНИЕ ПРОЦЕССАМИ
# ============================================================================
_SHUTDOWN = threading.Event()
_PROC_LOCK = threading.Lock()
_PROCESSES = set()

def _kill_process(p):
    try:
        if p.poll() is None:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=CREATE_NO_WINDOW)
            else:
                p.terminate()
    except Exception: pass

def kill_all_processes():
    _SHUTDOWN.set()
    with _PROC_LOCK:
        procs = list(_PROCESSES)
        for p in procs: _kill_process(p)
        time.sleep(0.2)
        for p in procs:
            try:
                if p.poll() is None:
                    p.kill()
                    p.wait(timeout=1)
            except Exception: pass
        _PROCESSES.clear()

atexit.register(kill_all_processes)

def _spawn(cmd, **kw):
    if _SHUTDOWN.is_set(): raise RuntimeError("Приложение закрывается")
    p = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW, text=True,
                         encoding="utf-8", errors="replace", **kw)
    with _PROC_LOCK: _PROCESSES.add(p)
    return p

def _release(p):
    with _PROC_LOCK: _PROCESSES.discard(p)

def run_cmd(cmd, timeout=None):
    p = _spawn(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process(p)
        raise RuntimeError("Превышено время ожидания внешней утилиты")
    finally:
        _release(p)
    return p.returncode, out or "", err or ""

def run_ffmpeg_progress(cmd, duration, progress_cb, start_pct=2, end_pct=90):
    """ffmpeg с чтением -progress pipe:1. Возвращает (код, хвост stderr)."""
    err_path = os.path.join(tempfile.gettempdir(), "ffmpeg_" + uuid.uuid4().hex[:8] + ".log")
    err_f = open(err_path, "w", encoding="utf-8", errors="replace")
    p = _spawn(cmd, stdout=subprocess.PIPE, stderr=err_f)
    last = -1
    try:
        for line in p.stdout:
            if _SHUTDOWN.is_set():
                _kill_process(p)
                break
            if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1].strip() or 0)
                    frac = (us / 1e6) / duration if duration > 0 else 0
                    pct = max(start_pct, min(end_pct, start_pct + int(frac * (end_pct - start_pct))))
                    if pct != last:
                        progress_cb(pct)
                        last = pct
                except ValueError:
                    pass
        p.wait()
    finally:
        _release(p)
        for f in (p.stdout, err_f):
            try: f.close()
            except Exception: pass
    tail = ""
    try:
        with open(err_path, "r", encoding="utf-8", errors="replace") as f:
            tail = " ".join(f.readlines()[-8:]).strip()
    except Exception: pass
    try: os.remove(err_path)
    except Exception: pass
    return p.returncode, tail

# ============================================================================
# 3. ПРОВЕРКА ФАЙЛОВ
# ============================================================================
def normalize_path(p):
    if not p: return ""
    p = str(p).strip().strip('"')
    if p.lower().startswith("file://"):
        try:
            from urllib.parse import unquote, urlparse
            p = unquote(urlparse(p).path)
        except Exception:
            p = p[7:]
        if IS_WIN and p.startswith("/") and len(p) >= 3 and p[2] == ":":
            p = p[1:]
    return os.path.normpath(p)

def validate_media_file(path):
    p = normalize_path(path)
    if not p: return None, "Файл не найден."
    name = os.path.basename(p)
    if re.search(FORBIDDEN_REGEX, name):
        bad = sorted({c for c in re.findall(FORBIDDEN_REGEX, name) if c.isprintable()})
        return None, "Недопустимые символы в имени файла: " + " ".join(bad)
    ext = os.path.splitext(name)[1].lower()
    if ext not in SUPPORTED:
        return None, "Формат " + (ext or "(без расширения)") + " не поддерживается."
    if not os.path.isfile(p):
        return None, "Файл не найден или нет доступа."
    return p, None

def check_space(path, out_dir, factor=3.0):
    try:
        need = os.path.getsize(path) * factor + 10 * 1024 * 1024
        if shutil.disk_usage(out_dir).free < need:
            raise RuntimeError("Недостаточно места на диске")
    except OSError:
        raise RuntimeError("Не удалось прочитать файл")
    if not os.access(out_dir, os.W_OK):
        raise RuntimeError("Нет права на запись в папку с файлом")

def probe_duration(ffprobe, path):
    rc, out, _ = run_cmd([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], timeout=60)
    try:
        return float(out.strip()) if rc == 0 else 0.0
    except ValueError:
        return 0.0

# ============================================================================
# 4. ГЕНЕРАЦИЯ МЕТАДАННЫХ (режим change)
# ============================================================================
def format_fps_for_xmp(fps):
    if abs(fps - 30000.0/1001.0) < 0.001: return "29.970030"
    if abs(fps - 60000.0/1001.0) < 0.001: return "59.940060"
    return f"{fps:.6f}"

def format_iso_date_tz(s):
    m = re.match(r'(.+?)([-+]\d{2}:\d{2})$', s)
    if m:
        d, t = m.group(1).split(' ')
        return d.replace(':', '-') + 'T' + t + m.group(2)
    d, t = s.split(' ')
    return d.replace(':', '-') + 'T' + t

def tz_offset_hours(tz):
    m = re.match(r'([-+])(\d{2}):(\d{2})', tz)
    sign = -1 if m.group(1) == '-' else 1
    return sign * (int(m.group(2)) + int(m.group(3)) / 60.0)

def local_to_utc_str(local_ds, tz):
    dt = datetime.strptime(local_ds, "%Y:%m:%d %H:%M:%S")
    return (dt - timedelta(hours=tz_offset_hours(tz))).strftime("%Y:%m:%d %H:%M:%S")

def ny_offset(dt):
    year = dt.year
    mar1 = datetime(year, 3, 1)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)
    nov1 = datetime(year, 11, 1)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return "-04:00" if dst_start <= dt < dst_end else "-05:00"

def get_h264_level(w, h, fps):
    if not w or not h: return '4.0'
    px, f = w * h, (fps or 30)
    if px <= 720*576: return '3.0'
    if px <= 1280*720: return '3.1' if f <= 30 else '4.0'
    if px <= 1920*1080: return '4.0' if f <= 30 else '4.2'
    if px <= 2048*1080: return '4.2' if f <= 30 else '5.0'
    if px <= 2560*1440: return '5.0'
    if px <= 3840*2160: return '5.1' if f <= 30 else '5.2'
    return '5.2'

def generate_project_path(video_path, is_premiere=True, dt=None):
    folders, ext = (["Premiere Pro", "Adobe Projects", "Video Edits"], ".prproj") if is_premiere \
        else (["After Effects", "Motion Graphics", "VFX Renders"], ".aep")
    users_win = ["Editor", "VideoProducer", "Admin", "CreativeUser"]
    users_mac = ["editor", "creative", "admin", "video_user"]
    if dt is None: dt = datetime.now() - timedelta(days=1)
    folder_date = dt - timedelta(days=random.choice([0, 3, 10, 25, 60]))
    year, month, month_num = folder_date.year, folder_date.strftime("%b"), folder_date.month
    vname = re.sub(r'[^\w\-_\(\)\[\]]', '_', os.path.splitext(os.path.basename(video_path))[0])[:40]
    suffix = random.choice(["", "", "_final", "_v2", "_master", "_export", " v2"])
    pname = f"{vname}{suffix}{ext}"
    date_folder = random.choice([f"{year}", f"{year}_{month}", f"{year}-{month_num:02d}", ""])
    if random.random() < 0.3:
        parts = [f"/Users/{random.choice(users_mac)}/Movies/{random.choice(folders)}"]
        if date_folder: parts.append(date_folder)
        parts.append(pname)
        return "/".join(parts)
    parts = [rf"{random.choice(['C:', 'D:'])}\Users\{random.choice(users_win)}\Documents\{random.choice(folders)}"]
    if date_folder: parts.append(date_folder)
    if random.random() > 0.5: parts.append(random.choice(["Final", "Exports", "Working"]))
    parts.append(pname)
    return "\\".join(parts)

def generate_metadata(file_path=None):
    y = datetime.now() - timedelta(days=1)
    secs = random.sample(range(60), 4)
    create_dt = datetime(y.year, y.month, y.day, random.randint(9, 18), random.randint(0, 59), secs[0])
    mod_dt = (create_dt + timedelta(hours=random.randint(1, 3), minutes=random.randint(0, 59))).replace(second=secs[1])
    export_dt = (mod_dt + timedelta(minutes=random.randint(10, 180))).replace(second=secs[2])
    export_end_dt = export_dt + timedelta(seconds=random.randint(15, 240))
    tz = ny_offset(create_dt)
    fmt = lambda d: d.strftime("%Y:%m:%d %H:%M:%S")
    pkg = random.choice(SOFTWARE_PACKAGES)
    is_pr = "Premiere" in pkg['name']
    project_path = generate_project_path(file_path, is_pr, create_dt) if file_path \
        else r"C:\Users\Editor\Documents\default.prproj"
    doc_id = f"xmp.did:{uuid.uuid4().hex}"
    return {
        'create_str': fmt(create_dt), 'mod_str': fmt(mod_dt),
        'export_str': fmt(export_dt), 'export_end_str': fmt(export_end_dt),
        'create_str_tz': f"{fmt(create_dt)}{tz}", 'mod_str_tz': f"{fmt(mod_dt)}{tz}",
        'export_str_tz': f"{fmt(export_dt)}{tz}", 'export_end_str_tz': f"{fmt(export_end_dt)}{tz}",
        'export_utc': local_to_utc_str(fmt(export_dt), tz),
        'export_end_utc': local_to_utc_str(fmt(export_end_dt), tz),
        'instance_id': f"xmp.iid:{uuid.uuid4().hex}", 'document_id': doc_id, 'original_doc_id': doc_id,
        'project_path': project_path, 'software': pkg['name'], 'software_year': pkg['year'],
        'timezone': tz, 'xmp_toolkit': pkg['xmp_toolkit'],
        'locale': random.choice(LOCALES), 'meta_language': random.choice(META_LANGUAGES),
        'is_premiere': is_pr,
        'sequence_id': random.randint(100, 999) if is_pr else None,
        'composition_id': random.randint(100, 200) if not is_pr else None,
        'render_item_id': random.randint(1, 20) if not is_pr else None,
    }

# ============================================================================
# 5. БИНАРНЫЕ ПАТЧИ (mmap)
# ============================================================================
def patch_compressorname_simple(file_path):
    try:
        with open(file_path, 'r+b') as f:
            with mmap.mmap(f.fileno(), 0) as mm:
                pos = mm.find(b'Lavc')
                if pos == -1: return None
                end = pos
                while end < len(mm) and (end - pos) < 31 and mm[end] != 0: end += 1
                old_len = end - pos
                if old_len == 0: return None
                mm[pos:end] = b"AVC Coding".ljust(old_len, b'\x00')
                return True
    except Exception:
        return False

def _atom_ok(mm, p):
    if p < 4: return False
    size = int.from_bytes(mm[p-4:p], 'big')
    return 8 <= size <= len(mm)

def patch_mp4_signature(file_path, brand='mp42', minor=0, compat=('mp42', 'avc1', 'isom', 'iso2'), timescale=10000):
    """Байт-патч ftyp + пересчёт mvhd/tkhd/elst/mehd в таймскейле фильма."""
    try:
        with open(file_path, 'r+b') as f:
            with mmap.mmap(f.fileno(), 0) as mm:
                p = mm.find(b'ftyp')
                if p != -1 and _atom_ok(mm, p):
                    size = int.from_bytes(mm[p-4:p], 'big')
                    n_compat = max(0, (size - 16) // 4)
                    mm[p+4:p+8] = brand.encode('latin1')[:4].ljust(4)
                    mm[p+8:p+12] = int(minor).to_bytes(4, 'big')
                    for i in range(min(n_compat, len(compat))):
                        off = p + 12 + 4 * i
                        mm[off:off+4] = compat[i].encode('latin1')[:4].ljust(4)

                old_ts_mvhd = None
                p = mm.find(b'mvhd')
                if p != -1 and _atom_ok(mm, p):
                    version = mm[p+4]
                    if version == 0:
                        ts_off, dur_off, dur_size = p+16, p+20, 4
                    else:
                        ts_off, dur_off, dur_size = p+24, p+28, 8
                    old_ts = int.from_bytes(mm[ts_off:ts_off+4], 'big')
                    if old_ts and old_ts != timescale:
                        old_dur = int.from_bytes(mm[dur_off:dur_off+dur_size], 'big')
                        mm[dur_off:dur_off+dur_size] = (old_dur * int(timescale) // old_ts).to_bytes(dur_size, 'big')
                        mm[ts_off:ts_off+4] = int(timescale).to_bytes(4, 'big')
                        old_ts_mvhd = old_ts

                if old_ts_mvhd:
                    fnum, fden = int(timescale), old_ts_mvhd
                    start = 0
                    while True:
                        p = mm.find(b'tkhd', start)
                        if p == -1 or not _atom_ok(mm, p): break
                        start = p + 4
                        if mm[p+4] == 0: d_off, d_size = p+24, 4
                        else: d_off, d_size = p+32, 8
                        old_d = int.from_bytes(mm[d_off:d_off+d_size], 'big')
                        mm[d_off:d_off+d_size] = (old_d * fnum // fden).to_bytes(d_size, 'big')

                    start = 0
                    while True:
                        p = mm.find(b'elst', start)
                        if p == -1 or not _atom_ok(mm, p): break
                        start = p + 4
                        ver = mm[p+4]
                        cnt = int.from_bytes(mm[p+8:p+12], 'big')
                        entry_size = 12 if ver == 0 else 20
                        sd_size = 4 if ver == 0 else 8
                        off = p + 12
                        for _ in range(cnt):
                            if off + entry_size > len(mm): break
                            old_sd = int.from_bytes(mm[off:off+sd_size], 'big')
                            mm[off:off+sd_size] = (old_sd * fnum // fden).to_bytes(sd_size, 'big')
                            off += entry_size

                    start = 0
                    while True:
                        p = mm.find(b'mehd', start)
                        if p == -1 or not _atom_ok(mm, p): break
                        start = p + 4
                        fd_size = 4 if mm[p+4] == 0 else 8
                        old_fd = int.from_bytes(mm[p+8:p+8+fd_size], 'big')
                        mm[p+8:p+8+fd_size] = (old_fd * fnum // fden).to_bytes(fd_size, 'big')
                return True
    except Exception as e:
        print(f"mp4 signature patch error: {e}")
        return False

# ============================================================================
# 6. PROBING (ffprobe)
# ============================================================================
def get_video_params_ffprobe(ffprobe_path, inp):
    try:
        r = subprocess.run([ffprobe_path, '-v', 'quiet', '-print_format', 'json', '-show_streams', inp],
                           capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0: return None
        p = {'bitrate': None, 'audio_bitrate': None, 'audio_codec': None, 'fps': None, 'width': None, 'height': None}
        for s in json.loads(r.stdout).get('streams', []):
            if s.get('codec_type') == 'video':
                p['width'], p['height'] = s.get('width'), s.get('height')
                p['bitrate'] = int(s['bit_rate']) // 1000 if s.get('bit_rate') else None
                fr = s.get('r_frame_rate', '0/0')
                if '/' in fr:
                    n, d = fr.split('/')
                    if float(d) != 0: p['fps'] = float(n) / float(d)
            elif s.get('codec_type') == 'audio':
                p['audio_bitrate'] = int(s['bit_rate']) // 1000 if s.get('bit_rate') else None
                p['audio_codec'] = s.get('codec_name', '').lower()
        return p
    except Exception:
        return None

# ============================================================================
# 7. РЕЖИМ CHANGE (перезапись оригинала)
# ============================================================================
def process_video_change(path, progress_cb):
    ffmpeg, ffprobe, exiftool = get_tool("ffmpeg"), get_tool("ffprobe"), get_tool("exiftool")
    if not (ffmpeg and ffprobe and exiftool):
        raise RuntimeError("Не найдены инструменты (ffmpeg, ffprobe, exiftool)")
    if not os.access(path, os.R_OK | os.W_OK):
        raise RuntimeError("Нет прав на чтение/запись файла")

    dir_path = os.path.dirname(os.path.abspath(path))
    check_space(path, dir_path, factor=3.0)

    progress_cb(2)
    params = get_video_params_ffprobe(ffprobe, path)
    if not params or not params.get('width'):
        raise RuntimeError("Видеопоток не найден или файл поврежден")

    total_duration = probe_duration(ffprobe, path) or 10
    meta = generate_metadata(path)
    iso_create_tz = format_iso_date_tz(meta['create_str_tz'])
    iso_mod_tz = format_iso_date_tz(meta['mod_str_tz'])
    iso_end_tz = format_iso_date_tz(meta['export_end_str_tz'])
    # ISO-формат для ffmpeg creation_time (иначе av_parse_time не поймёт)
    iso_export_utc = meta["export_utc"][:10].replace(':', '-') + 'T' + meta["export_utc"][11:] + 'Z'
    fps_real = params.get('fps', 29.97)
    fps_str = format_fps_for_xmp(fps_real)
    level = get_h264_level(params.get('width'), params.get('height'), fps_real)

    uid = uuid.uuid4().hex[:8]
    backup_path = path + f".{uid}.bak"
    temp_out = os.path.join(dir_path, f"temp_{uid}.mp4")

    try:
        shutil.copy2(path, backup_path)
    except Exception as e:
        raise RuntimeError(f"Не удалось создать резервную копию: {e}")

    progress_cb(5)
    try:
        bitrate, ab = params.get('bitrate'), params.get('audio_bitrate')
        has_audio = params.get('audio_codec') is not None
        ff_timeout = 900 if params.get('width') and params['width'] > 1920 else 600

        video_p = ['-c:v', 'libx264', '-preset', 'medium', '-profile:v', 'high', '-level:v', level,
                   '-bf', '2', '-g', str(max(1, int(fps_real))), '-pix_fmt', 'yuv420p', '-coder', '1']
        rate_p = (['-b:v', f'{bitrate}k', '-maxrate', f'{int(bitrate * 1.4)}k', '-bufsize', f'{int(bitrate * 2)}k']
                  if bitrate else ['-crf', '22'])
        stream_md = ['-metadata:s:v:0', f'handler_name={CONTAINER_SIG["video_handler"]}',
                     '-metadata:s:v:0', 'language=eng',
                     '-metadata', f'creation_time={iso_export_utc}']
        if has_audio:
            stream_md += ['-metadata:s:a:0', f'handler_name={CONTAINER_SIG["audio_handler"]}',
                          '-metadata:s:a:0', 'language=eng']
            audio_p = ['-c:a', 'aac', '-ar', '48000',
                       '-b:a', f'{ab}k' if ab and int(ab) >= 128 else '192k', '-profile:a', 'aac_low']
        else:
            audio_p = ['-an']
        out_p = ['-progress', 'pipe:1', '-nostats', temp_out, '-y']
        maps = ['-map', '0:v:0', '-map', '0:a:0?']
        cmd_primary = [ffmpeg, '-v', 'error', '-i', path, *maps, *video_p, *rate_p,
                       *stream_md, *audio_p, '-shortest', *out_p]

        last_progress = 5
        err_log = os.path.join(dir_path, f"fferr_{uid}.log")
        err_fh = open(err_log, 'w', encoding='utf-8', errors='replace')
        try:
            proc = _spawn(cmd_primary, stdout=subprocess.PIPE, stderr=err_fh)
        except Exception:
            err_fh.close()
            raise
        pq, stop = queue.Queue(), threading.Event()

        def reader():
            try:
                for line in proc.stdout:
                    if _SHUTDOWN.is_set() or stop.is_set(): break
                    if 'out_time_ms=' in line or 'out_time_us=' in line: pq.put(line)
            except Exception: pass
            finally:
                try: proc.stdout.close()
                except Exception: pass

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        t0 = time.time()

        while th.is_alive():
            if _SHUTDOWN.is_set():
                proc.terminate(); stop.set(); break
            try:
                line = pq.get(timeout=1)
                try:
                    us = int(line.split('=')[1])
                    pr = min(int(us / 1_000_000 / total_duration * 80) + 5, 85)
                    if pr > last_progress:
                        last_progress = pr
                        progress_cb(pr)
                except (ValueError, IndexError): pass
            except queue.Empty:
                if time.time() - t0 > ff_timeout:
                    proc.terminate(); stop.set(); break
        try:
            th.join(timeout=5)
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
        finally:
            _release(proc)
            try: err_fh.close()
            except Exception: pass

        tail = tail_log(err_log, 12)
        cleanup_files(err_log)
        rc = proc.returncode

        if rc != 0:
            cleanup_files(temp_out)
            abnormal = rc is not None and (rc < 0 or rc > 255)
            code = f"{rc} / 0x{rc & 0xFFFFFFFF:X}" if abnormal else str(rc)
            hint = ("\nПроцесс завершён антивирусом/системой: добавьте папку и tools в исключения "
                    "или замените ffmpeg") if (abnormal and not tail) \
                else (f"\n{tail[-250:]}" if tail else "")
            raise RuntimeError(f"Ошибка FFmpeg (код {code}){hint}")

        progress_cb(86)
    except Exception as e:
        cleanup_files(temp_out, backup_path)
        raise e

    ecmd = [exiftool, '-overwrite_original',
            f'-Software={meta["software"]}', f'-CreatorTool={meta["software"]}',
            f'-CreateDate={meta["export_utc"]}', f'-ModifyDate={meta["export_end_utc"]}',
            f'-DateTimeOriginal={meta["export_utc"]}',
            f'-TrackCreateDate={meta["export_utc"]}', f'-TrackModifyDate={meta["export_end_utc"]}',
            f'-MediaCreateDate={meta["export_utc"]}', f'-MediaModifyDate={meta["export_end_utc"]}',
            f'-MetadataDate={meta["export_end_str_tz"]}',
            f'-XMPToolkit={meta["xmp_toolkit"]}',
            f'-XMP:DateCreated={iso_create_tz}', f'-XMP:ModifyDate={iso_end_tz}',
            f'-XMP:MetadataDate={iso_end_tz}',
            f'-XMP:InstanceID={meta["instance_id"]}', f'-XMP:DocumentID={meta["document_id"]}',
            f'-XMP:OriginalDocumentID={meta["original_doc_id"]}',
            f'-XMP:VideoFrameRate={fps_str}', '-XMP:VideoFieldOrder=Progressive', '-XMP:VideoPixelAspectRatio=1']

    if meta["is_premiere"]:
        ecmd += [f'-XMP:ProjectRefPath={meta["project_path"]}', '-XMP:ProjectRefType=ProjectRefPath',
                 f'-XMP:SequenceID={meta["sequence_id"]}', '-XMP:ProjectRefTimecodeFormat=23.976fps']
    else:
        ecmd += [f'-XMP:AeProjectLinkFullPath={meta["project_path"]}',
                 f'-XMP:AeProjectLinkCompositionID={meta["composition_id"]}',
                 f'-XMP:AeProjectLinkRenderQueueItemID={meta["render_item_id"]}',
                 '-XMP:AeProjectLinkRenderOutputModuleIndex=0']
    if meta['locale'] is not None: ecmd.append(f'-XMP:Locale={meta["locale"]}')
    if meta['meta_language'] is not None: ecmd.append(f'-XMP:MetadataLanguage={meta["meta_language"]}')

    steps = [('created', iso_create_tz, '/'), ('modified', iso_mod_tz, '/metadata'), ('saved', iso_end_tz, '/')]
    for act, when, chg in steps:
        ecmd += [f'-XMP-xmpMM:HistoryAction+={act}', f'-XMP-xmpMM:HistoryWhen+={when}',
                 f'-XMP-xmpMM:HistorySoftwareAgent+={meta["software"]}', f'-XMP-xmpMM:HistoryChanged+={chg}']
    ecmd.append(temp_out)

    try:
        r = subprocess.run(ecmd, capture_output=True, text=True, timeout=180,
                           creationflags=CREATE_NO_WINDOW, encoding='utf-8', errors='replace')
        if r.returncode != 0:
            cleanup_files(temp_out); raise RuntimeError(f"Ошибка ExifTool: {r.stderr[:200]}")

        chk_h = subprocess.run([exiftool, '-XMP-xmpMM:HistoryAction', '-s3', temp_out],
                               capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        if not chk_h.stdout.strip():
            struct = [f'-XMP-xmpMM:History+={{action={a},when={w},softwareAgent="{meta["software"]}",changed={c}}}'
                      for a, w, c in steps]
            subprocess.run([exiftool, '-overwrite_original', *struct, temp_out],
                           capture_output=True, text=True, timeout=180, creationflags=CREATE_NO_WINDOW)

        progress_cb(92)
        subprocess.run([exiftool, '-overwrite_original', '-encoder=', '-EncodedBy=', '-Producer=', temp_out],
                       capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)

        if os.path.splitext(temp_out)[1].lower() in ('.mp4', '.mov'):
            patch_compressorname_simple(temp_out)
            patch_mp4_signature(temp_out, CONTAINER_SIG['brand'], int(CONTAINER_SIG['minor']),
                                CONTAINER_SIG['compat'], int(CONTAINER_SIG['movie_timescale']))

        progress_cb(95)
        os.replace(temp_out, path)
        if os.path.getsize(path) == 0:
            raise RuntimeError("Выходной файл пуст")

        utc_dt = datetime.strptime(meta['export_end_utc'], "%Y:%m:%d %H:%M:%S")
        epoch = calendar.timegm(utc_dt.timetuple())
        os.utime(path, (epoch, epoch))   # на macOS birth-time не меняется (ограничение ОС)
        cleanup_files(backup_path)
        progress_cb(100)
    except Exception as e:
        if os.path.exists(backup_path):
            try: os.replace(backup_path, path)
            except Exception: pass
        cleanup_files(temp_out)
        raise RuntimeError(f"Ошибка замены файла: {e}")

def process_photo_change(path, progress_cb):
    exiftool = get_tool("exiftool")
    if not exiftool:
        raise RuntimeError("Не найден exiftool")
    if not os.access(path, os.R_OK | os.W_OK):
        raise RuntimeError("Нет прав на чтение/запись файла")

    dir_path = os.path.dirname(os.path.abspath(path))
    check_space(path, dir_path, factor=2.0)

    progress_cb(10)
    uid = uuid.uuid4().hex[:8]
    ext = os.path.splitext(path)[1].lower()
    backup_path = path + f".{uid}.bak"
    temp_out = os.path.join(dir_path, f"temp_{uid}{ext}")

    try:
        shutil.copy2(path, backup_path)
        shutil.copy2(path, temp_out)
    except Exception as e:
        cleanup_files(temp_out, backup_path)
        raise RuntimeError(f"Не удалось создать резервную копию: {e}")

    ps = random.choice(PHOTOSHOP_VERSIONS)
    secs = random.sample(range(60), 3)
    y = datetime.now() - timedelta(days=random.randint(1, 3))
    create_dt = datetime(y.year, y.month, y.day, random.randint(9, 18), random.randint(0, 59), secs[0])
    mod_dt = (create_dt + timedelta(hours=random.randint(1, 4), minutes=random.randint(0, 59))).replace(second=secs[1])
    save_dt = (mod_dt + timedelta(minutes=random.randint(5, 90))).replace(second=secs[2])
    tz = ny_offset(create_dt)
    fmt = lambda d: d.strftime("%Y:%m:%d %H:%M:%S")
    iso = lambda d: format_iso_date_tz(f"{fmt(d)}{tz}")
    create_tz, mod_tz, save_tz = iso(create_dt), iso(mod_dt), iso(save_dt)

    doc_id = f"xmp.did:{uuid.uuid4().hex}"
    iid = [f"xmp.iid:{uuid.uuid4().hex}" for _ in range(4)]

    px_tags = []
    try:
        sz = subprocess.run([exiftool, '-ImageSize', '-s3', temp_out],
                            capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        if sz.returncode == 0 and 'x' in sz.stdout:
            w, h = sz.stdout.strip().split('x')
            px_tags = [f'-PixelXDimension={w}', f'-PixelYDimension={h}']
    except Exception:
        pass

    dpi = random.choice(['72', '300'])
    dc_format = DC_FORMAT.get(ext, 'image/jpeg')

    ecmd = [exiftool, '-overwrite_original',
            '-exif:all=', '-gps:all=', '-XMP:all=', '-Photoshop:all=', '-IPTC:all=', '-Comment=',
            f'-XMPToolkit={ps["xmp_toolkit"]}', f'-CreatorTool={ps["creator"]}',
            f'-XMP:CreateDate={create_tz}', f'-XMP:ModifyDate={save_tz}', f'-XMP:MetadataDate={save_tz}',
            f'-XMP-photoshop:DateCreated={create_tz}',
            f'-XMP:DocumentID={doc_id}', f'-XMP:OriginalDocumentID={doc_id}', f'-XMP:InstanceID={iid[3]}',
            f'-XMP-dc:format={dc_format}', '-XMP-photoshop:ColorMode=3',
            f'-XResolution={dpi}', f'-YResolution={dpi}', '-ResolutionUnit=2', '-ColorSpace=1', *px_tags]

    hist = [('created', create_tz, iid[0], None, None),
            ('saved', mod_tz, iid[1], None, '/'),
            ('converted', save_tz, iid[2], f'from application/vnd.adobe.photoshop to {dc_format}', None),
            ('saved', save_tz, iid[3], None, '/')]
    for act, when, inst, params, changed in hist:
        ecmd += [f'-XMP-xmpMM:HistoryAction+={act}', f'-XMP-xmpMM:HistoryWhen+={when}',
                 f'-XMP-xmpMM:HistoryInstanceID+={inst}', f'-XMP-xmpMM:HistorySoftwareAgent+={ps["creator"]}']
        if params: ecmd.append(f'-XMP-xmpMM:HistoryParameters+={params}')
        if changed: ecmd.append(f'-XMP-xmpMM:HistoryChanged+={changed}')
    ecmd.append(temp_out)

    progress_cb(60)
    try:
        r = subprocess.run(ecmd, capture_output=True, text=True, timeout=120,
                           creationflags=CREATE_NO_WINDOW, encoding='utf-8', errors='replace')
        if r.returncode != 0:
            cleanup_files(temp_out, backup_path); raise RuntimeError(f"Ошибка ExifTool: {r.stderr[:200]}")

        chk = subprocess.run([exiftool, '-CreatorTool', '-s3', temp_out],
                             capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        if 'Adobe Photoshop' not in chk.stdout:
            cleanup_files(temp_out, backup_path); raise RuntimeError("Метаданные фото не записаны корректно")

        chk_h = subprocess.run([exiftool, '-XMP-xmpMM:HistoryAction', '-s3', temp_out],
                               capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        if not chk_h.stdout.strip():
            struct = []
            for act, when, inst, params, changed in hist:
                s = f'{{action={act},when={when},instanceID={inst},softwareAgent="{ps["creator"]}"'
                if params: s += f',parameters={params}'
                if changed: s += f',changed={changed}'
                struct.append(f'-XMP-xmpMM:History+={s}}}')
            subprocess.run([exiftool, '-overwrite_original', *struct, temp_out],
                           capture_output=True, text=True, timeout=120, creationflags=CREATE_NO_WINDOW)

        progress_cb(85)
        os.replace(temp_out, path)
        utc_dt = save_dt - timedelta(hours=tz_offset_hours(tz))
        epoch = calendar.timegm(utc_dt.timetuple())
        os.utime(path, (epoch, epoch))
        cleanup_files(backup_path)
        progress_cb(100)
    except subprocess.TimeoutExpired:
        cleanup_files(temp_out, backup_path); raise RuntimeError("Превышено время ожидания ExifTool")
    except Exception as e:
        if os.path.exists(backup_path):
            try: os.replace(backup_path, path)
            except Exception: pass
        cleanup_files(temp_out)
        raise RuntimeError(f"Ошибка замены файла: {e}")

# ============================================================================
# 8. РЕЖИМ CLEAN / Remove (перезапись оригинала)
# ============================================================================
def process_video_clean(path, progress_cb):
    ffmpeg, ffprobe, exiftool = get_tool("ffmpeg"), get_tool("ffprobe"), get_tool("exiftool")
    if not (ffmpeg and ffprobe and exiftool):
        raise RuntimeError("Не найдены инструменты (ffmpeg, ffprobe, exiftool)")
    if not os.access(path, os.R_OK | os.W_OK):
        raise RuntimeError("Нет прав на чтение/запись файла")

    dir_path = os.path.dirname(os.path.abspath(path))
    check_space(path, dir_path, factor=1.2)

    ext = os.path.splitext(path)[1].lower()
    uid = uuid.uuid4().hex[:8]
    backup_path = path + f".{uid}.bak"
    temp = os.path.join(dir_path, f".clean_{uid}{ext}")

    try:
        shutil.copy2(path, backup_path)
    except Exception as e:
        raise RuntimeError(f"Не удалось создать резервную копию: {e}")

    progress_cb(0)
    try:
        duration = probe_duration(ffprobe, path)
        cmd = [ffmpeg, "-v", "error", "-i", path,
               "-map", "0:v?", "-map", "0:a?",
               "-map_metadata", "-1", "-map_chapters", "-1",
               "-c", "copy",
               "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
        if ext in (".mp4", ".mov"):
            cmd += ["-movflags", "+faststart"]
        cmd += ["-progress", "pipe:1", "-nostats", "-y", temp]
        rc, tail = run_ffmpeg_progress(cmd, duration, progress_cb)
        if _SHUTDOWN.is_set():
            raise RuntimeError("Приложение закрывается")
        if rc != 0 or not os.path.isfile(temp) or os.path.getsize(temp) == 0:
            raise RuntimeError("FFmpeg не смог обработать файл" + (": " + tail[-200:] if tail else ""))

        progress_cb(92)
        if ext in (".mp4", ".mov"):  # exiftool не пишет в mkv/avi
            rc, _, err = run_cmd([exiftool, "-overwrite_original", "-charset", "filename=utf8",
                                  "-all=", temp], timeout=240)
            if rc != 0:
                raise RuntimeError("ExifTool: " + err.strip()[:200])
        progress_cb(98)

        os.replace(temp, path)
        progress_cb(100)
        cleanup_files(backup_path)
    except Exception as e:
        if os.path.exists(backup_path):
            try: os.replace(backup_path, path)
            except Exception: pass
        cleanup_files(temp)
        raise RuntimeError(str(e).strip() or "Ошибка очистки видео")

def process_photo_clean(path, progress_cb):
    exiftool = get_tool("exiftool")
    if not exiftool:
        raise RuntimeError("Не найден exiftool")
    if not os.access(path, os.R_OK | os.W_OK):
        raise RuntimeError("Нет прав на чтение/запись файла")

    dir_path = os.path.dirname(os.path.abspath(path))
    check_space(path, dir_path, factor=1.2)

    ext = os.path.splitext(path)[1].lower()
    uid = uuid.uuid4().hex[:8]
    backup_path = path + f".{uid}.bak"
    temp = os.path.join(dir_path, f".clean_{uid}{ext}")

    try:
        shutil.copy2(path, backup_path)
        shutil.copy2(path, temp)
    except Exception as e:
        cleanup_files(temp, backup_path)
        raise RuntimeError(f"Не удалось создать резервную копию: {e}")

    progress_cb(10)
    try:
        progress_cb(40)
        rc, _, err = run_cmd([exiftool, "-overwrite_original", "-charset", "filename=utf8",
                              "-all=", "-tagsfromfile", "@", "-Orientation", "-ColorSpaceTags",
                              temp], timeout=240)
        if rc != 0:
            raise RuntimeError("ExifTool: " + err.strip()[:200])
        progress_cb(95)
        os.replace(temp, path)
        progress_cb(100)
        cleanup_files(backup_path)
    except Exception as e:
        if os.path.exists(backup_path):
            try: os.replace(backup_path, path)
            except Exception: pass
        cleanup_files(temp)
        raise RuntimeError(str(e).strip() or "Ошибка очистки фото")

# ============================================================================
# 9. ДИСПЕТЧЕР РЕЖИМОВ
# ============================================================================
def process_media(path, progress_cb, mode='change'):
    ext = os.path.splitext(path)[1].lower()
    if mode == 'clean':
        if ext in VIDEO: process_video_clean(path, progress_cb)
        elif ext in PHOTO: process_photo_clean(path, progress_cb)
        else: raise RuntimeError("Формат не поддерживается.")
    else:
        if ext in VIDEO: process_video_change(path, progress_cb)
        elif ext in PHOTO: process_photo_change(path, progress_cb)
        else: raise RuntimeError("Формат не поддерживается.")
    return path  # оригинал перезаписан на месте

# ============================================================================
# 10. API ДЛЯ JS (PYWEBVIEW)
# ============================================================================
class Api:
    def __init__(self):
        self._window = None

    def _send_progress(self, file_id, percent):
        if not self._window: return
        try:
            percent = max(0, min(100, int(percent)))
            self._window.evaluate_js("window.__progress && window.__progress(" +
                                     json.dumps(file_id) + ", " + str(percent) + ")")
        except Exception: pass

    def pick_files(self):
        if not self._window: return []
        import webview as _wv
        mask = "*.mp4;*.mov;*.avi;*.mkv;*.jpg;*.jpeg;*.jfif;*.png;*.heic;*.heif;*.tif;*.tiff;*.webp"
        try:
            result = self._window.create_file_dialog(
                _wv.FileDialog.OPEN, allow_multiple=True,
                file_types=("Медиафайлы (" + mask + ")", "Все файлы (*.*)"))
        except Exception:
            return []
        out, seen = [], set()
        for p in (result or []):
            p = normalize_path(p)
            if p and p not in seen and os.path.isfile(p):
                seen.add(p)
                try: size = os.path.getsize(p)
                except OSError: size = 0
                out.append({"name": os.path.basename(p), "size": size, "path": p})
        return out

    def process_file(self, file_id, path, mode='change'):
        """mode: 'change' (подмена метаданных) или 'clean' (очистка)."""
        try:
            valid, err = validate_media_file(path)
            if err: return {"ok": False, "error": err}
            mode = (mode or 'change').lower()
            if mode not in ('change', 'clean'): mode = 'change'
            last = [-1]
            def cb(pct):
                pct = int(pct)
                if pct > last[0]:
                    last[0] = pct
                    self._send_progress(file_id, pct)
            out_path = process_media(valid, cb, mode)
            self._send_progress(file_id, 100)
            return {"ok": True, "output": out_path, "mode": mode}
        except Exception as e:
            return {"ok": False, "error": str(e).strip() or "Неизвестная ошибка обработки"}

    def reveal(self, path):
        try:
            p = normalize_path(path)
            if not p: return
            if not os.path.exists(p):
                p = os.path.dirname(p)
                if not os.path.isdir(p): return
            if IS_WIN:
                if os.path.isfile(p):
                    # Одной строкой, кавычки ТОЛЬКО вокруг пути (иначе Проводник
                    # не разберёт пробелы и откроет "Документы").
                    subprocess.Popen('explorer /select,"' + os.path.normpath(p) + '"',
                                     creationflags=CREATE_NO_WINDOW)
                else:
                    subprocess.Popen('explorer "' + os.path.normpath(p) + '"',
                                     creationflags=CREATE_NO_WINDOW)
            elif IS_MAC:
                subprocess.Popen(["open", "-R", p] if os.path.isfile(p) else ["open", p])
            else:
                subprocess.Popen(["xdg-open", p if os.path.isdir(p) else os.path.dirname(p)])
        except Exception: pass

# ============================================================================
# 11. DRAG & DROP
# ============================================================================
_DROP_DONE = set()
def _make_drop_handler(window):
    def handler(e=None):
        items = []
        try:
            if isinstance(e, dict):
                files = (e.get("dataTransfer") or {}).get("files") or []
            else:
                files = getattr(getattr(e, "dataTransfer", None), "files", None) or []
            for f in files:
                get = f.get if isinstance(f, dict) else (lambda k, _f=f: getattr(_f, k, None))
                path = normalize_path(get("pywebviewFullPath") or get("path") or "")
                if path and os.path.isfile(path):
                    try: size = os.path.getsize(path)
                    except OSError: size = 0
                    items.append({"name": os.path.basename(path), "size": size, "path": path})
            if items:
                window.evaluate_js("window.__addFiles && window.__addFiles(" +
                                   json.dumps(items, ensure_ascii=False) + ")")
        except Exception: pass
        return handler
    return handler

def _enable_drop(window):
    if id(window) in _DROP_DONE: return
    _DROP_DONE.add(id(window))
    try:
        window.dom.document.events.drop += _make_drop_handler(window)
    except Exception:
        try:
            window.dom.document.events.drop += lambda e: None
        except Exception: pass

# ============================================================================
# 12. ИКОНКА ПРИЛОЖЕНИЯ (Win: WM_SETICON, mac: dock icon)
# ============================================================================
def _apply_window_icon_win():
    icon_path = find_data(ICON_FILE)
    if not os.path.isfile(icon_path): return
    def worker():
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = None
            for _ in range(40):
                if _SHUTDOWN.is_set(): return
                hwnd = user32.FindWindowW(None, APP_TITLE)
                if hwnd: break
                time.sleep(0.25)
            if not hwnd: return
            IMAGE_ICON, LR_LOADFROMFILE = 1, 0x00000010
            hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if not hicon: return
            WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        except Exception: pass
    threading.Thread(target=worker, daemon=True).start()

def _apply_app_icon_mac():
    try:
        from AppKit import NSApplication, NSImage
    except Exception:
        return
    path = None
    for cand in ("logo.png", "logo.icns"):
        p = find_data(cand)
        if os.path.isfile(p):
            path = p
            break
    if not path: return
    try:
        img = NSImage.alloc().initWithContentsOfFile_(path)
        if img:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception: pass

# ============================================================================
# 13. CLI-РЕЖИМ (для CEP/скриптов/батчников)
# ============================================================================
_CLI_HELP = ("MetaMask US CLI\n"
             "Использование: MetaMaskUS [--progress] [change|clean] \"путь\" [\"путь2\" ...]\n"
             "  change  - подмена метаданных (по умолчанию)\n"
             "  clean   - полное стирание метаданных\n"
             "Вывод: по одной JSON-строке на файл; с --progress дополнительно строки 'PROGRESS <путь> <%%>'")

def _cli_main(argv):
    mode, progress, paths = 'change', False, []
    for a in argv:
        if a == '--progress': progress = True
        elif a in ('change', 'clean'): mode = a
        elif a in ('-h', '--help'):
            print(_CLI_HELP); return 0
        else: paths.append(a)
    if not paths:
        print(_CLI_HELP); return 2
    ensure_tools()
    code = 0
    for p in paths:
        valid, err = validate_media_file(p)
        if err:
            print(json.dumps({"ok": False, "path": p, "error": err}, ensure_ascii=False)); code = 1; continue
        try:
            def cb(pct, _p=p):
                if progress: print(f"PROGRESS {_p} {int(pct)}", flush=True)
            out = process_media(valid, cb, mode)
            print(json.dumps({"ok": True, "path": p, "output": out, "mode": mode}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"ok": False, "path": p, "error": str(e)}, ensure_ascii=False)); code = 1
    return code

# ============================================================================
# 14. СТАРТ
# ============================================================================
def _start(window):
    threading.Thread(target=ensure_tools, daemon=True).start()
    def delayed():
        time.sleep(1.0)
        _enable_drop(window)
    threading.Thread(target=delayed, daemon=True).start()

def main():
    import webview
    api = Api()
    html_path = find_data(HTML_FILE)
    kwargs = dict(width=680, height=640, min_size=(520, 480), resizable=True,
                  js_api=api, background_color="#F4F5F8")
    if os.path.isfile(html_path):
        window = webview.create_window(APP_TITLE, url=html_path, **kwargs)
    else:
        window = webview.create_window(
            APP_TITLE,
            html="<h2 style='font-family:Segoe UI'>Не найден файл интерфейса</h2><p>" + html_path + "</p>",
            **kwargs)
    api._window = window
    try:
        window.events.loaded += lambda: _enable_drop(window)
        window.events.closing += lambda: kill_all_processes()
        window.events.closed += lambda: kill_all_processes()
    except Exception: pass
    if IS_WIN:
        _apply_window_icon_win()
        webview.start(_start, window, gui="edgechromium")
    else:
        _apply_app_icon_mac()          # macOS: иконка в доке
        webview.start(_start, window)  # macOS: системный WebKit

def _log_crash():
    """Пишет traceback в <app_data>/error.log (в релизе консоли нет)."""
    import traceback
    try:
        d = _app_data_root()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "error.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + traceback.format_exc() + "\n")
    except Exception: pass

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(_cli_main(sys.argv[1:]))   # CLI-режим
    try:
        main()
    except KeyboardInterrupt:
        kill_all_processes()
        sys.exit(0)
    except BaseException:
        _log_crash()
        kill_all_processes()
        raise