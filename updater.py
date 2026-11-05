"""
Parts Inventory Tracker - Auto Updater
Checks GitHub Releases for a newer version, downloads the new .exe,
and swaps it in place of the running one.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

from version import APP_VERSION, GITHUB_REPO

ASSET_NAME = "PartsInventory.exe"
USER_AGENT = f"PartsInventory-Updater/{APP_VERSION}"


def is_frozen() -> bool:
    """True when running as the compiled .exe (updates only apply then)."""
    return bool(getattr(sys, "frozen", False))


def parse_version(v: str) -> tuple:
    """'v1.2.10' -> (1, 2, 10). Non-numeric parts count as 0."""
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class UpdateInfo:
    def __init__(self, version: str, download_url: str, notes: str,
                 size: int):
        self.version = version
        self.download_url = download_url
        self.notes = notes
        self.size = size


def check_for_update(timeout: int = 10) -> UpdateInfo | None:
    """Return UpdateInfo if GitHub has a newer release, else None.
    Raises on network/API errors so callers can decide to stay quiet."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    tag = data.get("tag_name", "")
    if not tag or parse_version(tag) <= parse_version(APP_VERSION):
        return None

    for asset in data.get("assets", []):
        if asset.get("name", "").lower() == ASSET_NAME.lower():
            return UpdateInfo(
                version=tag.lstrip("vV"),
                download_url=asset["browser_download_url"],
                notes=(data.get("body") or "").strip(),
                size=int(asset.get("size", 0)),
            )
    return None


def download_update(info: UpdateInfo, progress_cb=None) -> str:
    """Download the new .exe next to the current one. Returns its path.
    progress_cb(bytes_done, bytes_total) is called while downloading."""
    target_dir = os.path.dirname(sys.executable) if is_frozen() \
        else tempfile.gettempdir()
    new_path = os.path.join(target_dir, "PartsInventory_update.exe")

    req = urllib.request.Request(info.download_url,
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or info.size or 0)
        done = 0
        with open(new_path, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)

    # Sanity checks: complete download and a real Windows executable
    size = os.path.getsize(new_path)
    with open(new_path, "rb") as f:
        magic = f.read(2)
    if magic != b"MZ" or (total and size != total) or size < 1_000_000:
        try:
            os.remove(new_path)
        except OSError:
            pass
        raise RuntimeError("Downloaded update is incomplete or invalid.")
    return new_path


def apply_update_and_restart(new_exe: str):
    """Replace the running .exe with new_exe and relaunch it.
    The caller must exit the app right after this returns."""
    if not is_frozen():
        raise RuntimeError("Updates can only be applied to the compiled .exe.")

    current = sys.executable
    pid = os.getpid()
    script = os.path.join(tempfile.gettempdir(), "parts_inventory_update.bat")

    # Wait for this process to exit, swap files (retrying in case Windows
    # still has the file locked), relaunch, then delete this script.
    with open(script, "w") as f:
        f.write(f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait
)
set tries=0
:swap
move /Y "{new_exe}" "{current}" >NUL 2>&1
if errorlevel 1 (
    set /a tries+=1
    if %tries% LSS 15 (
        timeout /t 1 /nobreak >NUL
        goto swap
    )
)
start "" "{current}"
del "%~f0"
""")

    flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(["cmd", "/c", script], creationflags=flags,
                     close_fds=True)


def cleanup_leftovers():
    """Remove a stale downloaded update if a previous swap didn't finish."""
    if not is_frozen():
        return
    stale = os.path.join(os.path.dirname(sys.executable),
                         "PartsInventory_update.exe")
    if os.path.exists(stale):
        try:
            os.remove(stale)
        except OSError:
            pass
