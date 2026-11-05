"""
Parts Inventory Tracker - Scanner input detection

Keyboard-wedge barcode scanners (like the Panasonic CF-33's built-in
reader) "type" the barcode very fast. Some send Enter afterwards, some send
Tab, and some send nothing at all. This helper recognizes a scan by its
typing speed, so scans work no matter which suffix the scanner is set to
send — and no matter which text box happens to have focus.
"""
import re
import time

# A scanner types a character every ~5-30 ms; people are 80 ms+.
MAX_GAP_MS = 60
MIN_SCAN_LEN = 4
SETTLE_MS = 150   # no suffix sent? treat the scan as done after this pause

_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")   # e.g. "]C0"


def clean_barcode(value: str) -> str:
    """Strip whitespace, control characters and AIM symbology prefixes that
    some scanners add in front of the data."""
    value = "".join(ch for ch in (value or "") if ch.isprintable()).strip()
    value = _AIM_PREFIX.sub("", value)
    return value.strip()


class ScanDetector:
    """Attach to an entry widget.

    on_scan(code)      — called when a fast scanner burst is detected. Any
                         characters the scanner typed into the box are
                         removed again, so a scan into the quantity box
                         won't corrupt the quantity.
    on_manual_enter()  — optional; called when the user presses Enter
                         after typing by hand.
    """

    def __init__(self, widget, on_scan, on_manual_enter=None):
        self.widget = widget
        self.on_scan = on_scan
        self.on_manual_enter = on_manual_enter
        self._burst = ""
        self._snapshot = ""
        self._last = 0.0
        self._timer = None

        widget.bind("<KeyPress>", self._on_key, add="+")
        widget.bind("<Return>", self._on_suffix, add="+")
        widget.bind("<KP_Enter>", self._on_suffix, add="+")
        widget.bind("<Tab>", self._on_suffix, add="+")

    def _now_ms(self):
        return time.monotonic() * 1000

    def _on_key(self, event):
        ch = event.char
        if not ch or not ch.isprintable():
            return
        now = self._now_ms()
        if now - self._last > MAX_GAP_MS:
            # Start of a new sequence: remember the box's text *before*
            # this keystroke lands, in case this turns out to be a scan.
            try:
                self._snapshot = self.widget.get()
            except Exception:
                self._snapshot = ""
            self._burst = ""
        self._burst += ch
        self._last = now
        self._schedule_settle()

    def _schedule_settle(self):
        if self._timer is not None:
            try:
                self.widget.after_cancel(self._timer)
            except Exception:
                pass
        self._timer = self.widget.after(SETTLE_MS, self._settle)

    def _settle(self):
        self._timer = None
        if len(self._burst) >= MIN_SCAN_LEN:
            self._finish()
        else:
            self._burst = ""

    def _on_suffix(self, event):
        recent = self._now_ms() - self._last < 300
        if len(self._burst) >= MIN_SCAN_LEN and recent:
            if self._timer is not None:
                try:
                    self.widget.after_cancel(self._timer)
                except Exception:
                    pass
                self._timer = None
            self._finish()
            return "break"
        self._burst = ""
        if event.keysym in ("Return", "KP_Enter") and self.on_manual_enter:
            self.on_manual_enter()
            return "break"
        return None

    def _finish(self):
        code = clean_barcode(self._burst)
        self._burst = ""
        # Put the box back the way it was before the scanner typed into it
        try:
            self.widget.delete(0, "end")
            if self._snapshot:
                self.widget.insert(0, self._snapshot)
        except Exception:
            pass
        if len(code) >= MIN_SCAN_LEN:
            self.on_scan(code)
