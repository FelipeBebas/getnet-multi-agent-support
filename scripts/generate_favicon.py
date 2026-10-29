"""Script to generate crisp favicon files:
- src/static/favicon.svg (vector SVG icon)
- src/static/favicon.ico (standard 32x32/16x16 ICO icon)
- src/static/favicon.png (high-res 64x64 PNG icon)
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "src" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# 1. Clean, modern SVG Favicon: Getnet brand red (#EC0000) background, rounded squircle, white 'G'
SVG_CONTENT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" rx="14" fill="#EC0000"/>
  <text x="32" y="47" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif" font-size="44" font-weight="900" fill="#FFFFFF" text-anchor="middle">G</text>
</svg>
""".strip() + "\n"

def make_png(width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> bytes:
    """Generate a valid 32-bit RGBA PNG from pixel tuples (r, g, b, a)."""
    # Header
    png = bytearray(b"\x89PNG\r\n\x1a\n")

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    png += struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    # IDAT
    raw_scanlines = bytearray()
    for y in range(height):
        raw_scanlines.append(0)  # filter type 0: None
        for x in range(width):
            r, g, b, a = pixels[y * width + x]
            raw_scanlines.extend((r, g, b, a))

    compressed = zlib.compress(bytes(raw_scanlines), level=9)
    idat_crc = zlib.crc32(b"IDAT" + compressed)
    png += struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)

    # IEND
    iend_crc = zlib.crc32(b"IEND")
    png += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    return bytes(png)

def make_ico(png_images: list[tuple[int, int, bytes]]) -> bytes:
    """Pack one or more PNG image payloads into a standard Windows ICO format."""
    count = len(png_images)
    header = struct.pack("<HHH", 0, 1, count)  # Reserved=0, Type=1 (ICO), Count
    entries = bytearray()
    image_data = bytearray()

    offset = 6 + 16 * count

    for width, height, png_bytes in png_images:
        w_byte = 0 if width >= 256 else width
        h_byte = 0 if height >= 256 else height
        size = len(png_bytes)
        entries += struct.pack("<BBBBHHII", w_byte, h_byte, 0, 0, 1, 32, size, offset)
        image_data += png_bytes
        offset += size

    return header + bytes(entries) + bytes(image_data)

