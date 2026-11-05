"""
Parts Inventory Tracker - Scan Station
Dedicated full-screen check-in/check-out mode for Panasonic CF-33
with integrated barcode scanner. Optimized for speed and touch.
"""
import tkinter as tk
from datetime import datetime

import customtkinter as ctk

from config import COLORS, get_scale
from scan_input import ScanDetector, clean_barcode


class ScanStation(ctk.CTkToplevel):
    """Full-screen scan station for barcode check-in / check-out."""

    def __init__(self, parent, db, tablet_mode=False):
        super().__init__(parent)
        self.db = db
        self.tablet_mode = tablet_mode
        self.S = get_scale(tablet_mode)

        self.title("Scan Station — Parts Inventory")
        self.configure(fg_color=COLORS["scan_bg"])

        # Force full screen on Windows reliably
        self.after(50, self._go_fullscreen)

        # Scanner state
        self._scan_buffer = ""
        self._scan_timer_id = None
        self._current_part = None
        self._history = []

        self._build_ui()

        # Bind keys
        self.bind("<Key>", self._on_key)
        self.bind("<Escape>", lambda e: self._exit())
        self.focus_force()
        self.lift()

    def _go_fullscreen(self):
        """Apply fullscreen after the window is fully initialized."""
        # Get screen dimensions
        w = self.winfo_screenwidth()
        h = self.winfo_screenheight()
        # Fill the screen. Native fullscreen (not a borderless window) so
        # Windows keeps delivering scanner keystrokes to this window.
        self.geometry(f"{w}x{h}+0+0")
        try:
            self.attributes("-fullscreen", True)
        except Exception:
            self.state("zoomed")
        # Bring to front and put the cursor in the barcode box
        self.lift()
        self.focus_force()
        self.after(100, self._barcode_entry.focus_set)

    def _build_ui(self):
        S = self.S
        # ── Top bar ───────────────────────────────────────────────────
        top = ctk.CTkFrame(self, height=50, fg_color=COLORS["bg_card"],
                           corner_radius=0)
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkLabel(
            top, text="🖥️  Scan Station", font=S["font_heading"],
            text_color=COLORS["text_primary"],
        ).pack(side="left", padx=20)

        self._clock_label = ctk.CTkLabel(
            top, text="", font=S["font_normal"],
            text_color=COLORS["text_muted"],
        )
        self._clock_label.pack(side="right", padx=20)
        self._update_clock()

        ctk.CTkButton(
            top, text="✕  Exit", width=100, height=36,
            font=S["font_normal"],
            fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"],
            command=self._exit,
        ).pack(side="right", padx=10, pady=7)

        # ── Main content — two columns ────────────────────────────────
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=10)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        # Left: scan area + part detail
        left = ctk.CTkFrame(main, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self._build_scan_area(left)
        self._build_part_detail(left)
        self._build_action_buttons(left)

        # Right: recent activity log
        right = ctk.CTkFrame(main, fg_color=COLORS["scan_card"],
                             corner_radius=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self._build_history_panel(right)

        # ── Bottom status ─────────────────────────────────────────────
        self._status_bar = ctk.CTkFrame(self, height=40,
                                        fg_color=COLORS["bg_card"],
                                        corner_radius=0)
        self._status_bar.pack(fill="x", side="bottom")
        self._status_bar.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            self._status_bar,
            text="Ready — scan a barcode or type and press Enter",
            font=S["font_normal"], text_color=COLORS["success"],
        )
        self._status_label.pack(side="left", padx=20)

        self._count_label = ctk.CTkLabel(
            self._status_bar, text="",
            font=S["font_small"], text_color=COLORS["text_muted"],
        )
        self._count_label.pack(side="right", padx=20)
        self._update_count()

    # ── Scan Area ─────────────────────────────────────────────────────
    def _build_scan_area(self, parent):
        S = self.S
        scan_frame = ctk.CTkFrame(parent, fg_color=COLORS["scan_card"],
                                  corner_radius=16)
        scan_frame.pack(fill="x", pady=(0, 10))

        inner = ctk.CTkFrame(scan_frame, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=15)

        ctk.CTkLabel(
            inner, text="Scan or type barcode:",
            font=S["font_scan_label"],
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w")

        entry_row = ctk.CTkFrame(inner, fg_color="transparent")
        entry_row.pack(fill="x", pady=(8, 0))

        self._barcode_entry = ctk.CTkEntry(
            entry_row, height=S["scan_qty_entry_h"],
            font=(S["font_scan_qty"][0], S["scan_qty_font"]),
            fg_color=COLORS["bg_input"], border_color=COLORS["accent"],
            text_color=COLORS["text_primary"],
            placeholder_text="Barcode...",
        )
        self._barcode_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        # Recognize scans whether or not the scanner sends Enter/Tab
        ScanDetector(self._barcode_entry, self._process_scan,
                     on_manual_enter=lambda: self._process_scan(
                         self._barcode_entry.get()))

        ctk.CTkButton(
            entry_row, text="Look Up", width=140,
            height=S["scan_qty_entry_h"],
            font=S["font_button"],
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=lambda: self._process_scan(self._barcode_entry.get()),
        ).pack(side="right")

    # ── Part Detail ───────────────────────────────────────────────────
    def _build_part_detail(self, parent):
        S = self.S
        self._detail_frame = ctk.CTkFrame(parent, fg_color=COLORS["scan_card"],
                                          corner_radius=16)
        self._detail_frame.pack(fill="both", expand=True, pady=(0, 10))

        # Placeholder
        self._detail_placeholder = ctk.CTkLabel(
            self._detail_frame,
            text="📦\n\nScan a barcode to view part details",
            font=S["font_scan_info"],
            text_color=COLORS["text_muted"], justify="center",
        )
        self._detail_placeholder.pack(expand=True)

        # Detail content (hidden until scan)
        self._detail_content = ctk.CTkFrame(self._detail_frame,
                                            fg_color="transparent")

        self._detail_labels = {}

    def _show_part_detail(self, part):
        S = self.S
        self._detail_placeholder.pack_forget()

        for w in self._detail_content.winfo_children():
            w.destroy()

        self._detail_content.pack(fill="both", expand=True, padx=20, pady=15)
        self._current_part = part

        loc_str = self.db.get_location_display(part.get("location_id", ""))
        qty = part.get("quantity", 0)
        min_qty = part.get("min_quantity", 0)
        qty_color = COLORS["danger"] if (qty <= min_qty and min_qty > 0) else COLORS["success"]

        # Part number — big and prominent
        pn = part.get("internal_part_number") or part.get("mfg_part_number", "")
        ctk.CTkLabel(
            self._detail_content, text=pn,
            font=S["font_scan_qty"], text_color=COLORS["accent"],
        ).pack(anchor="w", pady=(0, 5))

        # Info grid
        info = ctk.CTkFrame(self._detail_content, fg_color="transparent")
        info.pack(fill="x")

        fields = [
            ("MFG Part #", part.get("mfg_part_number", "")),
            ("Internal #", part.get("internal_part_number", "")),
            ("Description", part.get("description", "")),
            ("Location", loc_str),
            ("Vendor", part.get("vendor", "")),
            ("Cost", f"${part.get('cost_price', 0):.2f}"),
            ("List", f"${part.get('list_price', 0):.2f}"),
        ]

        for i, (label, value) in enumerate(fields):
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(
                row, text=f"{label}:", width=130,
                font=S["font_normal"],
                text_color=COLORS["text_secondary"], anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=value,
                font=S["font_normal"],
                text_color=COLORS["text_primary"], anchor="w",
            ).pack(side="left", padx=8)

        # Current quantity — large
        qty_frame = ctk.CTkFrame(self._detail_content, fg_color=COLORS["bg_input"],
                                 corner_radius=12)
        qty_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkLabel(
            qty_frame, text="CURRENT QUANTITY",
            font=S["font_small"], text_color=COLORS["text_muted"],
        ).pack(pady=(10, 0))

        self._qty_display = ctk.CTkLabel(
            qty_frame, text=str(qty),
            font=S["font_scan_big"], text_color=qty_color,
        )
        self._qty_display.pack(pady=(0, 10))

    def _clear_part_detail(self):
        self._detail_content.pack_forget()
        self._current_part = None
        self._detail_placeholder.pack(expand=True)

    # ── Action Buttons ────────────────────────────────────────────────
    def _build_action_buttons(self, parent):
        S = self.S
        self._action_frame = ctk.CTkFrame(parent, fg_color=COLORS["scan_card"],
                                          corner_radius=16)
        self._action_frame.pack(fill="x")

        inner = ctk.CTkFrame(self._action_frame, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=15)

        # Quantity input row
        qty_row = ctk.CTkFrame(inner, fg_color="transparent")
        qty_row.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            qty_row, text="Quantity:",
            font=S["font_scan_label"],
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 10))

        self._qty_entry = ctk.CTkEntry(
            qty_row, width=120, height=S["scan_qty_entry_h"],
            font=(S["font_scan_qty"][0], S["scan_qty_font"]),
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"], justify="center",
        )
        self._qty_entry.insert(0, "1")
        self._qty_entry.pack(side="left", padx=(0, 20))
        # A scan typed into this box is caught, removed, and looked up
        ScanDetector(self._qty_entry, self._process_scan)

        # Quick quantity buttons
        for val in ["1", "5", "10", "25"]:
            ctk.CTkButton(
                qty_row, text=val,
                width=S["scan_qty_entry_h"], height=S["scan_qty_entry_h"],
                font=S["font_button"],
                fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                command=lambda v=val: self._set_qty(v),
            ).pack(side="left", padx=3)

        # Reason input
        reason_row = ctk.CTkFrame(inner, fg_color="transparent")
        reason_row.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            reason_row, text="Reason / Job #:",
            font=S["font_scan_label"],
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 10))

        self._reason_entry = ctk.CTkEntry(
            reason_row, height=S["entry_height"],
            font=S["font_normal"],
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text="Optional...",
        )
        self._reason_entry.pack(side="left", fill="x", expand=True)
        ScanDetector(self._reason_entry, self._process_scan)

        # Action buttons
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")

        btn_h = S["scan_qty_entry_h"] + 10

        self._withdraw_btn = ctk.CTkButton(
            btn_row, text="➖  WITHDRAW", height=btn_h,
            font=S["font_button"],
            fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"],
            command=lambda: self._adjust(-1),
        )
        self._withdraw_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._restock_btn = ctk.CTkButton(
            btn_row, text="➕  RESTOCK", height=btn_h,
            font=S["font_button"],
            fg_color=COLORS["success"], hover_color=COLORS["success_hover"],
            command=lambda: self._adjust(1),
        )
        self._restock_btn.pack(side="left", fill="x", expand=True, padx=(8, 0))

    def _set_qty(self, val):
        self._qty_entry.delete(0, "end")
        self._qty_entry.insert(0, val)

    # ── History Panel ─────────────────────────────────────────────────
    def _build_history_panel(self, parent):
        S = self.S
        ctk.CTkLabel(
            parent, text="Recent Activity",
            font=S["font_heading"],
            text_color=COLORS["text_primary"],
        ).pack(padx=15, pady=(15, 5), anchor="w")

        self._history_scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent",
        )
        self._history_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._refresh_history()

    def _refresh_history(self):
        S = self.S
        for w in self._history_scroll.winfo_children():
            w.destroy()

        # Show local session history + recent from DB
        all_entries = list(reversed(self._history[-30:]))
        if not all_entries:
            db_history = self.db.get_history(20)
            all_entries = list(reversed(db_history))

        if not all_entries:
            ctk.CTkLabel(
                self._history_scroll, text="No activity yet.\nScan a barcode to begin.",
                font=S["font_normal"], text_color=COLORS["text_muted"],
                justify="center",
            ).pack(pady=30)
            return

        for entry in all_entries:
            ts = entry.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                time_str = ts[:8]

            action = entry.get("action", "")
            delta = entry.get("delta", 0)
            pn = entry.get("internal_part_number") or entry.get("mfg_part_number", "")
            new_qty = entry.get("new_quantity", "?")
            reason = entry.get("reason", "")

            is_withdraw = action == "withdraw"
            bg = COLORS["scan_danger"] if is_withdraw else COLORS["scan_success"]
            icon = "➖" if is_withdraw else "➕"

            card = ctk.CTkFrame(self._history_scroll, fg_color=bg,
                                corner_radius=8)
            card.pack(fill="x", pady=2)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=10, pady=(6, 0))

            ctk.CTkLabel(
                top_row, text=f"{icon} {pn}",
                font=S["font_normal"], text_color=COLORS["text_primary"],
                anchor="w",
            ).pack(side="left")

            ctk.CTkLabel(
                top_row, text=f"{delta:+d} → {new_qty}",
                font=S["font_normal"],
                text_color=COLORS["danger"] if is_withdraw else COLORS["success"],
                anchor="e",
            ).pack(side="right")

            bot_row = ctk.CTkFrame(card, fg_color="transparent")
            bot_row.pack(fill="x", padx=10, pady=(0, 6))

            detail_text = time_str
            if reason:
                detail_text += f"  •  {reason}"

            ctk.CTkLabel(
                bot_row, text=detail_text,
                font=S["font_small"], text_color=COLORS["text_muted"],
                anchor="w",
            ).pack(side="left")

    # ── Scanner Input ─────────────────────────────────────────────────
    def _on_key(self, event):
        # Don't capture if a text entry has focus
        focused = self.focus_get()
        if isinstance(focused, (ctk.CTkEntry, tk.Entry)):
            return

        # No text box has focus — collect the scan here instead. Finishes on
        # Enter/Tab, or on its own after a short pause if no suffix is sent.
        if event.keysym in ("Return", "KP_Enter", "Tab"):
            self._flush_buffer()
            return "break"

        if event.char and event.char.isprintable():
            self._scan_buffer += event.char
            if self._scan_timer_id:
                self.after_cancel(self._scan_timer_id)
            self._scan_timer_id = self.after(150, self._flush_buffer)

    def _flush_buffer(self):
        if self._scan_timer_id:
            try:
                self.after_cancel(self._scan_timer_id)
            except Exception:
                pass
            self._scan_timer_id = None
        code, self._scan_buffer = self._scan_buffer, ""
        if len(clean_barcode(code)) >= 4:
            self._process_scan(code)

    def _clear_buffer(self):
        self._scan_buffer = ""

    def _process_scan(self, barcode):
        barcode = clean_barcode(barcode)
        if not barcode:
            return

        self._barcode_entry.delete(0, "end")

        part = self.db.get_part_by_barcode(barcode)
        if part:
            self._show_part_detail(part)
            self._set_status(
                f"Found: {part.get('internal_part_number', barcode)}",
                COLORS["success"])
            # Reset qty to 1 but keep focus on the barcode box, so the
            # next scan goes to the right place
            self._set_qty("1")
            self._barcode_entry.focus_set()
        else:
            self._clear_part_detail()
            self._set_status(f"Not found: {barcode}", COLORS["danger"])

    # ── Adjust Quantity ───────────────────────────────────────────────
    def _adjust(self, sign):
        if not self._current_part:
            self._set_status("Scan a part first", COLORS["warning"])
            return

        try:
            qty = int(self._qty_entry.get())
        except ValueError:
            self._set_status("Enter a valid quantity", COLORS["danger"])
            return

        if qty <= 0:
            self._set_status("Quantity must be positive", COLORS["danger"])
            return

        delta = qty * sign
        reason = self._reason_entry.get().strip()
        part_id = self._current_part["id"]

        try:
            new_qty = self.db.adjust_quantity(part_id, delta, reason)
        except Exception as e:
            self._set_status(f"Error: {e}", COLORS["danger"])
            return

        action = "Withdrew" if sign < 0 else "Restocked"
        pn = (self._current_part.get("internal_part_number") or
              self._current_part.get("mfg_part_number", ""))

        self._set_status(
            f"{action} {qty} × {pn}  →  New qty: {new_qty}",
            COLORS["success"] if sign > 0 else COLORS["warning"])

        # Record in session history
        self._history.append({
            "timestamp": datetime.now().isoformat(),
            "part_id": part_id,
            "mfg_part_number": self._current_part.get("mfg_part_number", ""),
            "internal_part_number": self._current_part.get("internal_part_number", ""),
            "action": "withdraw" if sign < 0 else "restock",
            "delta": delta,
            "old_quantity": self._current_part.get("quantity", 0),
            "new_quantity": new_qty,
            "reason": reason,
        })

        # Update display
        self._current_part["quantity"] = new_qty
        min_qty = self._current_part.get("min_quantity", 0)
        qty_color = COLORS["danger"] if (new_qty <= min_qty and min_qty > 0) else COLORS["success"]
        self._qty_display.configure(text=str(new_qty), text_color=qty_color)

        self._refresh_history()
        self._update_count()

        # Flash background to confirm
        self._flash_confirm(sign)

        # Reset for next scan
        self._reason_entry.delete(0, "end")
        self._set_qty("1")
        self._barcode_entry.focus_set()

    def _flash_confirm(self, sign):
        color = COLORS["scan_success"] if sign > 0 else COLORS["scan_danger"]
        orig = COLORS["scan_bg"]
        self.configure(fg_color=color)
        self.after(200, lambda: self.configure(fg_color=orig))

    # ── Helpers ───────────────────────────────────────────────────────
    def _set_status(self, text, color=COLORS["text_primary"]):
        self._status_label.configure(text=text, text_color=color)

    def _update_clock(self):
        now = datetime.now().strftime("%I:%M %p  •  %A, %B %d")
        self._clock_label.configure(text=now)
        self.after(30000, self._update_clock)

    def _update_count(self):
        try:
            stats = self.db.get_stats()
            self._count_label.configure(
                text=f"📦 {stats['total_parts']} parts  •  "
                     f"⚠️ {stats['low_stock_count']} low stock  •  "
                     f"Session: {len(self._history)} actions")
        except Exception:
            pass

    def _exit(self):
        try:
            self.attributes("-fullscreen", False)
        except Exception:
            pass
        self.destroy()
