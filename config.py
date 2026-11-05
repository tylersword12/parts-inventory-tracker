"""
Parts Inventory Tracker - Configuration & Theme
"""
import json
import os
import sys


def _get_app_dir() -> str:
    """Get the real app directory — works as .py and as PyInstaller .exe."""
    if getattr(sys, 'frozen', False):
        # Running as compiled .exe — use the folder the .exe is in
        return os.path.dirname(sys.executable)
    else:
        # Running as .py script
        return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _get_app_dir()
LABELS_DIR = os.path.join(APP_DIR, "labels")
CONFIG_FILE = os.path.join(APP_DIR, "app_config.json")

DEFAULT_CONFIG = {
    "inventory_json_path": "",
    "pricing_folder_path": "",
    "dymo_printer_name": "",
    "label_width_mm": 54,
    "label_height_mm": 25,
    "barcode_type": "code128",
    "company_name": "",
    "tablet_mode": False,
    "auto_update_check": True,
    "scanner_suffix": "\r",
}

# ── Desktop vs Tablet scaling ─────────────────────────────────────────
SCALE = {
    "desktop": {
        "font_title": ("Segoe UI Semibold", 20),
        "font_heading": ("Segoe UI Semibold", 18),
        "font_normal": ("Segoe UI", 13),
        "font_small": ("Segoe UI", 11),
        "font_table": ("Segoe UI", 12),
        "font_table_header": ("Segoe UI Semibold", 11),
        "font_button": ("Segoe UI Semibold", 14),
        "font_scan_big": ("Segoe UI Bold", 72),
        "font_scan_qty": ("Segoe UI Bold", 28),
        "font_scan_info": ("Segoe UI", 15),
        "font_scan_label": ("Segoe UI Semibold", 16),
        "font_stat_value": ("Segoe UI Bold", 22),
        "font_stat_label": ("Segoe UI", 11),
        "font_tile_icon": ("Segoe UI", 48),
        "font_tile_title": ("Segoe UI Semibold", 18),
        "font_tile_sub": ("Segoe UI", 12),
        "row_height": 34,
        "header_height": 36,
        "btn_height": 40,
        "entry_height": 40,
        "tile_pad": 10,
        "tile_cols": 3,
        "scan_qty_entry_h": 50,
        "scan_qty_font": 24,
    },
    "tablet": {
        "font_title": ("Segoe UI Semibold", 28),
        "font_heading": ("Segoe UI Semibold", 24),
        "font_normal": ("Segoe UI", 18),
        "font_small": ("Segoe UI", 15),
        "font_table": ("Segoe UI", 17),
        "font_table_header": ("Segoe UI Semibold", 15),
        "font_button": ("Segoe UI Semibold", 20),
        "font_scan_big": ("Segoe UI Bold", 96),
        "font_scan_qty": ("Segoe UI Bold", 48),
        "font_scan_info": ("Segoe UI", 22),
        "font_scan_label": ("Segoe UI Semibold", 22),
        "font_stat_value": ("Segoe UI Bold", 30),
        "font_stat_label": ("Segoe UI", 15),
        "font_tile_icon": ("Segoe UI", 64),
        "font_tile_title": ("Segoe UI Semibold", 24),
        "font_tile_sub": ("Segoe UI", 16),
        "row_height": 52,
        "header_height": 48,
        "btn_height": 56,
        "entry_height": 52,
        "tile_pad": 14,
        "tile_cols": 3,
        "scan_qty_entry_h": 80,
        "scan_qty_font": 44,
    },
}

COLORS = {
    "bg_dark":       "#1a1a2e",
    "bg_card":       "#16213e",
    "bg_card_hover": "#1f3460",
    "bg_input":      "#0f3460",
    "accent":        "#e94560",
    "accent_hover":  "#ff6b81",
    "text_primary":  "#eaeaea",
    "text_secondary":"#a0a0b0",
    "text_muted":    "#6c6c80",
    "success":       "#2ed573",
    "success_hover": "#7bed9f",
    "warning":       "#ffa502",
    "danger":        "#ff4757",
    "danger_hover":  "#ff6b6b",
    "border":        "#2a2a4a",
    "table_row_alt": "#1b2a4a",
    "table_header":  "#0f3460",
    "scan_bg":       "#0d1117",
    "scan_card":     "#161b22",
    "scan_success":  "#1a4d2e",
    "scan_danger":   "#4d1a1a",
}

DASHBOARD_TILES = [
    {"id": "parts",     "title": "Parts Inventory", "subtitle": "Add, edit, search parts",      "icon": "📦", "color": "#e94560"},
    {"id": "locations", "title": "Locations",        "subtitle": "Cabinets, shelves, bins",      "icon": "🗄️", "color": "#0f3460"},
    {"id": "scanner",   "title": "Scan Parts",       "subtitle": "Scan barcode to withdraw",     "icon": "📷", "color": "#2ed573"},
    {"id": "scan_station","title":"Scan Station",     "subtitle": "Full-screen check in/out",     "icon": "🖥️", "color": "#7c5cfc"},
    {"id": "pricing",   "title": "Pricing Import",    "subtitle": "Load vendor price lists",      "icon": "💲", "color": "#ffa502"},
    {"id": "labels",    "title": "Print Labels",      "subtitle": "Generate & print barcodes",    "icon": "🏷️", "color": "#00b894"},
    {"id": "settings",  "title": "Settings",          "subtitle": "Paths, printer, config",       "icon": "⚙️", "color": "#6c6c80"},
]


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config.update(json.load(f))
        except Exception:
            pass
    return config


def save_config(config: dict):
    os.makedirs(os.path.dirname(CONFIG_FILE) or ".", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def ensure_dirs():
    """Create required directories if they don't exist."""
    os.makedirs(LABELS_DIR, exist_ok=True)


ensure_dirs()


def get_scale(tablet_mode: bool) -> dict:
    return SCALE["tablet"] if tablet_mode else SCALE["desktop"]
