"""
Genera los iconos de la PWA (static/icon-192.png, icon-512.png) SIN dependencias
externas: encoder PNG mínimo con zlib de la stdlib.

Diseño: fondo oscuro (slate-900) + tres barras verdes ascendentes (gráfico al alza),
dentro del área segura del 20% para que se vea bien también como icono "maskable".

Reejecutar:  python make_icons.py
"""

import os
import struct
import zlib

BG = (15, 23, 42)     # slate-900
GREEN = (34, 197, 94)  # emerald-500
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(pixels, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def render(size: int) -> bytes:
    m = round(size * 0.20)                 # margen (área segura maskable)
    cw = size - 2 * m                       # ancho de contenido
    ch = size - 2 * m                       # alto de contenido
    baseline = size - m                     # base de las barras
    unit = cw / 8.0                         # 3 barras (2u) + 2 huecos (1u)
    bw = 2 * unit
    heights = [0.42, 0.68, 0.96]            # alturas relativas ascendentes
    bars = []
    for i, hf in enumerate(heights):
        x0 = m + i * (bw + unit)
        x1 = x0 + bw
        y0 = baseline - hf * ch
        y1 = baseline
        bars.append((x0, x1, y0, y1))

    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filtro None
        for x in range(size):
            r, g, b = BG
            for (x0, x1, y0, y1) in bars:
                if x0 <= x < x1 and y0 <= y < y1:
                    r, g, b = GREEN
                    break
            rows += bytes((r, g, b))
    return _png(size, size, bytes(rows))


def main() -> None:
    os.makedirs(STATIC, exist_ok=True)
    for size in (192, 512):
        path = os.path.join(STATIC, f"icon-{size}.png")
        with open(path, "wb") as f:
            f.write(render(size))
        print(f"escrito {path}")


if __name__ == "__main__":
    main()
