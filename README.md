# Parts Inventory Tracker

A dark-themed Python desktop app for managing shop parts inventory with barcode scanning, vendor pricing import, Dymo LabelWriter 550 label printing, and a dedicated full-screen Scan Station for the Panasonic CF-33 tablet.

## Features

- **Dashboard** — Quick-access tiles with live inventory stats
- **Parts Inventory** — Full CRUD with MFG part number, internal QuickBooks part number, vendor, pricing, quantity tracking, and min-stock alerts
- **Location Management** — Cabinet → Shelf → Bin hierarchy
- **Inline Scanner** — Barcode scanner support via keyboard wedge mode (works with any USB barcode scanner)
- **Scan Station** — Dedicated full-screen check-in/check-out mode: scan → view part → withdraw/restock. Session history log, quick-quantity buttons, optimized for the shop floor
- **Tablet / Desktop Toggle** — Switch between compact desktop UI and touch-friendly tablet UI with larger buttons, text, and input fields
- **Vendor Pricing Import** — Point to a server folder of .xlsx/.csv price lists. Auto-detects column headers
- **Label Printing** — Code128 barcode labels for Dymo LabelWriter 550
- **Multi-Station Access** — Shared JSON database on your server with file locking

## Quick Start

### 1. Install Python 3.10+

### 2. Install Dependencies
```
pip install -r requirements.txt
```

### 3. Run
```
python app.py
```

### 4. First-Time Setup
1. Click **Settings** on the dashboard
2. Set **Database File Path** — browse to a shared server location
   - UNC path: `\\SERVER\share\parts_inventory.json`
   - Mapped drive: `Z:\parts_inventory.json`
3. Set **Pricing Spreadsheets Folder** if you have vendor price lists
4. Select your **Dymo LabelWriter 550** printer
5. Toggle **Tablet Mode** if running on the CF-33
6. Click **Save Settings**

### 5. Deploy to Other Stations
Copy the `parts_tracker` folder to each workstation. Point all to the **same** JSON file.

## Scan Station (CF-33 Tablet)

The Scan Station is a dedicated full-screen mode for the Panasonic CF-33:

1. Click **Scan Station** on the dashboard (or any station)
2. The screen goes full-screen with a large scan input, part detail view, and activity log
3. Scan a barcode with the CF-33's integrated scanner — it auto-detects the input
4. Part details appear immediately with current quantity
5. Tap a quick-quantity button (1, 5, 10, 25) or type a custom amount
6. Hit **WITHDRAW** or **RESTOCK** — the screen flashes to confirm
7. Optionally enter a job number or reason
8. Scan the next barcode — repeat
9. Press **Escape** or **Exit** to return to the dashboard

The barcode scanner works in keyboard wedge mode — it types the barcode characters followed by Enter. This is compatible with any USB barcode scanner including the Panasonic CF-33's integrated scanner.

## File Structure

```
parts_tracker/
├── app.py               # Main application & UI
├── config.py            # Configuration, theme, tablet/desktop scaling
├── inventory_db.py      # JSON database with file locking
├── barcode_manager.py   # Barcode generation & Dymo printing
├── pricing_import.py    # Vendor spreadsheet import
├── scan_station.py      # Full-screen scan station module
├── requirements.txt     # Python dependencies
├── app_config.json      # Local settings (auto-created)
└── labels/              # Generated barcode label images
```

## Releases & Auto-Update (GitHub)

The .exe is built by GitHub Actions on a Windows machine and published as a
GitHub Release. Every installed copy checks for a newer release when it starts
and offers a one-click update.

**Publishing a new version:**
1. Make your code changes
2. Bump `APP_VERSION` in `version.py` (e.g. `1.0.0` → `1.0.1`)
3. Optionally edit `RELEASE_NOTES.md` — shown to users in the update popup
4. Push to the `main` branch

GitHub builds `PartsInventory.exe` (~3–5 min) and publishes release `v1.0.1`.
Pushes that don't change `version.py` don't trigger a release.

**Notes**
- The repository must be **public** for auto-update to work (the app checks
  GitHub without logging in). Your inventory data and settings are never
  uploaded — they stay on your server and in `app_config.json`.
- Keep the .exe in a folder the user can write to (Desktop, Documents,
  `C:\PartsInventory`) — not `Program Files` — so it can replace itself.
- Updates can be turned off per machine in **Settings → Updates**.

## Building a Windows Executable Locally

```
python build_exe.py
```
