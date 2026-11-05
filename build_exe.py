"""
Build script - Creates a standalone Windows .exe
Run this on your Windows machine:
    python build_exe.py
"""
import subprocess
import sys
import os


def main():
    # Install PyInstaller if not present
    print("Checking for PyInstaller...")
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("  Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Install pywin32 for printer support
    try:
        import win32print
        print("  pywin32 found")
    except ImportError:
        print("  Installing pywin32 (for Dymo printer support)...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pywin32"])
        except Exception:
            print("  Warning: pywin32 install failed - printing may not work")

    # Make sure all app dependencies are installed
    print("\nInstalling app dependencies...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
    ])

    print("\nBuilding executable...")
    print("=" * 50)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "PartsInventory",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",

        # App entry point
        "app.py",

        # Include all app modules explicitly
        "--hidden-import", "config",
        "--hidden-import", "inventory_db",
        "--hidden-import", "barcode_manager",
        "--hidden-import", "pricing_import",
        "--hidden-import", "scan_station",
        "--hidden-import", "version",
        "--hidden-import", "updater",
        "--hidden-import", "scan_input",
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageTk",
        "--hidden-import", "PIL.ImageDraw",
        "--hidden-import", "PIL.ImageFont",
        "--hidden-import", "openpyxl",
        "--hidden-import", "filelock",
        "--hidden-import", "barcode",
        "--hidden-import", "barcode.codex",
        "--hidden-import", "barcode.writer",

        # Include customtkinter data files (themes, etc.)
        "--collect-data", "customtkinter",

        # Include python-barcode's bundled font (fixes "cannot open resource")
        "--collect-data", "barcode",

        # Add all .py files in the project as data files so
        # PyInstaller bundles them even though they're imported dynamically
        "--add-data", f"config.py{os.pathsep}.",
        "--add-data", f"inventory_db.py{os.pathsep}.",
        "--add-data", f"barcode_manager.py{os.pathsep}.",
        "--add-data", f"pricing_import.py{os.pathsep}.",
        "--add-data", f"scan_station.py{os.pathsep}.",
    ]

    subprocess.check_call(cmd)

    exe_path = os.path.join("dist", "PartsInventory.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print("\n" + "=" * 50)
        print(f"  BUILD SUCCESSFUL")
        print(f"  Output: {os.path.abspath(exe_path)}")
        print(f"  Size:   {size_mb:.1f} MB")
        print("=" * 50)
        print(f"\nCopy PartsInventory.exe to any Windows machine to run.")
        print(f"No Python installation needed on the target machine.")
        print(f"\nNote: On first run, create a 'labels' folder next to")
        print(f"the .exe if you want to generate barcode labels.")
    else:
        print("\nBuild failed - check the output above for errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
