"""
Parts Inventory Tracker - Barcode & Label Manager
Generates Code128 barcodes and prints to Dymo LabelWriter 550.
"""
import os
import subprocess
import sys
import tempfile

from barcode import Code128
from PIL import Image, ImageDraw, ImageFont


# ── Font discovery ─────────────────────────────────────────────────────
# PyInstaller .exe builds don't always include python-barcode's bundled
# font, which causes "cannot open resource". We search for a font that
# actually exists on this machine instead of trusting the default.

def _font_candidates(kind: str) -> list[str]:
    win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    try:
        import barcode as _bc
        bc_fonts = os.path.join(os.path.dirname(_bc.__file__), "fonts")
    except Exception:
        bc_fonts = ""
    # When frozen, PyInstaller extracts bundled data under sys._MEIPASS
    mei = getattr(sys, "_MEIPASS", "")
    mei_fonts = os.path.join(mei, "barcode", "fonts") if mei else ""

    if kind == "mono":
        return [
            os.path.join(win_fonts, "consola.ttf"),
            os.path.join(win_fonts, "cour.ttf"),
            os.path.join(mei_fonts, "DejaVuSansMono.ttf") if mei_fonts else "",
            os.path.join(bc_fonts, "DejaVuSansMono.ttf") if bc_fonts else "",
            os.path.join(win_fonts, "arial.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    if kind == "bold":
        return [
            os.path.join(win_fonts, "arialbd.ttf"),
            os.path.join(win_fonts, "segoeuib.ttf"),
            os.path.join(win_fonts, "arial.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    return [
        os.path.join(win_fonts, "arial.ttf"),
        os.path.join(win_fonts, "segoeui.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def find_font_path(kind: str = "regular") -> str:
    """Return the first font file that exists, or '' if none found."""
    for p in _font_candidates(kind):
        if p and os.path.isfile(p):
            return p
    return ""


def load_font(size: int, kind: str = "regular"):
    path = find_font_path(kind)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_barcode_image(barcode_value: str, max_width_px: int,
                       bar_height_px: int, text_size_px: int = 0) -> Image.Image:
    """Draw a scanner-friendly Code128 barcode at exact pixel widths.

    Every bar and space is a whole number of printer dots and the image is
    never resized afterwards, so bar-width ratios stay exact. (Resizing a
    barcode blurs and distorts the bars — hardware scanners reject that.)

    The result is exactly max_width_px wide with the bars centered; the
    white space on either side is the scanner's required quiet zone.
    """
    pattern = Code128(barcode_value).build()[0]   # "1101001..." one char per module
    n = len(pattern)

    # Pick the widest whole-pixel module that still leaves a proper quiet
    # zone. At 300 DPI: 4px = 13 mil, 3px = 10 mil (ideal), 2px = 6.7 mil.
    module = 2
    for k in (4, 3):
        if n * k + 2 * 10 * k <= max_width_px:      # full 10-module quiet zone
            module = k
            break
    else:
        if n * 3 + 2 * 6 * 3 <= max_width_px:       # 6-module quiet zone is
            module = 3                              # fine for imaging scanners
    if n * module > max_width_px:                   # extremely long value
        module = max(1, max_width_px // (n + 12))

    bars_w = n * module
    text_gap = int(text_size_px * 0.25) if text_size_px else 0
    height = bar_height_px + (text_gap + text_size_px + 4 if text_size_px else 0)

    img = Image.new("L", (max_width_px, height), 255)
    draw = ImageDraw.Draw(img)
    left = (max_width_px - bars_w) // 2

    # Draw runs of black modules as single solid rectangles
    i = 0
    while i < n:
        if pattern[i] == "1":
            j = i
            while j < n and pattern[j] == "1":
                j += 1
            draw.rectangle([left + i * module, 0,
                            left + j * module - 1, bar_height_px - 1], fill=0)
            i = j
        else:
            i += 1

    # Human-readable value under the bars
    if text_size_px:
        font = load_font(text_size_px, "mono")
        tw = draw.textlength(barcode_value, font=font)
        draw.text(((max_width_px - tw) / 2, bar_height_px + text_gap),
                  barcode_value, fill=0, font=font)

    return img.convert("RGB")


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value)


class BarcodeManager:

    def __init__(self, labels_dir: str, label_width_mm: int = 54,
                 label_height_mm: int = 25):
        self.labels_dir = labels_dir
        self.last_sheet_pdf = ""
        os.makedirs(labels_dir, exist_ok=True)
        # Dymo 550 at 300 DPI
        self.dpi = 300
        self.label_width_px = int(label_width_mm * self.dpi / 25.4)
        self.label_height_px = int(label_height_mm * self.dpi / 25.4)

    def generate_barcode_image(self, barcode_value: str,
                                part_description: str = "",
                                internal_pn: str = "",
                                location_str: str = "") -> str:
        """Generate a label image with barcode + text, return path."""
        # Build composite label image
        label = Image.new("RGB", (self.label_width_px, self.label_height_px),
                          "white")
        draw = ImageDraw.Draw(label)

        # Pixel-exact barcode, full label width (edges act as quiet zone)
        bar_h = int(self.label_height_px * 0.38)
        bc_img = make_barcode_image(barcode_value, self.label_width_px,
                                    bar_h, text_size_px=24)
        y_offset = 10
        label.paste(bc_img, (0, y_offset))

        # Add text below barcode
        text_y = y_offset + bc_img.height + 6
        # Sizes in pixels at 300 DPI (~8pt / ~6pt when printed)
        font_large = load_font(34, "bold")
        font_small = load_font(25, "regular")

        # Internal part number (bold, larger)
        if internal_pn:
            draw.text((16, text_y), internal_pn, fill="black", font=font_large)
            text_y += 38

        # Description (smaller)
        if part_description:
            desc = part_description[:40]  # Truncate for label
            draw.text((16, text_y), desc, fill="black", font=font_small)
            text_y += 29

        # Location
        if location_str:
            loc = location_str[:40]
            draw.text((16, text_y), loc, fill="#555555", font=font_small)

        # Save final label
        safe_name = _safe_name(barcode_value)
        label_path = os.path.join(self.labels_dir, f"label_{safe_name}.png")
        label.save(label_path, dpi=(self.dpi, self.dpi))

        return label_path

    def print_label(self, image_path: str, printer_name: str = "") -> bool:
        """Print a label image to the Dymo LabelWriter 550."""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Label image not found: {image_path}")

        if sys.platform == "win32":
            return self._print_windows(image_path, printer_name)
        else:
            return self._print_linux(image_path, printer_name)

    def _print_windows(self, image_path: str, printer_name: str) -> bool:
        """Print via Windows GDI (win32print + win32ui)."""
        try:
            import win32print
            import win32ui
            from PIL import ImageWin

            if not printer_name:
                printer_name = win32print.GetDefaultPrinter()

            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            hdc.StartDoc(image_path)
            hdc.StartPage()

            img = Image.open(image_path)
            dib = ImageWin.Dib(img)
            # Print at actual size
            dib.draw(hdc.GetHandleOutput(),
                     (0, 0, self.label_width_px, self.label_height_px))

            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()
            return True
        except ImportError:
            # Fallback: use system print command
            os.startfile(image_path, "print")
            return True
        except Exception as e:
            raise RuntimeError(f"Print failed: {e}")

    def _print_linux(self, image_path: str, printer_name: str) -> bool:
        """Print via CUPS (lp command)."""
        cmd = ["lp"]
        if printer_name:
            cmd += ["-d", printer_name]
        cmd += [
            "-o", f"PageSize=Custom.{54}x{25}mm",
            "-o", "fit-to-page",
            image_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Print failed: {result.stderr}")
        return True

    def get_available_printers(self) -> list[str]:
        """Return list of available printer names."""
        if sys.platform == "win32":
            try:
                import win32print
                printers = win32print.EnumPrinters(
                    win32print.PRINTER_ENUM_LOCAL |
                    win32print.PRINTER_ENUM_CONNECTIONS
                )
                return [p[2] for p in printers]
            except ImportError:
                return ["(Install pywin32 for printer detection)"]
        else:
            try:
                result = subprocess.run(["lpstat", "-a"],
                                        capture_output=True, text=True)
                return [line.split()[0] for line in result.stdout.strip().split("\n")
                        if line.strip()]
            except Exception:
                return []

    def generate_label_sheet(self, labels: list[dict],
                              page_width_in: float = 8.5,
                              page_height_in: float = 11.0,
                              margin_in: float = 0.3,
                              label_w_in: float = 2.5,
                              label_h_in: float = 1.0,
                              gap_in: float = 0.12) -> list[str]:
        """Generate a printable sheet of labels as a PDF-ready image.

        Args:
            labels: list of dicts with keys: barcode, description,
                    internal_pn, location
            page_width_in / page_height_in: page size in inches
            margin_in: page margin in inches
            label_w_in / label_h_in: individual label size in inches
            gap_in: gap between labels in inches

        Returns:
            Path to the generated PNG sheet (or multiple sheets).
        """
        dpi = self.dpi
        page_w = int(page_width_in * dpi)
        page_h = int(page_height_in * dpi)
        margin = int(margin_in * dpi)
        lbl_w = int(label_w_in * dpi)
        lbl_h = int(label_h_in * dpi)
        gap = int(gap_in * dpi)

        usable_w = page_w - 2 * margin
        usable_h = page_h - 2 * margin

        cols = max(1, (usable_w + gap) // (lbl_w + gap))
        rows = max(1, (usable_h + gap) // (lbl_h + gap))
        per_page = cols * rows

        # Center the grid on the page
        grid_w = cols * lbl_w + (cols - 1) * gap
        grid_h = rows * lbl_h + (rows - 1) * gap
        offset_x = margin + (usable_w - grid_w) // 2
        offset_y = margin + (usable_h - grid_h) // 2

        # Font sizes scale with DPI so text is readable when printed
        font_large = load_font(int(dpi * 0.12), "bold")
        font_med = load_font(int(dpi * 0.09), "regular")
        font_small = load_font(int(dpi * 0.08), "regular")
        line_large = int(dpi * 0.14)
        line_med = int(dpi * 0.11)

        # Padding inside each label — defined once, outside any try block
        pad = int(lbl_w * 0.05)

        sheet_paths = []
        page_num = 0

        for start in range(0, len(labels), per_page):
            page_num += 1
            batch = labels[start:start + per_page]

            sheet = Image.new("RGB", (page_w, page_h), "white")
            draw = ImageDraw.Draw(sheet)

            for idx, lbl_data in enumerate(batch):
                row_i = idx // cols
                col_i = idx % cols

                x = offset_x + col_i * (lbl_w + gap)
                y = offset_y + row_i * (lbl_h + gap)

                # Draw cut line border (light gray dashed)
                draw.rectangle([x, y, x + lbl_w, y + lbl_h],
                               outline="#cccccc", width=1)

                # Generate barcode image
                barcode_value = lbl_data.get("barcode", "")
                if not barcode_value:
                    continue

                bc_top = y + int(dpi * 0.07)
                bc_h_total = 0
                try:
                    bc_img = make_barcode_image(
                        barcode_value, lbl_w - 20,
                        bar_height_px=int(dpi * 0.33),
                        text_size_px=int(dpi * 0.085))
                    sheet.paste(bc_img, (x + 10, bc_top))
                    bc_h_total = bc_img.height
                except Exception:
                    # If barcode generation fails, just show text
                    draw.text((x + 10, y + 10), barcode_value,
                              fill="black", font=font_med)

                # Text below barcode
                text_y = bc_top + max(bc_h_total, int(lbl_h * 0.4)) + 6
                text_x = x + pad

                internal_pn = lbl_data.get("internal_pn", "")
                if internal_pn:
                    draw.text((text_x, text_y), internal_pn,
                              fill="black", font=font_large)
                    text_y += line_large

                desc = lbl_data.get("description", "")[:35]
                if desc:
                    draw.text((text_x, text_y), desc,
                              fill="#333333", font=font_med)
                    text_y += line_med

                location = lbl_data.get("location", "")[:30]
                if location:
                    draw.text((text_x, text_y), location,
                              fill="#666666", font=font_small)

            # Save sheet
            sheet_name = f"label_sheet_page{page_num}.png"
            sheet_path = os.path.join(self.labels_dir, sheet_name)
            sheet.save(sheet_path, dpi=(dpi, dpi))
            sheet_paths.append(sheet_path)

        # Also save all pages as one PDF at true physical size. Printing
        # the PDF at "Actual size" keeps every bar exactly as drawn; photo
        # viewers often "fit to page", which rescales and blurs the bars.
        self.last_sheet_pdf = os.path.join(self.labels_dir, "label_sheet.pdf")
        pages = [Image.open(p).convert("RGB") for p in sheet_paths]
        if pages:
            pages[0].save(self.last_sheet_pdf, "PDF", resolution=float(dpi),
                          save_all=True, append_images=pages[1:])

        return sheet_paths