def render_g_icon(size: int) -> list[tuple[int, int, int, int]]:
    """Render a rounded red square with a crisp white capital 'G' at given resolution."""
    # We will use Windows GDI via ctypes if available, or math-based rasterizer
    import ctypes
    from ctypes import wintypes

    try:
        hdc_screen = ctypes.windll.user32.GetDC(None)
        hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_screen)

        bmi = bytearray(40)
        # biSize=40, biWidth=size, biHeight=-size (top-down), biPlanes=1, biBitCount=32, biCompression=0 (BI_RGB)
        struct.pack_into("<IiiHHIIiiII", bmi, 0, 40, size, -size, 1, 32, 0, size * size * 4, 0, 0, 0, 0)

        p_bits = ctypes.c_void_p()
        h_bitmap = ctypes.windll.gdi32.CreateDIBSection(
            hdc_mem,
            ctypes.c_char_p(bytes(bmi)),
            0,
            ctypes.byref(p_bits),
            None,
            0,
        )

        h_old = ctypes.windll.gdi32.SelectObject(hdc_mem, h_bitmap)

        # Clear background to transparent
        ctypes.memset(p_bits, 0, size * size * 4)

        # Draw rounded red rectangle
        # Red: #EC0000 -> COLORREF 0x000000EC (BBGGRR)
        red_color = 0x000000EC
        brush = ctypes.windll.gdi32.CreateSolidBrush(red_color)
        pen = ctypes.windll.gdi32.CreatePen(0, 0, red_color)  # PS_SOLID
        ctypes.windll.gdi32.SelectObject(hdc_mem, brush)
        ctypes.windll.gdi32.SelectObject(hdc_mem, pen)

        radius = int(size * 0.22)
        ctypes.windll.gdi32.RoundRect(hdc_mem, 0, 0, size, size, radius * 2, radius * 2)

        # Draw white bold 'G'
        font_height = int(size * 0.72)
        # FW_BLACK = 900, CLEARTYPE_QUALITY = 5
        h_font = ctypes.windll.gdi32.CreateFontW(
            -font_height, 0, 0, 0, 900, 0, 0, 0, 1, 0, 0, 5, 0, "Arial"
        )
        ctypes.windll.gdi32.SelectObject(hdc_mem, h_font)
        ctypes.windll.gdi32.SetBkMode(hdc_mem, 1)  # TRANSPARENT
        ctypes.windll.gdi32.SetTextColor(hdc_mem, 0x00FFFFFF)  # White

        rect = (wintypes.RECT)()
        rect.left = 0
        rect.top = int(size * 0.02)
        rect.right = size
        rect.bottom = size

        # DT_CENTER = 1, DT_VCENTER = 4, DT_SINGLELINE = 32 -> 37
        ctypes.windll.user32.DrawTextW(hdc_mem, "G", 1, ctypes.byref(rect), 37)

        # Read back raw buffer (size * size * 4 bytes: B, G, R, A)
        raw_bytes = ctypes.string_at(p_bits, size * size * 4)

        pixels: list[tuple[int, int, int, int]] = []
        for i in range(0, len(raw_bytes), 4):
            b, g, r = raw_bytes[i], raw_bytes[i + 1], raw_bytes[i + 2]
            # Since GDI doesn't write alpha channel for text/shapes, set alpha=255 for non-black or inside shape
            # Or if color is red or white
            if r > 0 or g > 0 or b > 0:
                pixels.append((r, g, b, 255))
            else:
                pixels.append((0, 0, 0, 0))

        # Cleanup
        ctypes.windll.gdi32.SelectObject(hdc_mem, h_old)
        ctypes.windll.gdi32.DeleteObject(h_bitmap)
        ctypes.windll.gdi32.DeleteObject(brush)
        ctypes.windll.gdi32.DeleteObject(pen)
        ctypes.windll.gdi32.DeleteObject(h_font)
        ctypes.windll.gdi32.DeleteDC(hdc_mem)
        ctypes.windll.user32.ReleaseDC(None, hdc_screen)

        return pixels
    except Exception:
        # Fallback pure-math rendering if GDI is unavailable
        pixels = []
        for y in range(size):
            for x in range(size):
                # Simple red square with rounded corners
                # Check distance from corners
                corner_r = size * 0.2
                dx = max(0.0, max(corner_r - x, x - (size - 1 - corner_r)))
                dy = max(0.0, max(corner_r - y, y - (size - 1 - corner_r)))
                if dx * dx + dy * dy > corner_r * corner_r:
                    pixels.append((0, 0, 0, 0))
                else:
                    pixels.append((0xEC, 0x00, 0x00, 255))
        return pixels

def main():
    # 1. Save SVG
    svg_path = STATIC_DIR / "favicon.svg"
    svg_path.write_text(SVG_CONTENT, encoding="utf-8")
    print(f"Generated {svg_path}")

    # 2. Render 64x64 PNG
    p64 = render_g_icon(64)
    png64 = make_png(64, 64, p64)
    png_path = STATIC_DIR / "favicon.png"
    png_path.write_bytes(png64)
    print(f"Generated {png_path}")

    # 3. Render 32x32 and 16x16 for ICO
    p32 = render_g_icon(32)
    png32 = make_png(32, 32, p32)
    p16 = render_g_icon(16)
    png16 = make_png(16, 16, p16)

    ico_data = make_ico([(32, 32, png32), (16, 16, png16)])
    ico_path = STATIC_DIR / "favicon.ico"
    ico_path.write_bytes(ico_data)
    print(f"Generated {ico_path}")

if __name__ == "__main__":
    main()
