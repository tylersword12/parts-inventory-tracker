"""
Parts Inventory Tracker - Database Layer
Shared JSON file with cross-process file locking.
"""
import json
import os
import time
import uuid
from datetime import datetime
from filelock import FileLock, Timeout


# ── Schema ─────────────────────────────────────────────────────────────
def _empty_db() -> dict:
    return {
        "meta": {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
        },
        "locations": {},   # id -> {cabinet, shelf, bin, description}
        "parts": {},       # id -> {part record}
        "history": [],     # withdrawal / addition log entries
    }


class InventoryDB:
    """Thread-safe, file-locked JSON database for shared network access."""

    def __init__(self, json_path: str):
        self.json_path = json_path
        self.lock_path = json_path + ".lock"
        self.lock = FileLock(self.lock_path, timeout=10)
        self._ensure_file()

    # ── File I/O ───────────────────────────────────────────────────────
    def _ensure_file(self):
        if not os.path.exists(self.json_path):
            dir_path = os.path.dirname(self.json_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            self._write(_empty_db())

    def _read(self) -> dict:
        try:
            with self.lock:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            db = _empty_db()
            self._write(db)
            return db
        except Timeout:
            raise RuntimeError(
                "Could not acquire database lock. Another station may be "
                "performing a long write. Try again in a moment."
            )

    def _write(self, data: dict):
        try:
            with self.lock:
                data["meta"]["last_modified"] = datetime.now().isoformat()
                tmp = self.json_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                # Atomic rename (works on Windows for same-volume)
                if os.path.exists(self.json_path):
                    os.replace(tmp, self.json_path)
                else:
                    os.rename(tmp, self.json_path)
        except Timeout:
            raise RuntimeError("Could not acquire database lock for writing.")

    def _atomic_update(self, updater):
        """Read-modify-write with lock held for the entire operation."""
        try:
            with self.lock:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                result = updater(data)
                data["meta"]["last_modified"] = datetime.now().isoformat()
                tmp = self.json_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                if os.path.exists(self.json_path):
                    os.replace(tmp, self.json_path)
                else:
                    os.rename(tmp, self.json_path)
                return result
        except Timeout:
            raise RuntimeError("Could not acquire database lock.")

    # ── Locations ──────────────────────────────────────────────────────
    def get_locations(self) -> dict:
        return self._read().get("locations", {})

    def add_location(self, cabinet: str, shelf: str, bin_label: str,
                     description: str = "") -> str:
        loc_id = f"LOC-{uuid.uuid4().hex[:8].upper()}"
        loc = {
            "id": loc_id,
            "cabinet": cabinet.strip(),
            "shelf": shelf.strip(),
            "bin": bin_label.strip(),
            "description": description.strip(),
            "created": datetime.now().isoformat(),
        }

        def _update(data):
            data["locations"][loc_id] = loc
            return loc_id

        return self._atomic_update(_update)

    def update_location(self, loc_id: str, **fields):
        def _update(data):
            if loc_id in data["locations"]:
                data["locations"][loc_id].update(fields)
        self._atomic_update(_update)

    def delete_location(self, loc_id: str):
        def _update(data):
            data["locations"].pop(loc_id, None)
        self._atomic_update(_update)

    def get_location_display(self, loc_id: str) -> str:
        """Return a human-readable string for a location."""
        locs = self.get_locations()
        loc = locs.get(loc_id)
        if not loc:
            return "Unassigned"
        return f"{loc['cabinet']} → {loc['shelf']} → {loc['bin']}"

    # ── Parts ──────────────────────────────────────────────────────────
    def get_parts(self) -> dict:
        return self._read().get("parts", {})

    def get_part_by_barcode(self, barcode: str) -> dict | None:
        """Look up a part by its barcode value.
        Case-insensitive and whitespace-tolerant, because keyboard-wedge
        scanners type inverted case when Caps Lock is on."""
        key = (barcode or "").strip().upper()
        if not key:
            return None
        parts = self.get_parts()
        for part in parts.values():
            if (part.get("barcode") or "").strip().upper() == key:
                return part
        # Fall back to matching the internal or MFG part number directly,
        # so manufacturer barcodes on parts can be scanned too.
        for part in parts.values():
            if (part.get("internal_part_number") or "").strip().upper() == key \
               or (part.get("mfg_part_number") or "").strip().upper() == key:
                return part
        return None

    def add_part(self, mfg_part_number: str, internal_part_number: str,
                 description: str = "", location_id: str = "",
                 quantity: int = 0, min_quantity: int = 0,
                 cost_price: float = 0.0, list_price: float = 0.0,
                 vendor: str = "", notes: str = "",
                 category: str = "") -> str:
        part_id = f"PRT-{uuid.uuid4().hex[:8].upper()}"
        barcode_value = f"INV-{internal_part_number or mfg_part_number}-{part_id[-4:]}"
        part = {
            "id": part_id,
            "mfg_part_number": mfg_part_number.strip(),
            "internal_part_number": internal_part_number.strip(),
            "description": description.strip(),
            "location_id": location_id,
            "quantity": quantity,
            "min_quantity": min_quantity,
            "cost_price": cost_price,
            "list_price": list_price,
            "vendor": vendor.strip(),
            "notes": notes.strip(),
            "category": category.strip(),
            "barcode": barcode_value,
            "created": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
        }

        def _update(data):
            data["parts"][part_id] = part
            return part_id

        return self._atomic_update(_update)

    def update_part(self, part_id: str, **fields):
        def _update(data):
            if part_id in data["parts"]:
                fields["last_modified"] = datetime.now().isoformat()
                data["parts"][part_id].update(fields)
        self._atomic_update(_update)

    def delete_part(self, part_id: str):
        def _update(data):
            data["parts"].pop(part_id, None)
        self._atomic_update(_update)

    def adjust_quantity(self, part_id: str, delta: int,
                        reason: str = "", user: str = ""):
        """Add or subtract quantity and log to history."""
        def _update(data):
            if part_id not in data["parts"]:
                return False
            part = data["parts"][part_id]
            old_qty = part["quantity"]
            part["quantity"] = max(0, old_qty + delta)
            part["last_modified"] = datetime.now().isoformat()
            entry = {
                "timestamp": datetime.now().isoformat(),
                "part_id": part_id,
                "mfg_part_number": part["mfg_part_number"],
                "internal_part_number": part["internal_part_number"],
                "action": "withdraw" if delta < 0 else "restock",
                "delta": delta,
                "old_quantity": old_qty,
                "new_quantity": part["quantity"],
                "reason": reason,
                "user": user,
            }
            data["history"].append(entry)
            return part["quantity"]

        return self._atomic_update(_update)

    # ── History ────────────────────────────────────────────────────────
    def get_history(self, limit: int = 200) -> list:
        db = self._read()
        history = db.get("history", [])
        return history[-limit:]

    # ── Search ─────────────────────────────────────────────────────────
    def search_parts(self, query: str) -> list:
        query = query.lower().strip()
        results = []
        for part in self.get_parts().values():
            searchable = " ".join([
                part.get("mfg_part_number", ""),
                part.get("internal_part_number", ""),
                part.get("description", ""),
                part.get("vendor", ""),
                part.get("barcode", ""),
                part.get("category", ""),
                part.get("notes", ""),
            ]).lower()
            if query in searchable:
                results.append(part)
        return results

    # ── Stats ──────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        db = self._read()
        parts = db.get("parts", {})
        locations = db.get("locations", {})
        low_stock = [p for p in parts.values()
                     if p["quantity"] <= p.get("min_quantity", 0) and p.get("min_quantity", 0) > 0]
        total_value = sum(p["quantity"] * p.get("cost_price", 0) for p in parts.values())
        return {
            "total_parts": len(parts),
            "total_locations": len(locations),
            "low_stock_count": len(low_stock),
            "total_inventory_value": total_value,
            "history_entries": len(db.get("history", [])),
        }
