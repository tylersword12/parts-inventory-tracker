"""
Parts Inventory Tracker - Pricing Import
Reads vendor spreadsheets with user-configured column mappings.
Supports autocomplete for part number fields.
"""
import csv
import json
import os
from dataclasses import dataclass, asdict
from openpyxl import load_workbook


@dataclass
class PricingEntry:
    vendor_file: str
    vendor_name: str
    part_number: str
    description: str
    cost_price: float
    list_price: float
    row_index: int


@dataclass
class SheetMapping:
    """Saved column mapping for a single spreadsheet."""
    filename: str
    sheet_name: str       # xlsx sheet name, or "" for csv
    header_row: int       # 0-based index of the header row
    part_number_col: int  # 0-based column index, -1 = not mapped
    description_col: int
    cost_col: int
    list_col: int
    enabled: bool = True


class PricingImporter:

    MAPPINGS_FILE = "pricing_mappings.json"

    def __init__(self, pricing_folder: str):
        self.pricing_folder = pricing_folder
        self._cache: dict[str, list[PricingEntry]] = {}
        self._mappings: dict[str, SheetMapping] = {}
        self._all_entries_cache: list[PricingEntry] | None = None
        self._load_mappings()

    # ── Mappings persistence ───────────────────────────────────────────

    def _mappings_path(self) -> str:
        return os.path.join(self.pricing_folder, self.MAPPINGS_FILE)

    def _load_mappings(self):
        path = self._mappings_path()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for key, m in data.items():
                    self._mappings[key] = SheetMapping(**m)
            except Exception:
                pass

    def _save_mappings(self):
        path = self._mappings_path()
        data = {}
        for key, m in self._mappings.items():
            data[key] = asdict(m)
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save mappings: {e}")

    def get_mapping(self, filename: str, sheet_name: str = "") -> SheetMapping | None:
        key = f"{filename}::{sheet_name}"
        return self._mappings.get(key)

    def set_mapping(self, mapping: SheetMapping):
        key = f"{mapping.filename}::{mapping.sheet_name}"
        self._mappings[key] = mapping
        self._save_mappings()
        # Clear caches so next load uses new mapping
        self._cache.pop(mapping.filename, None)
        self._all_entries_cache = None

    def delete_mapping(self, filename: str, sheet_name: str = ""):
        key = f"{filename}::{sheet_name}"
        self._mappings.pop(key, None)
        self._save_mappings()
        self._cache.pop(filename, None)
        self._all_entries_cache = None

    def get_all_mappings(self) -> dict[str, SheetMapping]:
        return dict(self._mappings)

    # ── File listing ───────────────────────────────────────────────────

    def get_spreadsheet_files(self) -> list[str]:
        if not os.path.isdir(self.pricing_folder):
            return []
        files = []
        for f in os.listdir(self.pricing_folder):
            if f.lower().endswith((".xlsx", ".csv", ".xls")) and \
               not f.startswith("~") and f != self.MAPPINGS_FILE:
                files.append(f)
        return sorted(files)

    # ── Read raw headers from a file ───────────────────────────────────

    def read_headers(self, filename: str, sheet_name: str = "",
                     max_scan_rows: int = 10) -> tuple[list[str], list[list[str]]]:
        """Read column headers and sample data rows from a spreadsheet.

        Returns:
            (headers, sample_rows) where headers is a list of column header
            strings and sample_rows is a list of the first few data rows
            (each row is a list of string cell values).
        """
        filepath = os.path.join(self.pricing_folder, filename)
        if not os.path.exists(filepath):
            return [], []

        if filepath.lower().endswith(".csv"):
            return self._read_csv_headers(filepath, max_scan_rows)
        else:
            return self._read_xlsx_headers(filepath, sheet_name, max_scan_rows)

    def _read_xlsx_headers(self, filepath, sheet_name, max_rows):
        try:
            wb = load_workbook(filepath, read_only=True, data_only=True)
            if sheet_name and sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            else:
                ws = wb[wb.sheetnames[0]]

            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= max_rows + 5:
                    break
                rows.append([str(c) if c is not None else "" for c in row])
            wb.close()

            if not rows:
                return [], []

            # First row as headers by default
            headers = rows[0] if rows else []
            samples = rows[1:max_rows + 1] if len(rows) > 1 else []
            return headers, samples
        except Exception as e:
            print(f"Error reading headers from {filepath}: {e}")
            return [], []

    def _read_csv_headers(self, filepath, max_rows):
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = []
                for i, row in enumerate(reader):
                    if i >= max_rows + 5:
                        break
                    rows.append(row)

            if not rows:
                return [], []

            headers = rows[0]
            samples = rows[1:max_rows + 1] if len(rows) > 1 else []
            return headers, samples
        except Exception as e:
            print(f"Error reading headers from {filepath}: {e}")
            return [], []

    def get_xlsx_sheet_names(self, filename: str) -> list[str]:
        filepath = os.path.join(self.pricing_folder, filename)
        if not filepath.lower().endswith(".xlsx"):
            return []
        try:
            wb = load_workbook(filepath, read_only=True)
            names = wb.sheetnames
            wb.close()
            return names
        except Exception:
            return []

    # ── Load data using saved mappings ─────────────────────────────────

    def _parse_price(self, value) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().replace("$", "").replace(",", "")
        try:
            return float(s)
        except ValueError:
            return 0.0

    def load_spreadsheet(self, filename: str) -> list[PricingEntry]:
        if filename in self._cache:
            return self._cache[filename]

        filepath = os.path.join(self.pricing_folder, filename)
        if not os.path.exists(filepath):
            return []

        entries = []
        vendor_name = os.path.splitext(filename)[0]

        # Find all mappings for this file
        file_mappings = [m for m in self._mappings.values()
                         if m.filename == filename and m.enabled]

        if not file_mappings:
            # No mapping configured — skip this file
            self._cache[filename] = []
            return []

        if filepath.lower().endswith(".csv"):
            for mapping in file_mappings:
                entries.extend(self._load_csv_mapped(filepath, filename,
                                                     vendor_name, mapping))
        else:
            for mapping in file_mappings:
                entries.extend(self._load_xlsx_mapped(filepath, filename,
                                                      vendor_name, mapping))

        self._cache[filename] = entries
        return entries

    def _load_xlsx_mapped(self, filepath, filename, vendor_name, mapping):
        entries = []
        try:
            wb = load_workbook(filepath, read_only=True, data_only=True)
            sheet = mapping.sheet_name or wb.sheetnames[0]
            if sheet not in wb.sheetnames:
                wb.close()
                return entries

            ws = wb[sheet]
            rows = list(ws.iter_rows(values_only=True))
            wb.close()

            if not rows:
                return entries

            data_start = mapping.header_row + 1
            for row_idx, row in enumerate(rows[data_start:], start=data_start + 1):
                cells = list(row)
                entry = self._row_to_entry(cells, mapping, filename, vendor_name,
                                           row_idx)
                if entry:
                    entries.append(entry)
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
        return entries

    def _load_csv_mapped(self, filepath, filename, vendor_name, mapping):
        entries = []
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))

            data_start = mapping.header_row + 1
            for row_idx, row in enumerate(rows[data_start:], start=data_start + 1):
                entry = self._row_to_entry(row, mapping, filename, vendor_name,
                                           row_idx)
                if entry:
                    entries.append(entry)
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
        return entries

    def _row_to_entry(self, cells, mapping, filename, vendor_name, row_idx):
        """Convert a row to a PricingEntry using the mapping."""
        pn_col = mapping.part_number_col
        if pn_col < 0 or pn_col >= len(cells):
            return None

        pn = str(cells[pn_col] or "").strip()
        if not pn or pn.lower() in ("none", "nan", ""):
            return None

        desc = ""
        if 0 <= mapping.description_col < len(cells):
            desc = str(cells[mapping.description_col] or "").strip()

        cost = 0.0
        if 0 <= mapping.cost_col < len(cells):
            cost = self._parse_price(cells[mapping.cost_col])

        list_p = 0.0
        if 0 <= mapping.list_col < len(cells):
            list_p = self._parse_price(cells[mapping.list_col])

        return PricingEntry(
            vendor_file=filename,
            vendor_name=vendor_name,
            part_number=pn,
            description=desc,
            cost_price=cost,
            list_price=list_p,
            row_index=row_idx,
        )

    # ── Search & Autocomplete ──────────────────────────────────────────

    def _get_all_entries(self) -> list[PricingEntry]:
        """Load and cache all entries from all configured spreadsheets."""
        if self._all_entries_cache is not None:
            return self._all_entries_cache

        all_entries = []
        for filename in self.get_spreadsheet_files():
            all_entries.extend(self.load_spreadsheet(filename))
        self._all_entries_cache = all_entries
        return all_entries

    def find_pricing(self, part_number: str,
                     vendor_filter: str = "") -> list[PricingEntry]:
        """Search all configured spreadsheets for a part number."""
        part_number = part_number.strip().lower()
        results = []
        for entry in self._get_all_entries():
            if vendor_filter and vendor_filter.lower() not in entry.vendor_name.lower():
                continue
            if part_number in entry.part_number.lower():
                results.append(entry)
        return results

    def autocomplete(self, query: str, limit: int = 15) -> list[PricingEntry]:
        """Return matching entries for autocomplete dropdown."""
        query = query.strip().lower()
        if len(query) < 2:
            return []

        results = []
        seen = set()
        for entry in self._get_all_entries():
            if query in entry.part_number.lower() or query in entry.description.lower():
                # Deduplicate by part number
                if entry.part_number.lower() not in seen:
                    seen.add(entry.part_number.lower())
                    results.append(entry)
                    if len(results) >= limit:
                        break
        return results

    def clear_cache(self):
        self._cache.clear()
        self._all_entries_cache = None
