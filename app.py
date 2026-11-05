"""
Parts Inventory Tracker - Main Application
Dark-themed dashboard UI with customtkinter.
"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageTk

from config import (COLORS, DASHBOARD_TILES, LABELS_DIR, load_config,
                    save_config, get_scale)
from inventory_db import InventoryDB
from barcode_manager import BarcodeManager
from pricing_import import PricingImporter
from scan_station import ScanStation
from scan_input import ScanDetector, clean_barcode
from version import APP_VERSION
import updater


# ── App Setup ──────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class InventoryApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title(f"Parts Inventory Tracker  v{APP_VERSION}")
        self.geometry("1280x800")
        self.minsize(1024, 700)
        self.configure(fg_color=COLORS["bg_dark"])

        # Load config
        self.config = load_config()

        # Tablet mode
        self.tablet_mode = self.config.get("tablet_mode", False)
        self.S = get_scale(self.tablet_mode)

        # Initialize subsystems (lazy - set up once paths configured)
        self.db: InventoryDB | None = None
        self.barcode_mgr: BarcodeManager | None = None
        self.pricing: PricingImporter | None = None
        self._init_subsystems()

        # Scanner state
        self._scan_buffer = ""
        self._scan_timer_id = None
        self._scanner_active = False

        # Navigation stack
        self._frame_stack: list[str] = []

        # Build UI
        self._build_header()
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # Show dashboard
        self.show_dashboard()

        # Bind global key events for scanner
        self.bind("<Key>", self._on_key)

        # Check GitHub for a newer version a few seconds after launch
        updater.cleanup_leftovers()
        if self.config.get("auto_update_check", True) and updater.is_frozen():
            self.after(3000, lambda: self._check_for_updates(silent=True))

    # ── Subsystem init ────────────────────────────────────────────────
    def _init_subsystems(self):
        path = self.config.get("inventory_json_path", "")
        if path:
            try:
                self.db = InventoryDB(path)
            except Exception as e:
                print(f"DB init error: {e}")

        self.barcode_mgr = BarcodeManager(
            LABELS_DIR,
            self.config.get("label_width_mm", 54),
            self.config.get("label_height_mm", 25),
        )

        pfolder = self.config.get("pricing_folder_path", "")
        if pfolder and os.path.isdir(pfolder):
            self.pricing = PricingImporter(pfolder)

    def _require_db(self) -> bool:
        if self.db is None:
            messagebox.showwarning(
                "Setup Required",
                "Please configure the inventory database path in Settings first."
            )
            self.show_settings()
            return False
        return True

    # ── Header ────────────────────────────────────────────────────────
    def _build_header(self):
        header = ctk.CTkFrame(self, height=60, fg_color=COLORS["bg_card"],
                              corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        self._back_btn = ctk.CTkButton(
            header, text="◀  Back", width=80, height=36,
            fg_color="transparent", hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"], font=("Segoe UI", 13),
            command=self._go_back,
        )
        self._back_btn.pack(side="left", padx=15, pady=12)
        self._back_btn.pack_forget()  # Hidden on dashboard

        title_label = ctk.CTkLabel(
            header, text="⚙  Parts Inventory Tracker",
            font=("Segoe UI Semibold", 20), text_color=COLORS["text_primary"],
        )
        title_label.pack(side="left", padx=(15, 6), pady=12)

        ctk.CTkLabel(
            header, text=f"v{APP_VERSION}",
            font=("Segoe UI", 12), text_color=COLORS["text_muted"],
        ).pack(side="left", pady=(16, 12))

        # Tablet mode toggle
        self._tablet_switch = ctk.CTkSwitch(
            header, text="Tablet Mode",
            font=("Segoe UI", 12), text_color=COLORS["text_secondary"],
            fg_color=COLORS["border"], progress_color=COLORS["accent"],
            command=self._toggle_tablet_mode,
        )
        if self.tablet_mode:
            self._tablet_switch.select()
        self._tablet_switch.pack(side="right", padx=10, pady=12)

        # Status indicator
        self._status_label = ctk.CTkLabel(
            header, text="", font=("Segoe UI", 12),
            text_color=COLORS["text_muted"],
        )
        self._status_label.pack(side="right", padx=20, pady=12)
        self._update_status()

    def _update_status(self):
        if self.db:
            stats = self.db.get_stats()
            txt = (f"📦 {stats['total_parts']} parts  |  "
                   f"🗄️ {stats['total_locations']} locations  |  "
                   f"⚠️ {stats['low_stock_count']} low stock")
            self._status_label.configure(text=txt)
        else:
            self._status_label.configure(text="⚠ No database connected")

    # ── Navigation ────────────────────────────────────────────────────
    def _clear_content(self):
        # Leaving any page turns off the Scan Parts listener; show_scanner()
        # turns it back on.
        self._scanner_active = False
        self._scan_buffer = ""
        for widget in self._content.winfo_children():
            widget.destroy()

    def _go_back(self):
        if self._frame_stack:
            self._frame_stack.pop()
        if self._frame_stack:
            target = self._frame_stack.pop()
            self._navigate(target)
        else:
            self.show_dashboard()

    def _toggle_tablet_mode(self):
        self.tablet_mode = self._tablet_switch.get() == 1
        self.config["tablet_mode"] = self.tablet_mode
        save_config(self.config)
        self.S = get_scale(self.tablet_mode)
        messagebox.showinfo("Tablet Mode",
            "Tablet mode " + ("enabled" if self.tablet_mode else "disabled") +
            ".\n\nRestart the app for all UI changes to take effect.\n"
            "The Scan Station always uses the current mode.")

    def _open_scan_station(self):
        if not self._require_db():
            return
        ScanStation(self, self.db, tablet_mode=self.tablet_mode)

    def _navigate(self, target: str):
        nav_map = {
            "dashboard": self.show_dashboard,
            "parts": self.show_parts,
            "locations": self.show_locations,
            "scanner": self.show_scanner,
            "scan_station": lambda: self._open_scan_station(),
            "pricing": self.show_pricing,
            "labels": self.show_labels,
            "settings": self.show_settings,
        }
        fn = nav_map.get(target)
        if fn:
            fn()

    def _show_back_button(self, show=True):
        if show:
            self._back_btn.pack(side="left", padx=15, pady=12)
        else:
            self._back_btn.pack_forget()

    # ══════════════════════════════════════════════════════════════════
    #  DASHBOARD
    # ══════════════════════════════════════════════════════════════════
    def show_dashboard(self):
        self._clear_content()
        self._frame_stack = ["dashboard"]
        self._show_back_button(False)
        self._update_status()

        # Stats bar
        if self.db:
            stats = self.db.get_stats()
            stats_frame = ctk.CTkFrame(self._content, fg_color=COLORS["bg_card"],
                                       corner_radius=12, height=70)
            stats_frame.pack(fill="x", pady=(0, 20))
            stats_frame.pack_propagate(False)

            stat_items = [
                ("Total Parts", str(stats["total_parts"]), COLORS["accent"]),
                ("Locations", str(stats["total_locations"]), COLORS["accent"]),
                ("Low Stock", str(stats["low_stock_count"]),
                 COLORS["danger"] if stats["low_stock_count"] > 0 else COLORS["success"]),
                ("Inventory Value",
                 f"${stats['total_inventory_value']:,.2f}", COLORS["warning"]),
            ]
            for label, value, color in stat_items:
                sf = ctk.CTkFrame(stats_frame, fg_color="transparent")
                sf.pack(side="left", expand=True, fill="both", padx=20, pady=10)
                ctk.CTkLabel(sf, text=value, font=("Segoe UI Bold", 22),
                             text_color=color).pack()
                ctk.CTkLabel(sf, text=label, font=("Segoe UI", 11),
                             text_color=COLORS["text_muted"]).pack()

        # Tile grid
        grid_frame = ctk.CTkFrame(self._content, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True)

        for i, tile in enumerate(DASHBOARD_TILES):
            row, col = divmod(i, 3)
            grid_frame.columnconfigure(col, weight=1)
            grid_frame.rowconfigure(row, weight=1)

            card = ctk.CTkFrame(grid_frame, fg_color=COLORS["bg_card"],
                                corner_radius=16, cursor="hand2")
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(expand=True)

            # Color accent bar
            accent_bar = ctk.CTkFrame(inner, width=50, height=4,
                                      fg_color=tile["color"], corner_radius=2)
            accent_bar.pack(pady=(0, 10))

            ctk.CTkLabel(inner, text=tile["icon"],
                         font=("Segoe UI", 48)).pack(pady=(5, 5))
            ctk.CTkLabel(inner, text=tile["title"],
                         font=("Segoe UI Semibold", 18),
                         text_color=COLORS["text_primary"]).pack()
            ctk.CTkLabel(inner, text=tile["subtitle"],
                         font=("Segoe UI", 12),
                         text_color=COLORS["text_muted"]).pack(pady=(2, 0))

            tile_id = tile["id"]
            for w in (card, inner):
                w.bind("<Button-1>", lambda e, t=tile_id: self._navigate(t))
                w.bind("<Enter>",
                       lambda e, c=card: c.configure(fg_color=COLORS["bg_card_hover"]))
                w.bind("<Leave>",
                       lambda e, c=card: c.configure(fg_color=COLORS["bg_card"]))
            # Also bind child labels
            for child in inner.winfo_children():
                child.bind("<Button-1>", lambda e, t=tile_id: self._navigate(t))

    # ══════════════════════════════════════════════════════════════════
    #  PARTS INVENTORY
    # ══════════════════════════════════════════════════════════════════
    def show_parts(self):
        if not self._require_db():
            return
        self._clear_content()
        self._frame_stack.append("parts")
        self._show_back_button(True)

        # Top bar: search + add button
        top = ctk.CTkFrame(self._content, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))

        self._parts_search_var = ctk.StringVar()
        search = ctk.CTkEntry(
            top, placeholder_text="🔍  Search parts (MFG #, internal #, description)...",
            textvariable=self._parts_search_var,
            width=500, height=40, font=("Segoe UI", 14),
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        )
        search.pack(side="left", padx=(0, 10))
        search.bind("<KeyRelease>", lambda e: self._refresh_parts_table())

        ctk.CTkButton(
            top, text="＋  Add Part", height=40, width=140,
            font=("Segoe UI Semibold", 14),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._show_add_part_dialog,
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            top, text="⟳  Refresh", height=40, width=100,
            font=("Segoe UI", 13), fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            command=self._refresh_parts_table,
        ).pack(side="left", padx=5)

        # Table
        self._parts_table_frame = ctk.CTkScrollableFrame(
            self._content, fg_color=COLORS["bg_card"], corner_radius=12,
        )
        self._parts_table_frame.pack(fill="both", expand=True)

        self._refresh_parts_table()

    def _refresh_parts_table(self):
        for w in self._parts_table_frame.winfo_children():
            w.destroy()

        # Header
        headers = ["Internal #", "MFG Part #", "Description", "Location",
                    "Qty", "Min", "Cost", "List", "Vendor", "Actions"]
        widths =  [100, 120, 180, 140, 50, 50, 70, 70, 100, 140]

        header_frame = ctk.CTkFrame(self._parts_table_frame,
                                    fg_color=COLORS["table_header"], height=36,
                                    corner_radius=8)
        header_frame.pack(fill="x", padx=5, pady=(5, 2))
        header_frame.pack_propagate(False)

        for h, w in zip(headers, widths):
            ctk.CTkLabel(header_frame, text=h, width=w,
                         font=("Segoe UI Semibold", 11),
                         text_color=COLORS["text_secondary"],
                         anchor="w").pack(side="left", padx=4)

        # Data rows
        query = self._parts_search_var.get() if hasattr(self, "_parts_search_var") else ""
        if query.strip():
            parts = self.db.search_parts(query)
        else:
            parts = list(self.db.get_parts().values())

        parts.sort(key=lambda p: p.get("internal_part_number", ""))

        for idx, part in enumerate(parts):
            bg = COLORS["table_row_alt"] if idx % 2 == 0 else COLORS["bg_card"]
            row_frame = ctk.CTkFrame(self._parts_table_frame, fg_color=bg,
                                     height=34, corner_radius=4)
            row_frame.pack(fill="x", padx=5, pady=1)
            row_frame.pack_propagate(False)

            loc_str = self.db.get_location_display(part.get("location_id", ""))
            qty = part.get("quantity", 0)
            min_qty = part.get("min_quantity", 0)
            qty_color = COLORS["danger"] if qty <= min_qty and min_qty > 0 else COLORS["text_primary"]

            vals = [
                part.get("internal_part_number", ""),
                part.get("mfg_part_number", ""),
                part.get("description", "")[:30],
                loc_str[:25],
                str(qty),
                str(min_qty),
                f"${part.get('cost_price', 0):.2f}",
                f"${part.get('list_price', 0):.2f}",
                part.get("vendor", "")[:15],
            ]

            for v, w, ci in zip(vals, widths, range(len(vals))):
                color = qty_color if ci == 4 else COLORS["text_primary"]
                ctk.CTkLabel(row_frame, text=v, width=w,
                             font=("Segoe UI", 12), text_color=color,
                             anchor="w").pack(side="left", padx=4)

            # Action buttons
            actions = ctk.CTkFrame(row_frame, fg_color="transparent", width=140)
            actions.pack(side="left", padx=4)

            pid = part["id"]
            ctk.CTkButton(
                actions, text="✏️", width=30, height=26,
                fg_color="transparent", hover_color=COLORS["bg_card_hover"],
                command=lambda p=pid: self._show_edit_part_dialog(p),
            ).pack(side="left", padx=2)
            ctk.CTkButton(
                actions, text="🏷️", width=30, height=26,
                fg_color="transparent", hover_color=COLORS["bg_card_hover"],
                command=lambda p=pid: self._generate_label(p),
            ).pack(side="left", padx=2)
            ctk.CTkButton(
                actions, text="🗑️", width=30, height=26,
                fg_color="transparent", hover_color=COLORS["danger"],
                command=lambda p=pid: self._delete_part(p),
            ).pack(side="left", padx=2)

        if not parts:
            ctk.CTkLabel(
                self._parts_table_frame,
                text="No parts found. Click '+ Add Part' to get started.",
                font=("Segoe UI", 14), text_color=COLORS["text_muted"],
            ).pack(pady=40)

    def _show_add_part_dialog(self):
        self._part_dialog("Add New Part")

    def _show_edit_part_dialog(self, part_id: str):
        parts = self.db.get_parts()
        part = parts.get(part_id)
        if part:
            self._part_dialog("Edit Part", part)

    def _part_dialog(self, title: str, existing: dict | None = None):
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("600x700")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.focus_force()

        scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        fields = {}

        def add_field(label, key, default="", row=None, width=540):
            ctk.CTkLabel(scroll, text=label, font=("Segoe UI Semibold", 12),
                         text_color=COLORS["text_secondary"], anchor="w"
                         ).pack(fill="x", pady=(8, 2))
            var = ctk.StringVar(value=str(existing.get(key, default)) if existing else default)
            entry = ctk.CTkEntry(scroll, textvariable=var, width=width, height=36,
                                 fg_color=COLORS["bg_input"],
                                 border_color=COLORS["border"],
                                 text_color=COLORS["text_primary"],
                                 font=("Segoe UI", 13))
            entry.pack(fill="x", pady=(0, 2))
            fields[key] = var
            return entry

        mfg_entry = add_field("MFG Part Number *", "mfg_part_number")
        internal_entry = add_field("Internal Part Number (QuickBooks) *", "internal_part_number")
        desc_entry = add_field("Description", "description")
        add_field("Vendor", "vendor")
        add_field("Category", "category")

        # ── Autocomplete for part numbers ──────────────────────────────
        self._autocomplete_popup = None
        self._ac_listbox = None

        def _do_autocomplete(event, entry_widget, field_key):
            """Show autocomplete dropdown as user types."""
            if self.pricing is None:
                return
            query = fields[field_key].get().strip()
            if len(query) < 2:
                _close_autocomplete()
                return

            results = self.pricing.autocomplete(query, limit=10)
            if not results:
                _close_autocomplete()
                return

            _close_autocomplete()

            # Create popup below the entry
            popup = tk.Toplevel(dialog)
            popup.withdraw()
            popup.overrideredirect(True)
            popup.configure(bg=COLORS["bg_input"])

            listbox = tk.Listbox(
                popup, bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                selectbackground=COLORS["accent"],
                selectforeground=COLORS["text_primary"],
                font=("Segoe UI", 12), borderwidth=1,
                relief="solid", highlightthickness=0,
                activestyle="none",
            )
            listbox.pack(fill="both", expand=True)

            for r in results:
                display = f"{r.part_number}  —  {r.description[:30]}  |  ${r.cost_price:.2f} / ${r.list_price:.2f}  ({r.vendor_name})"
                listbox.insert("end", display)

            def on_select(evt=None):
                sel = listbox.curselection()
                if sel:
                    entry = results[sel[0]]
                    fields["mfg_part_number"].set(entry.part_number)
                    if not fields["description"].get().strip():
                        fields["description"].set(entry.description)
                    if entry.vendor_name and not fields["vendor"].get().strip():
                        fields["vendor"].set(entry.vendor_name)
                    cost_var.set(f"{entry.cost_price:.2f}")
                    list_var.set(f"{entry.list_price:.2f}")
                _close_autocomplete()

            listbox.bind("<<ListboxSelect>>", on_select)
            listbox.bind("<Return>", on_select)

            # Position popup below entry
            x = entry_widget.winfo_rootx()
            y = entry_widget.winfo_rooty() + entry_widget.winfo_height()
            w = entry_widget.winfo_width()
            h = min(len(results) * 24 + 4, 250)
            popup.geometry(f"{w}x{h}+{x}+{y}")
            popup.deiconify()
            popup.lift()

            self._autocomplete_popup = popup
            self._ac_listbox = listbox

        def _close_autocomplete():
            if self._autocomplete_popup:
                try:
                    self._autocomplete_popup.destroy()
                except Exception:
                    pass
                self._autocomplete_popup = None
                self._ac_listbox = None

        mfg_entry.bind("<KeyRelease>", lambda e: _do_autocomplete(e, mfg_entry, "mfg_part_number"))
        internal_entry.bind("<KeyRelease>", lambda e: _do_autocomplete(e, internal_entry, "internal_part_number"))
        dialog.bind("<FocusOut>", lambda e: dialog.after(200, _close_autocomplete))
        dialog.protocol("WM_DELETE_WINDOW", lambda: (_close_autocomplete(), dialog.destroy()))

        # Location dropdown
        ctk.CTkLabel(scroll, text="Location (Cabinet → Shelf → Bin)",
                     font=("Segoe UI Semibold", 12),
                     text_color=COLORS["text_secondary"], anchor="w"
                     ).pack(fill="x", pady=(8, 2))
        locations = self.db.get_locations()
        loc_options = {"Unassigned": ""}
        for lid, loc in locations.items():
            label = f"{loc['cabinet']} → {loc['shelf']} → {loc['bin']}"
            loc_options[label] = lid

        current_loc = ""
        if existing:
            current_loc = existing.get("location_id", "")
        current_label = "Unassigned"
        for label, lid in loc_options.items():
            if lid == current_loc:
                current_label = label

        loc_var = ctk.StringVar(value=current_label)
        loc_menu = ctk.CTkOptionMenu(
            scroll, variable=loc_var, values=list(loc_options.keys()),
            width=540, height=36, fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            font=("Segoe UI", 13),
        )
        loc_menu.pack(fill="x", pady=(0, 2))

        # Quantity fields
        qty_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        qty_frame.pack(fill="x", pady=(8, 2))

        ctk.CTkLabel(qty_frame, text="Quantity", font=("Segoe UI Semibold", 12),
                     text_color=COLORS["text_secondary"]).pack(side="left")
        qty_var = ctk.StringVar(
            value=str(existing.get("quantity", 0)) if existing else "0")
        ctk.CTkEntry(qty_frame, textvariable=qty_var, width=100, height=36,
                     fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                     text_color=COLORS["text_primary"]).pack(side="left", padx=(10, 30))

        ctk.CTkLabel(qty_frame, text="Min Quantity (reorder alert)",
                     font=("Segoe UI Semibold", 12),
                     text_color=COLORS["text_secondary"]).pack(side="left")
        min_var = ctk.StringVar(
            value=str(existing.get("min_quantity", 0)) if existing else "0")
        ctk.CTkEntry(qty_frame, textvariable=min_var, width=100, height=36,
                     fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                     text_color=COLORS["text_primary"]).pack(side="left", padx=10)

        # Pricing
        price_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        price_frame.pack(fill="x", pady=(8, 2))

        ctk.CTkLabel(price_frame, text="Cost Price $",
                     font=("Segoe UI Semibold", 12),
                     text_color=COLORS["text_secondary"]).pack(side="left")
        cost_var = ctk.StringVar(
            value=str(existing.get("cost_price", 0.0)) if existing else "0.00")
        ctk.CTkEntry(price_frame, textvariable=cost_var, width=120, height=36,
                     fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                     text_color=COLORS["text_primary"]).pack(side="left", padx=(10, 30))

        ctk.CTkLabel(price_frame, text="List Price $",
                     font=("Segoe UI Semibold", 12),
                     text_color=COLORS["text_secondary"]).pack(side="left")
        list_var = ctk.StringVar(
            value=str(existing.get("list_price", 0.0)) if existing else "0.00")
        ctk.CTkEntry(price_frame, textvariable=list_var, width=120, height=36,
                     fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                     text_color=COLORS["text_primary"]).pack(side="left", padx=10)

        # Lookup pricing button
        def lookup_pricing():
            pn = fields["mfg_part_number"].get().strip()
            if not pn:
                pn = fields["internal_part_number"].get().strip()
            if not pn:
                messagebox.showinfo("Pricing Lookup",
                                    "Enter a part number first.")
                return
            if self.pricing is None:
                messagebox.showinfo("Pricing Lookup",
                                    "Configure pricing folder in Settings first.")
                return
            results = self.pricing.find_pricing(pn)
            if not results:
                messagebox.showinfo("Pricing Lookup",
                                    f"No pricing found for '{pn}' in vendor spreadsheets.")
                return
            # Show results in a sub-dialog
            self._show_pricing_results(results, cost_var, list_var, dialog)

        ctk.CTkButton(
            scroll, text="🔍  Look Up Pricing from Vendor Sheets", height=36,
            fg_color=COLORS["bg_input"], hover_color=COLORS["bg_card_hover"],
            font=("Segoe UI", 13), command=lookup_pricing,
        ).pack(fill="x", pady=(10, 5))

        add_field("Notes", "notes")

        # Save button
        def save():
            mfg = fields["mfg_part_number"].get().strip()
            internal = fields["internal_part_number"].get().strip()
            if not mfg and not internal:
                messagebox.showwarning("Missing Fields",
                                       "Enter at least a MFG or internal part number.")
                return
            try:
                qty = int(qty_var.get())
            except ValueError:
                qty = 0
            try:
                min_q = int(min_var.get())
            except ValueError:
                min_q = 0
            try:
                cost = float(cost_var.get())
            except ValueError:
                cost = 0.0
            try:
                lp = float(list_var.get())
            except ValueError:
                lp = 0.0

            loc_id = loc_options.get(loc_var.get(), "")

            if existing:
                self.db.update_part(
                    existing["id"],
                    mfg_part_number=mfg,
                    internal_part_number=internal,
                    description=fields["description"].get().strip(),
                    vendor=fields["vendor"].get().strip(),
                    category=fields["category"].get().strip(),
                    location_id=loc_id,
                    quantity=qty,
                    min_quantity=min_q,
                    cost_price=cost,
                    list_price=lp,
                    notes=fields["notes"].get().strip(),
                )
            else:
                self.db.add_part(
                    mfg_part_number=mfg,
                    internal_part_number=internal,
                    description=fields["description"].get().strip(),
                    location_id=loc_id,
                    quantity=qty,
                    min_quantity=min_q,
                    cost_price=cost,
                    list_price=lp,
                    vendor=fields["vendor"].get().strip(),
                    notes=fields["notes"].get().strip(),
                    category=fields["category"].get().strip(),
                )
            dialog.destroy()
            self._refresh_parts_table()
            self._update_status()

        ctk.CTkButton(
            scroll, text="💾  Save Part", height=44,
            font=("Segoe UI Semibold", 15),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=save,
        ).pack(fill="x", pady=(20, 10))

    def _show_pricing_results(self, results, cost_var, list_var, parent):
        pr_dialog = ctk.CTkToplevel(parent)
        pr_dialog.title("Pricing Results")
        pr_dialog.geometry("650x400")
        pr_dialog.configure(fg_color=COLORS["bg_dark"])
        pr_dialog.transient(parent)
        pr_dialog.grab_set()

        ctk.CTkLabel(pr_dialog, text="Select pricing to apply:",
                     font=("Segoe UI Semibold", 14),
                     text_color=COLORS["text_primary"]).pack(pady=(15, 10))

        scroll = ctk.CTkScrollableFrame(pr_dialog, fg_color=COLORS["bg_card"],
                                        corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        for r in results:
            row = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card_hover"],
                               corner_radius=8)
            row.pack(fill="x", padx=5, pady=3)

            info = (f"{r.vendor_name}  |  PN: {r.part_number}  |  "
                    f"Cost: ${r.cost_price:.2f}  |  List: ${r.list_price:.2f}")
            ctk.CTkLabel(row, text=info, font=("Segoe UI", 12),
                         text_color=COLORS["text_primary"], anchor="w"
                         ).pack(side="left", padx=10, pady=8)

            def apply(c=r.cost_price, l=r.list_price):
                cost_var.set(f"{c:.2f}")
                list_var.set(f"{l:.2f}")
                pr_dialog.destroy()

            ctk.CTkButton(
                row, text="Apply", width=70, height=28,
                fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                font=("Segoe UI", 12), command=apply,
            ).pack(side="right", padx=10, pady=6)

    def _generate_label(self, part_id: str):
        part = self.db.get_parts().get(part_id)
        if not part:
            return
        try:
            loc_str = self.db.get_location_display(part.get("location_id", ""))
            path = self.barcode_mgr.generate_barcode_image(
                part["barcode"],
                part.get("description", ""),
                part.get("internal_part_number", ""),
                loc_str,
            )
            messagebox.showinfo("Label Generated",
                                f"Label saved to:\n{path}\n\n"
                                "Use 'Print Labels' from the dashboard to print.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate label:\n{e}")

    def _delete_part(self, part_id: str):
        if messagebox.askyesno("Confirm Delete",
                               "Delete this part? This cannot be undone."):
            self.db.delete_part(part_id)
            self._refresh_parts_table()
            self._update_status()

    # ══════════════════════════════════════════════════════════════════
    #  LOCATIONS
    # ══════════════════════════════════════════════════════════════════
    def show_locations(self):
        if not self._require_db():
            return
        self._clear_content()
        self._frame_stack.append("locations")
        self._show_back_button(True)

        top = ctk.CTkFrame(self._content, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(top, text="🗄️  Locations (Cabinet → Shelf → Bin)",
                     font=("Segoe UI Semibold", 18),
                     text_color=COLORS["text_primary"]).pack(side="left")

        ctk.CTkButton(
            top, text="＋  Add Location", height=40, width=160,
            font=("Segoe UI Semibold", 14),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._show_add_location_dialog,
        ).pack(side="right")

        # Location table
        self._loc_table = ctk.CTkScrollableFrame(
            self._content, fg_color=COLORS["bg_card"], corner_radius=12)
        self._loc_table.pack(fill="both", expand=True)

        self._refresh_locations_table()

    def _refresh_locations_table(self):
        for w in self._loc_table.winfo_children():
            w.destroy()

        # Header
        hdr = ctk.CTkFrame(self._loc_table, fg_color=COLORS["table_header"],
                           height=36, corner_radius=8)
        hdr.pack(fill="x", padx=5, pady=(5, 2))
        hdr.pack_propagate(False)
        for h, w in [("Cabinet", 150), ("Shelf", 120), ("Bin", 120),
                     ("Description", 250), ("Parts Stored", 100), ("Actions", 100)]:
            ctk.CTkLabel(hdr, text=h, width=w, font=("Segoe UI Semibold", 11),
                         text_color=COLORS["text_secondary"],
                         anchor="w").pack(side="left", padx=4)

        locations = self.db.get_locations()
        parts = self.db.get_parts()

        for idx, (lid, loc) in enumerate(sorted(locations.items(),
                                                 key=lambda x: (x[1]["cabinet"],
                                                                x[1]["shelf"],
                                                                x[1]["bin"]))):
            bg = COLORS["table_row_alt"] if idx % 2 == 0 else COLORS["bg_card"]
            row = ctk.CTkFrame(self._loc_table, fg_color=bg, height=34,
                               corner_radius=4)
            row.pack(fill="x", padx=5, pady=1)
            row.pack_propagate(False)

            parts_count = sum(1 for p in parts.values()
                              if p.get("location_id") == lid)

            for val, w in [(loc["cabinet"], 150), (loc["shelf"], 120),
                           (loc["bin"], 120), (loc.get("description", ""), 250),
                           (str(parts_count), 100)]:
                ctk.CTkLabel(row, text=val, width=w, font=("Segoe UI", 12),
                             text_color=COLORS["text_primary"],
                             anchor="w").pack(side="left", padx=4)

            ctk.CTkButton(
                row, text="🗑️", width=30, height=26,
                fg_color="transparent", hover_color=COLORS["danger"],
                command=lambda l=lid: self._delete_location(l),
            ).pack(side="left", padx=10)

        if not locations:
            ctk.CTkLabel(
                self._loc_table,
                text="No locations set up yet. Click '+ Add Location' to get started.",
                font=("Segoe UI", 14), text_color=COLORS["text_muted"],
            ).pack(pady=40)

    def _show_add_location_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Location")
        dialog.geometry("450x350")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.focus_force()

        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=25, pady=25)

        fields = {}
        for label, key in [("Cabinet Name *", "cabinet"), ("Shelf *", "shelf"),
                           ("Bin Label *", "bin"), ("Description", "description")]:
            ctk.CTkLabel(frame, text=label, font=("Segoe UI Semibold", 12),
                         text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(10, 2))
            var = ctk.StringVar()
            ctk.CTkEntry(frame, textvariable=var, height=36,
                         fg_color=COLORS["bg_input"],
                         border_color=COLORS["border"],
                         text_color=COLORS["text_primary"],
                         font=("Segoe UI", 13)).pack(fill="x")
            fields[key] = var

        def save():
            cab = fields["cabinet"].get().strip()
            shelf = fields["shelf"].get().strip()
            bn = fields["bin"].get().strip()
            if not cab or not shelf or not bn:
                messagebox.showwarning("Missing", "Cabinet, shelf, and bin are required.")
                return
            self.db.add_location(cab, shelf, bn, fields["description"].get().strip())
            dialog.destroy()
            self._refresh_locations_table()
            self._update_status()

        ctk.CTkButton(
            frame, text="💾  Save Location", height=40,
            font=("Segoe UI Semibold", 14),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=save,
        ).pack(fill="x", pady=(20, 0))

    def _delete_location(self, loc_id):
        if messagebox.askyesno("Confirm", "Delete this location?"):
            self.db.delete_location(loc_id)
            self._refresh_locations_table()
            self._update_status()

    # ══════════════════════════════════════════════════════════════════
    #  SCANNER (BARCODE SCAN → WITHDRAW)
    # ══════════════════════════════════════════════════════════════════
    def show_scanner(self):
        if not self._require_db():
            return
        self._clear_content()
        self._frame_stack.append("scanner")
        self._show_back_button(True)
        self._scanner_active = True

        center = ctk.CTkFrame(self._content, fg_color="transparent")
        center.pack(expand=True)

        ctk.CTkLabel(center, text="📷", font=("Segoe UI", 72)).pack(pady=(20, 10))
        ctk.CTkLabel(
            center, text="Scan Mode Active",
            font=("Segoe UI Semibold", 28), text_color=COLORS["success"],
        ).pack()
        ctk.CTkLabel(
            center,
            text="Scan a part bin barcode with your scanner\n"
                 "or type a barcode value and press Enter",
            font=("Segoe UI", 14), text_color=COLORS["text_muted"],
            justify="center",
        ).pack(pady=(10, 25))

        # Manual entry field
        self._manual_scan_var = ctk.StringVar()
        entry = ctk.CTkEntry(
            center, textvariable=self._manual_scan_var,
            placeholder_text="Manual barcode entry...",
            width=400, height=44, font=("Segoe UI", 16),
            fg_color=COLORS["bg_input"], border_color=COLORS["accent"],
            text_color=COLORS["text_primary"],
        )
        entry.pack(pady=(0, 15))
        # Recognize scans whether or not the scanner sends Enter/Tab
        ScanDetector(entry, self._process_scan,
                     on_manual_enter=lambda: self._process_scan(
                         self._manual_scan_var.get()))
        entry.focus_set()

        # Recent scans history
        ctk.CTkLabel(center, text="Recent Activity",
                     font=("Segoe UI Semibold", 14),
                     text_color=COLORS["text_secondary"]).pack(pady=(20, 5))

        self._scan_history_frame = ctk.CTkScrollableFrame(
            center, width=500, height=200, fg_color=COLORS["bg_card"],
            corner_radius=12)
        self._scan_history_frame.pack()

        # Show recent history
        history = self.db.get_history(20)
        for entry in reversed(history):
            ts = entry.get("timestamp", "")[:16].replace("T", " ")
            action = entry.get("action", "")
            delta = entry.get("delta", 0)
            pn = entry.get("internal_part_number") or entry.get("mfg_part_number", "")
            txt = f"{ts}  |  {action.upper()}  |  {pn}  |  Δ {delta:+d}  →  {entry.get('new_quantity', '?')}"
            color = COLORS["danger"] if action == "withdraw" else COLORS["success"]
            ctk.CTkLabel(self._scan_history_frame, text=txt,
                         font=("Consolas", 11), text_color=color,
                         anchor="w").pack(fill="x", padx=8, pady=1)

    def _on_key(self, event):
        """Fallback scan capture on the Scan Parts page when no text box
        has focus. (Text boxes use ScanDetector instead.)"""
        if not self._scanner_active:
            return
        focused = self.focus_get()
        if isinstance(focused, (ctk.CTkEntry, tk.Entry)):
            return

        if event.keysym in ("Return", "KP_Enter", "Tab"):
            self._flush_scan_buffer()
            return "break"

        if event.char and event.char.isprintable():
            self._scan_buffer += event.char
            if self._scan_timer_id:
                self.after_cancel(self._scan_timer_id)
            # Scanner didn't send Enter? Finish the scan after a short pause.
            self._scan_timer_id = self.after(150, self._flush_scan_buffer)

    def _flush_scan_buffer(self):
        if self._scan_timer_id:
            try:
                self.after_cancel(self._scan_timer_id)
            except Exception:
                pass
            self._scan_timer_id = None
        code, self._scan_buffer = self._scan_buffer, ""
        if self._scanner_active and len(clean_barcode(code)) >= 4:
            self._process_scan(code)

    def _clear_scan_buffer(self):
        self._scan_buffer = ""

    def _process_scan(self, barcode: str):
        """Handle a scanned barcode - show withdrawal dialog."""
        barcode = clean_barcode(barcode)
        if not barcode or not self.db:
            return

        part = self.db.get_part_by_barcode(barcode)
        if not part:
            messagebox.showwarning("Not Found",
                                   f"No part found for barcode:\n{barcode}")
            return

        self._show_withdraw_dialog(part)

    def _show_withdraw_dialog(self, part: dict):
        """Pop up allowing user to enter quantity withdrawn."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Part Scanned — Withdraw")
        dialog.geometry("500x420")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.focus_force()

        frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"],
                             corner_radius=16)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(frame, text="📦  Part Scanned",
                     font=("Segoe UI Semibold", 22),
                     text_color=COLORS["accent"]).pack(pady=(20, 15))

        # Part info
        info_items = [
            ("MFG Part #", part.get("mfg_part_number", "")),
            ("Internal #", part.get("internal_part_number", "")),
            ("Description", part.get("description", "")),
            ("Current Qty", str(part.get("quantity", 0))),
            ("Location", self.db.get_location_display(part.get("location_id", ""))),
        ]
        for label, value in info_items:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=25, pady=2)
            ctk.CTkLabel(row, text=f"{label}:", width=120,
                         font=("Segoe UI Semibold", 12),
                         text_color=COLORS["text_secondary"],
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=("Segoe UI", 13),
                         text_color=COLORS["text_primary"],
                         anchor="w").pack(side="left", padx=5)

        # Quantity to withdraw
        ctk.CTkLabel(frame, text="How many parts taken?",
                     font=("Segoe UI Semibold", 15),
                     text_color=COLORS["text_primary"]).pack(pady=(20, 5))

        qty_var = ctk.StringVar(value="1")
        qty_entry = ctk.CTkEntry(
            frame, textvariable=qty_var, width=120, height=50,
            font=("Segoe UI Bold", 24), justify="center",
            fg_color=COLORS["bg_input"], border_color=COLORS["accent"],
            text_color=COLORS["text_primary"],
        )
        qty_entry.pack(pady=(0, 5))
        qty_entry.select_range(0, "end")
        qty_entry.focus_set()

        reason_var = ctk.StringVar()
        ctk.CTkEntry(
            frame, textvariable=reason_var,
            placeholder_text="Reason / Job # (optional)",
            width=300, height=36, font=("Segoe UI", 13),
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        ).pack(pady=(5, 15))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(pady=(0, 20))

        def withdraw():
            try:
                qty = int(qty_var.get())
            except ValueError:
                messagebox.showwarning("Invalid", "Enter a valid number.")
                return
            if qty <= 0:
                messagebox.showwarning("Invalid", "Enter a positive quantity.")
                return
            new_qty = self.db.adjust_quantity(
                part["id"], -qty, reason_var.get().strip())
            dialog.destroy()
            messagebox.showinfo(
                "Withdrawn",
                f"Took {qty} × {part.get('internal_part_number', part.get('mfg_part_number', ''))}\n"
                f"New quantity: {new_qty}"
            )
            # Refresh if on scanner page
            if self._scanner_active:
                self.show_scanner()

        def restock():
            try:
                qty = int(qty_var.get())
            except ValueError:
                messagebox.showwarning("Invalid", "Enter a valid number.")
                return
            if qty <= 0:
                messagebox.showwarning("Invalid", "Enter a positive quantity.")
                return
            new_qty = self.db.adjust_quantity(
                part["id"], qty, reason_var.get().strip())
            dialog.destroy()
            messagebox.showinfo(
                "Restocked",
                f"Added {qty} × {part.get('internal_part_number', part.get('mfg_part_number', ''))}\n"
                f"New quantity: {new_qty}"
            )
            if self._scanner_active:
                self.show_scanner()

        ctk.CTkButton(
            btn_frame, text="➖  Withdraw", width=150, height=44,
            font=("Segoe UI Semibold", 15),
            fg_color=COLORS["danger"], hover_color="#ff6b6b",
            command=withdraw,
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame, text="➕  Restock", width=150, height=44,
            font=("Segoe UI Semibold", 15),
            fg_color=COLORS["success"], hover_color="#7bed9f",
            command=restock,
        ).pack(side="left", padx=10)

        # Bind Enter to withdraw
        qty_entry.bind("<Return>", lambda e: withdraw())

    # ══════════════════════════════════════════════════════════════════
    #  PRICING IMPORT
    # ══════════════════════════════════════════════════════════════════
    def show_pricing(self):
        self._clear_content()
        self._frame_stack.append("pricing")
        self._show_back_button(True)

        top = ctk.CTkFrame(self._content, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(top, text="💲  Vendor Pricing — Column Configuration",
                     font=("Segoe UI Semibold", 18),
                     text_color=COLORS["text_primary"]).pack(side="left")

        ctk.CTkButton(
            top, text="📁  Change Folder", height=36, width=150,
            font=("Segoe UI", 13), fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            command=self._select_pricing_folder,
        ).pack(side="right")

        folder = self.config.get("pricing_folder_path", "")
        ctk.CTkLabel(
            self._content,
            text=f"Folder: {folder}" if folder else "⚠ No pricing folder configured — click 'Change Folder'",
            font=("Segoe UI", 12),
            text_color=COLORS["text_muted"] if folder else COLORS["warning"],
        ).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(
            self._content,
            text="Configure which columns to pull Part Number, Description, Cost, and List Price from in each spreadsheet.",
            font=("Segoe UI", 11),
            text_color=COLORS["text_muted"],
        ).pack(anchor="w", pady=(0, 10))

        if not self.pricing:
            return

        files = self.pricing.get_spreadsheet_files()
        if not files:
            ctk.CTkLabel(self._content,
                         text="No .xlsx or .csv files found in the pricing folder.",
                         font=("Segoe UI", 14), text_color=COLORS["text_muted"],
                         ).pack(pady=40)
            return

        scroll = ctk.CTkScrollableFrame(self._content,
                                        fg_color=COLORS["bg_card"],
                                        corner_radius=12)
        scroll.pack(fill="both", expand=True)

        all_mappings = self.pricing.get_all_mappings()

        for f in files:
            row = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card_hover"],
                               corner_radius=8)
            row.pack(fill="x", padx=5, pady=3)

            # Check if this file has a mapping configured
            is_csv = f.lower().endswith(".csv")
            has_mapping = any(m.filename == f for m in all_mappings.values())
            status = "✅" if has_mapping else "⚠️"
            status_text = "Configured" if has_mapping else "Not configured"
            status_color = COLORS["success"] if has_mapping else COLORS["warning"]

            ctk.CTkLabel(row, text=f"{status}  📊  {f}", font=("Segoe UI", 13),
                         text_color=COLORS["text_primary"],
                         anchor="w").pack(side="left", padx=12, pady=10)

            ctk.CTkLabel(row, text=status_text, font=("Segoe UI", 11),
                         text_color=status_color).pack(side="left", padx=5)

            # Count loaded entries
            if has_mapping:
                count = len(self.pricing.load_spreadsheet(f))
                ctk.CTkLabel(row, text=f"{count} items loaded",
                             font=("Segoe UI", 11),
                             text_color=COLORS["text_muted"]).pack(side="right", padx=5)

            def configure(fn=f):
                self._show_column_config_dialog(fn)

            ctk.CTkButton(
                row, text="Configure Columns", width=140, height=28,
                fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                font=("Segoe UI", 12), command=configure,
            ).pack(side="right", padx=5, pady=8)

            if has_mapping:
                def preview(fn=f):
                    entries = self.pricing.load_spreadsheet(fn)
                    self._show_pricing_preview(fn, entries)

                ctk.CTkButton(
                    row, text="Preview", width=80, height=28,
                    fg_color=COLORS["bg_input"], hover_color=COLORS["bg_card"],
                    font=("Segoe UI", 12), command=preview,
                ).pack(side="right", padx=5, pady=8)

    def _show_column_config_dialog(self, filename: str):
        """Show dialog to configure which columns to pull data from."""
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Configure Columns — {filename}")
        dialog.geometry("900x700")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.focus_force()

        is_xlsx = filename.lower().endswith(".xlsx")

        # Sheet selector for xlsx
        sheet_names = []
        selected_sheet = ""
        if is_xlsx:
            sheet_names = self.pricing.get_xlsx_sheet_names(filename)
            selected_sheet = sheet_names[0] if sheet_names else ""

        main_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Top controls
        ctrl = ctk.CTkFrame(main_frame, fg_color="transparent")
        ctrl.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(ctrl, text=f"📊  {filename}",
                     font=("Segoe UI Semibold", 16),
                     text_color=COLORS["text_primary"]).pack(side="left")

        sheet_var = ctk.StringVar(value=selected_sheet)
        if is_xlsx and len(sheet_names) > 1:
            ctk.CTkLabel(ctrl, text="Sheet:",
                         font=("Segoe UI", 12),
                         text_color=COLORS["text_secondary"]).pack(side="left", padx=(20, 5))
            sheet_menu = ctk.CTkOptionMenu(
                ctrl, variable=sheet_var, values=sheet_names,
                width=200, height=32, fg_color=COLORS["bg_input"],
                button_color=COLORS["accent"],
                command=lambda v: refresh_preview(),
            )
            sheet_menu.pack(side="left")

        # Column mapping dropdowns
        map_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12)
        map_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(map_frame, text="Map each data field to a column:",
                     font=("Segoe UI Semibold", 14),
                     text_color=COLORS["text_primary"],
                     ).pack(anchor="w", padx=15, pady=(12, 8))

        mapping_vars = {}
        mapping_row_frame = ctk.CTkFrame(map_frame, fg_color="transparent")
        mapping_row_frame.pack(fill="x", padx=15, pady=(0, 12))

        field_labels = [
            ("part_number", "Part Number / Item # *"),
            ("description", "Description"),
            ("cost", "Cost Price"),
            ("list", "List Price"),
        ]

        col_options_var = {}  # Will be populated after headers load

        for i, (key, label) in enumerate(field_labels):
            col = ctk.CTkFrame(mapping_row_frame, fg_color="transparent")
            col.pack(side="left", fill="x", expand=True, padx=5)

            ctk.CTkLabel(col, text=label, font=("Segoe UI Semibold", 11),
                         text_color=COLORS["text_secondary"]).pack(anchor="w")

            var = ctk.StringVar(value="(not mapped)")
            menu = ctk.CTkOptionMenu(
                col, variable=var, values=["(not mapped)"],
                width=180, height=32, fg_color=COLORS["bg_input"],
                button_color=COLORS["accent"], font=("Segoe UI", 12),
            )
            menu.pack(fill="x", pady=(2, 0))
            mapping_vars[key] = (var, menu)

        # Header row selector
        header_row_var = ctk.StringVar(value="Row 1")

        hdr_frame = ctk.CTkFrame(map_frame, fg_color="transparent")
        hdr_frame.pack(fill="x", padx=15, pady=(0, 12))

        ctk.CTkLabel(hdr_frame, text="Header Row:",
                     font=("Segoe UI Semibold", 11),
                     text_color=COLORS["text_secondary"]).pack(side="left")

        hdr_menu = ctk.CTkOptionMenu(
            hdr_frame, variable=header_row_var,
            values=[f"Row {i+1}" for i in range(10)],
            width=100, height=32, fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            command=lambda v: refresh_preview(),
        )
        hdr_menu.pack(side="left", padx=10)

        # Data preview table
        ctk.CTkLabel(main_frame, text="Data Preview (first 10 rows):",
                     font=("Segoe UI Semibold", 13),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(5, 3))

        preview_scroll = ctk.CTkScrollableFrame(main_frame,
                                                 fg_color=COLORS["bg_card"],
                                                 corner_radius=12)
        preview_scroll.pack(fill="both", expand=True)

        def get_header_row_idx():
            try:
                return int(header_row_var.get().replace("Row ", "")) - 1
            except ValueError:
                return 0

        def refresh_preview():
            sheet = sheet_var.get() if is_xlsx else ""
            headers, samples = self.pricing.read_headers(filename, sheet, 10)

            if not headers:
                return

            # Build column options: "A: Column Name", "B: Column Name", ...
            col_letters = [chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26)
                           for i in range(len(headers))]

            hdr_idx = get_header_row_idx()
            # If header row is beyond available data, use row 0
            all_rows = [headers] + samples
            if hdr_idx < len(all_rows):
                display_headers = all_rows[hdr_idx]
            else:
                display_headers = headers

            options = ["(not mapped)"]
            for i, h in enumerate(display_headers):
                letter = col_letters[i] if i < len(col_letters) else str(i)
                label = h[:30] if h else "(empty)"
                options.append(f"{letter}: {label}")

            # Load existing mapping if any
            existing = self.pricing.get_mapping(filename, sheet)

            for key, (var, menu) in mapping_vars.items():
                menu.configure(values=options)
                # Set from existing mapping
                if existing:
                    col_idx = getattr(existing, f"{key}_col" if key != "part_number" else "part_number_col")
                    if 0 <= col_idx < len(display_headers):
                        var.set(options[col_idx + 1])  # +1 for "(not mapped)"
                    else:
                        var.set("(not mapped)")
                else:
                    var.set("(not mapped)")

            if existing:
                header_row_var.set(f"Row {existing.header_row + 1}")

            # Show preview table
            for w in preview_scroll.winfo_children():
                w.destroy()

            # Header row
            hdr_row = ctk.CTkFrame(preview_scroll, fg_color=COLORS["table_header"],
                                   height=30, corner_radius=6)
            hdr_row.pack(fill="x", padx=3, pady=(3, 2))
            hdr_row.pack_propagate(False)

            col_width = max(80, min(150, 800 // max(len(display_headers), 1)))
            for i, h in enumerate(display_headers):
                letter = col_letters[i] if i < len(col_letters) else str(i)
                ctk.CTkLabel(hdr_row, text=f"{letter}: {h[:15]}",
                             width=col_width, font=("Segoe UI Semibold", 10),
                             text_color=COLORS["text_secondary"],
                             anchor="w").pack(side="left", padx=2)

            # Data rows
            data_start = hdr_idx + 1
            display_rows = all_rows[data_start:data_start + 10]

            for ri, row in enumerate(display_rows):
                bg = COLORS["table_row_alt"] if ri % 2 == 0 else COLORS["bg_card"]
                r_frame = ctk.CTkFrame(preview_scroll, fg_color=bg,
                                       height=26, corner_radius=3)
                r_frame.pack(fill="x", padx=3, pady=1)
                r_frame.pack_propagate(False)

                for ci, cell in enumerate(row):
                    ctk.CTkLabel(r_frame, text=str(cell)[:18],
                                 width=col_width, font=("Segoe UI", 10),
                                 text_color=COLORS["text_primary"],
                                 anchor="w").pack(side="left", padx=2)

        def parse_col_selection(var_value: str) -> int:
            """Convert 'A: Column Name' back to column index."""
            if var_value == "(not mapped)":
                return -1
            try:
                letter_part = var_value.split(":")[0].strip()
                if len(letter_part) == 1:
                    return ord(letter_part) - 65
                elif len(letter_part) == 2:
                    return (ord(letter_part[0]) - 64) * 26 + (ord(letter_part[1]) - 65)
                return -1
            except Exception:
                return -1

        def save_mapping():
            sheet = sheet_var.get() if is_xlsx else ""
            pn_col = parse_col_selection(mapping_vars["part_number"][0].get())
            if pn_col < 0:
                messagebox.showwarning("Required",
                    "Part Number column must be mapped.")
                return

            mapping = SheetMapping(
                filename=filename,
                sheet_name=sheet,
                header_row=get_header_row_idx(),
                part_number_col=pn_col,
                description_col=parse_col_selection(mapping_vars["description"][0].get()),
                cost_col=parse_col_selection(mapping_vars["cost"][0].get()),
                list_col=parse_col_selection(mapping_vars["list"][0].get()),
                enabled=True,
            )
            self.pricing.set_mapping(mapping)
            dialog.destroy()
            self.show_pricing()

        def remove_mapping():
            sheet = sheet_var.get() if is_xlsx else ""
            self.pricing.delete_mapping(filename, sheet)
            dialog.destroy()
            self.show_pricing()

        # Bottom buttons
        btn_frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"],
                                 corner_radius=0)
        btn_frame.pack(fill="x", side="bottom")

        ctk.CTkButton(
            btn_frame, text="💾  Save Column Mapping", height=40, width=220,
            font=("Segoe UI Semibold", 14),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=save_mapping,
        ).pack(side="right", padx=15, pady=10)

        ctk.CTkButton(
            btn_frame, text="🗑️  Remove Mapping", height=40, width=160,
            font=("Segoe UI", 13),
            fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"],
            command=remove_mapping,
        ).pack(side="right", padx=5, pady=10)

        ctk.CTkButton(
            btn_frame, text="Cancel", height=40, width=100,
            font=("Segoe UI", 13),
            fg_color=COLORS["bg_card_hover"], hover_color=COLORS["border"],
            command=dialog.destroy,
        ).pack(side="right", padx=5, pady=10)

        # Need to import SheetMapping for the save
        from pricing_import import SheetMapping

        # Initial load
        refresh_preview()

    def _show_pricing_preview(self, filename, entries):
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Preview: {filename}")
        dialog.geometry("750x500")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)

        scroll = ctk.CTkScrollableFrame(dialog, fg_color=COLORS["bg_card"],
                                        corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=15, pady=15)

        hdr = ctk.CTkFrame(scroll, fg_color=COLORS["table_header"],
                           height=32, corner_radius=6)
        hdr.pack(fill="x", padx=3, pady=(3, 2))
        hdr.pack_propagate(False)
        for h, w in [("Part Number", 180), ("Description", 250),
                     ("Cost", 90), ("List", 90)]:
            ctk.CTkLabel(hdr, text=h, width=w, font=("Segoe UI Semibold", 11),
                         text_color=COLORS["text_secondary"],
                         anchor="w").pack(side="left", padx=4)

        for i, e in enumerate(entries[:200]):
            bg = COLORS["table_row_alt"] if i % 2 == 0 else COLORS["bg_card"]
            row = ctk.CTkFrame(scroll, fg_color=bg, height=28, corner_radius=3)
            row.pack(fill="x", padx=3, pady=1)
            row.pack_propagate(False)
            for v, w in [(e.part_number, 180), (e.description[:40], 250),
                         (f"${e.cost_price:.2f}", 90),
                         (f"${e.list_price:.2f}", 90)]:
                ctk.CTkLabel(row, text=v, width=w, font=("Segoe UI", 11),
                             text_color=COLORS["text_primary"],
                             anchor="w").pack(side="left", padx=4)

        if len(entries) > 200:
            ctk.CTkLabel(scroll, text=f"... showing 200 of {len(entries)} entries",
                         text_color=COLORS["text_muted"]).pack(pady=10)

    def _select_pricing_folder(self):
        folder = filedialog.askdirectory(title="Select Pricing Spreadsheets Folder")
        if folder:
            self.config["pricing_folder_path"] = folder
            save_config(self.config)
            self.pricing = PricingImporter(folder)
            self.show_pricing()

    # ══════════════════════════════════════════════════════════════════
    #  PRINT LABELS
    # ══════════════════════════════════════════════════════════════════
    def show_labels(self):
        if not self._require_db():
            return
        self._clear_content()
        self._frame_stack.append("labels")
        self._show_back_button(True)

        top = ctk.CTkFrame(self._content, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(top, text="🏷️  Generate & Print Labels",
                     font=("Segoe UI Semibold", 18),
                     text_color=COLORS["text_primary"]).pack(side="left")

        ctk.CTkButton(
            top, text="🖨️  Print Label Sheet (All Parts)", height=36,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=("Segoe UI Semibold", 13),
            command=self._generate_label_sheet,
        ).pack(side="right", padx=(5, 0))

        ctk.CTkButton(
            top, text="📄  Generate All Missing Labels", height=36,
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            font=("Segoe UI", 13),
            command=self._generate_all_labels,
        ).pack(side="right")

        # Show existing labels
        scroll = ctk.CTkScrollableFrame(self._content,
                                        fg_color=COLORS["bg_card"],
                                        corner_radius=12)
        scroll.pack(fill="both", expand=True)

        parts = self.db.get_parts()
        if not parts:
            ctk.CTkLabel(scroll, text="No parts in inventory yet.",
                         font=("Segoe UI", 14),
                         text_color=COLORS["text_muted"]).pack(pady=40)
            return

        for pid, part in sorted(parts.items(),
                                key=lambda x: x[1].get("internal_part_number", "")):
            row = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card_hover"],
                               corner_radius=8)
            row.pack(fill="x", padx=5, pady=3)

            barcode = part.get("barcode", "")
            pn = part.get("internal_part_number") or part.get("mfg_part_number", "")
            label_file = os.path.join(
                LABELS_DIR,
                f"label_{''.join(c if c.isalnum() or c in '-_' else '_' for c in barcode)}.png"
            )
            has_label = os.path.exists(label_file)

            status = "✅" if has_label else "❌"
            ctk.CTkLabel(row, text=f"{status}  {pn}  —  {barcode}",
                         font=("Segoe UI", 13),
                         text_color=COLORS["text_primary"],
                         anchor="w").pack(side="left", padx=12, pady=8)

            ctk.CTkButton(
                row, text="Generate" if not has_label else "Regenerate",
                width=90, height=28,
                fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                font=("Segoe UI", 12),
                command=lambda p=pid: self._generate_label(p),
            ).pack(side="right", padx=5, pady=6)

            if has_label:
                ctk.CTkButton(
                    row, text="Print", width=60, height=28,
                    fg_color=COLORS["success"], hover_color="#7bed9f",
                    font=("Segoe UI", 12),
                    command=lambda lf=label_file: self._print_single_label(lf),
                ).pack(side="right", padx=5, pady=6)

                ctk.CTkButton(
                    row, text="Preview", width=70, height=28,
                    fg_color=COLORS["bg_input"], hover_color=COLORS["bg_card"],
                    font=("Segoe UI", 12),
                    command=lambda lf=label_file: self._preview_label(lf),
                ).pack(side="right", padx=5, pady=6)

    def _generate_all_labels(self):
        parts = self.db.get_parts()
        generated = 0
        for pid, part in parts.items():
            barcode = part.get("barcode", "")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_"
                                for c in barcode)
            label_file = os.path.join(LABELS_DIR, f"label_{safe_name}.png")
            if not os.path.exists(label_file):
                try:
                    loc_str = self.db.get_location_display(
                        part.get("location_id", ""))
                    self.barcode_mgr.generate_barcode_image(
                        barcode, part.get("description", ""),
                        part.get("internal_part_number", ""), loc_str)
                    generated += 1
                except Exception as e:
                    print(f"Failed to generate label for {barcode}: {e}")

        messagebox.showinfo("Labels Generated",
                            f"Generated {generated} new label(s).")
        self.show_labels()

    def _generate_label_sheet(self):
        parts = self.db.get_parts()
        if not parts:
            messagebox.showinfo("No Parts", "No parts in inventory to generate labels for.")
            return

        # Build label data for all parts
        labels = []
        for pid, part in sorted(parts.items(),
                                key=lambda x: x[1].get("internal_part_number", "")):
            barcode = part.get("barcode", "")
            if not barcode:
                continue
            loc_str = self.db.get_location_display(part.get("location_id", ""))
            labels.append({
                "barcode": barcode,
                "internal_pn": part.get("internal_part_number", ""),
                "description": part.get("description", ""),
                "location": loc_str,
            })

        if not labels:
            messagebox.showinfo("No Labels", "No parts with barcodes to print.")
            return

        try:
            sheet_paths = self.barcode_mgr.generate_label_sheet(labels)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate label sheet:\n{e}")
            return

        # Show preview of first sheet
        if sheet_paths:
            total_pages = len(sheet_paths)
            page_info = f"{len(labels)} labels across {total_pages} page(s)"

            preview = ctk.CTkToplevel(self)
            preview.title(f"Label Sheet Preview — {page_info}")
            preview.geometry("850x950")
            preview.configure(fg_color=COLORS["bg_dark"])
            preview.transient(self)

            top_bar = ctk.CTkFrame(preview, fg_color=COLORS["bg_card"],
                                   corner_radius=0)
            top_bar.pack(fill="x")

            ctk.CTkLabel(
                top_bar, text=f"📄  {page_info}  —  Saved to labels/ folder",
                font=("Segoe UI Semibold", 14),
                text_color=COLORS["text_primary"],
            ).pack(side="left", padx=15, pady=10)

            def open_folder():
                folder = os.path.abspath(LABELS_DIR)
                if sys.platform == "win32":
                    os.startfile(folder)
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", folder])

            def open_pdf():
                pdf = getattr(self.barcode_mgr, "last_sheet_pdf", "")
                if not pdf or not os.path.exists(pdf):
                    open_folder()
                    return
                if sys.platform == "win32":
                    os.startfile(pdf)
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", pdf])

            ctk.CTkButton(
                top_bar, text="🖨️  Open PDF to Print", width=170, height=32,
                font=("Segoe UI Semibold", 13),
                fg_color=COLORS["success"], hover_color=COLORS["success_hover"],
                text_color=COLORS["bg_dark"],
                command=open_pdf,
            ).pack(side="right", padx=10, pady=8)

            ctk.CTkButton(
                top_bar, text="📂  Open Folder", width=120, height=32,
                font=("Segoe UI", 13),
                fg_color=COLORS["bg_input"], hover_color=COLORS["bg_card_hover"],
                command=open_folder,
            ).pack(side="right", pady=8)

            ctk.CTkLabel(
                preview,
                text="When printing, set scaling to \"Actual size\" (100%) — "
                     "not \"Fit to page\" — so the barcodes scan reliably.",
                font=("Segoe UI", 12), text_color=COLORS["warning"],
            ).pack(fill="x", padx=15, pady=(8, 0))

            # Scrollable preview of all pages
            scroll = ctk.CTkScrollableFrame(preview, fg_color=COLORS["bg_card"],
                                            corner_radius=12)
            scroll.pack(fill="both", expand=True, padx=15, pady=15)

            for i, sheet_path in enumerate(sheet_paths):
                try:
                    ctk.CTkLabel(
                        scroll, text=f"Page {i + 1} of {total_pages}",
                        font=("Segoe UI Semibold", 13),
                        text_color=COLORS["text_secondary"],
                    ).pack(pady=(10 if i > 0 else 5, 5))

                    img = Image.open(sheet_path)
                    # Scale to fit preview window
                    img.thumbnail((800, 1000))
                    photo = ImageTk.PhotoImage(img)
                    lbl = ctk.CTkLabel(scroll, image=photo, text="")
                    lbl.image = photo
                    lbl.pack(padx=10, pady=(0, 10))
                except Exception as e:
                    ctk.CTkLabel(scroll, text=f"Error loading page {i+1}: {e}",
                                 text_color=COLORS["danger"]).pack(pady=10)

    def _print_single_label(self, label_file: str):
        try:
            printer = self.config.get("dymo_printer_name", "")
            self.barcode_mgr.print_label(label_file, printer)
            messagebox.showinfo("Sent", "Label sent to printer.")
        except Exception as e:
            messagebox.showerror("Print Error", str(e))

    def _preview_label(self, label_file: str):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Label Preview")
        dialog.geometry("450x250")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)

        try:
            img = Image.open(label_file)
            img.thumbnail((400, 200))
            photo = ImageTk.PhotoImage(img)
            lbl = ctk.CTkLabel(dialog, image=photo, text="")
            lbl.image = photo  # keep reference
            lbl.pack(expand=True, padx=20, pady=20)
        except Exception as e:
            ctk.CTkLabel(dialog, text=f"Error loading image:\n{e}",
                         text_color=COLORS["danger"]).pack(expand=True)

    # ══════════════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════════════
    def show_settings(self):
        self._clear_content()
        self._frame_stack.append("settings")
        self._show_back_button(True)

        ctk.CTkLabel(self._content, text="⚙️  Settings",
                     font=("Segoe UI Semibold", 22),
                     text_color=COLORS["text_primary"]).pack(anchor="w",
                                                             pady=(0, 20))

        scroll = ctk.CTkScrollableFrame(self._content,
                                        fg_color=COLORS["bg_card"],
                                        corner_radius=12)
        scroll.pack(fill="both", expand=True)

        # ── Database Path ──────────────────────────────────────────────
        self._settings_section(scroll, "Database File Path",
            "Path to the shared JSON inventory file on your server.\n"
            "Use 'Open Existing' to connect to an existing database on another machine.")

        db_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        db_frame.pack(fill="x", padx=20, pady=(0, 15))

        self._db_path_var = ctk.StringVar(
            value=self.config.get("inventory_json_path", ""))
        ctk.CTkEntry(db_frame, textvariable=self._db_path_var, height=36,
                     fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                     text_color=COLORS["text_primary"],
                     font=("Segoe UI", 13)).pack(side="left", fill="x",
                                                  expand=True, padx=(0, 10))

        def open_existing_db():
            path = filedialog.askopenfilename(
                title="Open Existing Inventory Database",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if path:
                self._db_path_var.set(path)

        def create_new_db():
            path = filedialog.asksaveasfilename(
                title="Create New Inventory Database",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json")],
                initialfile="parts_inventory.json",
            )
            if path:
                self._db_path_var.set(path)

        ctk.CTkButton(db_frame, text="Open Existing", width=120, height=36,
                     fg_color=COLORS["success"],
                     hover_color=COLORS["success_hover"],
                     text_color=COLORS["bg_dark"],
                     font=("Segoe UI Semibold", 12),
                     command=open_existing_db).pack(side="right", padx=(5, 0))

        ctk.CTkButton(db_frame, text="Create New", width=110, height=36,
                     fg_color=COLORS["bg_input"],
                     hover_color=COLORS["bg_card_hover"],
                     font=("Segoe UI", 12),
                     command=create_new_db).pack(side="right")

        # ── Pricing Folder ─────────────────────────────────────────────
        self._settings_section(scroll, "Pricing Spreadsheets Folder",
            "Shared folder on your server with vendor pricing .xlsx/.csv files.")

        pf_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        pf_frame.pack(fill="x", padx=20, pady=(0, 15))

        self._pricing_path_var = ctk.StringVar(
            value=self.config.get("pricing_folder_path", ""))
        ctk.CTkEntry(pf_frame, textvariable=self._pricing_path_var, height=36,
                     fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                     text_color=COLORS["text_primary"],
                     font=("Segoe UI", 13)).pack(side="left", fill="x",
                                                  expand=True, padx=(0, 10))

        def browse_pf():
            path = filedialog.askdirectory(
                title="Select Pricing Spreadsheets Folder")
            if path:
                self._pricing_path_var.set(path)

        ctk.CTkButton(pf_frame, text="Browse...", width=90, height=36,
                     fg_color=COLORS["bg_input"],
                     hover_color=COLORS["bg_card_hover"],
                     command=browse_pf).pack(side="right")

        # ── Printer ────────────────────────────────────────────────────
        self._settings_section(scroll, "Dymo LabelWriter 550",
            "Select your Dymo printer for barcode label printing.")

        printer_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        printer_frame.pack(fill="x", padx=20, pady=(0, 15))

        printers = self.barcode_mgr.get_available_printers()
        self._printer_var = ctk.StringVar(
            value=self.config.get("dymo_printer_name", ""))

        if printers:
            ctk.CTkOptionMenu(
                printer_frame, variable=self._printer_var, values=printers,
                width=400, height=36, fg_color=COLORS["bg_input"],
                button_color=COLORS["accent"],
                font=("Segoe UI", 13),
            ).pack(side="left")
        else:
            ctk.CTkLabel(printer_frame,
                         text="No printers detected. Enter name manually:",
                         text_color=COLORS["text_muted"]).pack(side="left", padx=(0, 10))
            ctk.CTkEntry(printer_frame, textvariable=self._printer_var,
                         width=300, height=36, fg_color=COLORS["bg_input"],
                         border_color=COLORS["border"],
                         text_color=COLORS["text_primary"]).pack(side="left")

        # ── Label Size ─────────────────────────────────────────────────
        self._settings_section(scroll, "Label Dimensions",
            "Label size in mm for your Dymo label roll.")

        size_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        size_frame.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(size_frame, text="Width (mm):",
                     text_color=COLORS["text_secondary"]).pack(side="left")
        self._label_w_var = ctk.StringVar(
            value=str(self.config.get("label_width_mm", 54)))
        ctk.CTkEntry(size_frame, textvariable=self._label_w_var, width=80,
                     height=36, fg_color=COLORS["bg_input"],
                     border_color=COLORS["border"],
                     text_color=COLORS["text_primary"]).pack(side="left", padx=(5, 20))

        ctk.CTkLabel(size_frame, text="Height (mm):",
                     text_color=COLORS["text_secondary"]).pack(side="left")
        self._label_h_var = ctk.StringVar(
            value=str(self.config.get("label_height_mm", 25)))
        ctk.CTkEntry(size_frame, textvariable=self._label_h_var, width=80,
                     height=36, fg_color=COLORS["bg_input"],
                     border_color=COLORS["border"],
                     text_color=COLORS["text_primary"]).pack(side="left", padx=5)

        # ── Company Name ───────────────────────────────────────────────
        self._settings_section(scroll, "Company Name",
            "Shown on labels and reports.")

        co_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        co_frame.pack(fill="x", padx=20, pady=(0, 15))

        self._company_var = ctk.StringVar(
            value=self.config.get("company_name", ""))
        ctk.CTkEntry(co_frame, textvariable=self._company_var, width=400,
                     height=36, fg_color=COLORS["bg_input"],
                     border_color=COLORS["border"],
                     text_color=COLORS["text_primary"],
                     font=("Segoe UI", 13)).pack(side="left")

        # ── Updates ────────────────────────────────────────────────────
        self._settings_section(scroll, "Updates",
            f"Installed version: v{APP_VERSION}. New versions are published on GitHub.")

        upd_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        upd_frame.pack(fill="x", padx=20, pady=(0, 15))

        self._auto_update_switch = ctk.CTkSwitch(
            upd_frame, text="Check for updates when the app starts",
            font=("Segoe UI", 13), text_color=COLORS["text_secondary"],
            fg_color=COLORS["border"], progress_color=COLORS["accent"],
        )
        if self.config.get("auto_update_check", True):
            self._auto_update_switch.select()
        self._auto_update_switch.pack(side="left")

        ctk.CTkButton(
            upd_frame, text="🔄  Check for Updates Now", width=200, height=36,
            font=("Segoe UI", 13),
            fg_color=COLORS["bg_input"], hover_color=COLORS["bg_card_hover"],
            command=lambda: self._check_for_updates(silent=False),
        ).pack(side="right")

        # ── Save Button ───────────────────────────────────────────────
        ctk.CTkButton(
            scroll, text="💾  Save Settings", height=48, width=300,
            font=("Segoe UI Semibold", 16),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._save_settings,
        ).pack(pady=30)

    def _settings_section(self, parent, title, subtitle):
        ctk.CTkLabel(parent, text=title, font=("Segoe UI Semibold", 15),
                     text_color=COLORS["text_primary"],
                     anchor="w").pack(fill="x", padx=20, pady=(15, 0))
        ctk.CTkLabel(parent, text=subtitle, font=("Segoe UI", 11),
                     text_color=COLORS["text_muted"],
                     anchor="w").pack(fill="x", padx=20, pady=(0, 5))

    def _save_settings(self):
        self.config["inventory_json_path"] = self._db_path_var.get().strip()
        self.config["pricing_folder_path"] = self._pricing_path_var.get().strip()
        self.config["dymo_printer_name"] = self._printer_var.get().strip()
        self.config["company_name"] = self._company_var.get().strip()
        self.config["auto_update_check"] = self._auto_update_switch.get() == 1

        try:
            self.config["label_width_mm"] = int(self._label_w_var.get())
        except ValueError:
            pass
        try:
            self.config["label_height_mm"] = int(self._label_h_var.get())
        except ValueError:
            pass

        save_config(self.config)
        self._init_subsystems()
        self._update_status()
        messagebox.showinfo("Saved", "Settings saved successfully.")

    # ══════════════════════════════════════════════════════════════════
    #  AUTO UPDATE
    # ══════════════════════════════════════════════════════════════════
    def _check_for_updates(self, silent: bool = True):
        """Check GitHub in the background. silent=True stays quiet unless
        an update is found (used at startup)."""
        def worker():
            try:
                info = updater.check_for_update()
            except Exception as e:
                if not silent:
                    msg = str(e)
                    self.after(0, lambda: messagebox.showwarning(
                        "Update Check Failed",
                        f"Couldn't reach GitHub to check for updates.\n\n{msg}"))
                return
            if info:
                self.after(0, lambda: self._show_update_dialog(info))
            elif not silent:
                self.after(0, lambda: messagebox.showinfo(
                    "Up to Date",
                    f"You're running the latest version (v{APP_VERSION})."))

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_dialog(self, info):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Update Available")
        dialog.geometry("520x440")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.focus_force()

        ctk.CTkLabel(
            dialog, text="🔄  A new version is available",
            font=("Segoe UI Semibold", 18), text_color=COLORS["text_primary"],
        ).pack(pady=(20, 4))
        ctk.CTkLabel(
            dialog, text=f"v{APP_VERSION}  →  v{info.version}",
            font=("Segoe UI", 14), text_color=COLORS["success"],
        ).pack(pady=(0, 10))

        notes = ctk.CTkTextbox(dialog, height=170, font=("Segoe UI", 12),
                               fg_color=COLORS["bg_card"],
                               text_color=COLORS["text_secondary"])
        notes.pack(fill="x", padx=20)
        notes.insert("1.0", info.notes or "No release notes.")
        notes.configure(state="disabled")

        progress = ctk.CTkProgressBar(dialog, progress_color=COLORS["accent"])
        progress.set(0)
        status = ctk.CTkLabel(dialog, text="", font=("Segoe UI", 12),
                              text_color=COLORS["text_muted"])

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=15, side="bottom")

        def start_update():
            if not updater.is_frozen():
                messagebox.showinfo(
                    "Update",
                    "You're running from the Python source, so auto-update "
                    "can't replace it.\nDownload the new .exe from GitHub "
                    "Releases instead.", parent=dialog)
                return

            update_btn.configure(state="disabled")
            later_btn.configure(state="disabled")
            progress.pack(fill="x", padx=20, pady=(12, 2))
            status.pack()
            status.configure(text="Downloading…")

            def on_progress(done, total):
                frac = (done / total) if total else 0
                text = (f"Downloading… {done/1_048_576:.1f} of "
                        f"{total/1_048_576:.1f} MB")
                self.after(0, lambda: (progress.set(frac),
                                       status.configure(text=text)))

            def worker():
                try:
                    new_exe = updater.download_update(info, on_progress)
                    updater.apply_update_and_restart(new_exe)
                except Exception as e:
                    msg = str(e)
                    self.after(0, lambda: (
                        messagebox.showerror(
                            "Update Failed",
                            f"The update couldn't be installed.\n\n{msg}",
                            parent=dialog),
                        update_btn.configure(state="normal"),
                        later_btn.configure(state="normal"),
                        status.configure(text="")))
                    return
                # The swap script waits for this app to close, then relaunches
                self.after(0, lambda: (
                    status.configure(text="Restarting with the new version…"),
                    self.after(800, self.destroy)))

            threading.Thread(target=worker, daemon=True).start()

        update_btn = ctk.CTkButton(
            btns, text="Update Now", height=40, width=160,
            font=("Segoe UI Semibold", 14),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=start_update,
        )
        update_btn.pack(side="right")
        later_btn = ctk.CTkButton(
            btns, text="Later", height=40, width=100,
            font=("Segoe UI", 13),
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            command=dialog.destroy,
        )
        later_btn.pack(side="right", padx=10)


# ── Entry Point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = InventoryApp()
    app.mainloop()
