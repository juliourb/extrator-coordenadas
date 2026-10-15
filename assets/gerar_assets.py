r"""Gera o ícone (assets/icone.ico) e o retrato em pixel art (assets/italo.png).

Executar: .venv\Scripts\python assets\gerar_assets.py
"""
import os
from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))


def icone():
    """Pino de mapa vermelho sobre uma grade de coordenadas."""
    s = 256
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, s - 8, s - 8), radius=44, fill=(36, 84, 140))
    for k in range(1, 4):  # grade
        x = 8 + k * (s - 16) // 4
        d.line((x, 24, x, s - 24), fill=(90, 140, 200), width=6)
        d.line((24, x, s - 24, x), fill=(90, 140, 200), width=6)
    cx, cy, r = 128, 104, 62  # pino
    d.polygon([(cx - 52, cy + 34), (cx + 52, cy + 34), (cx, 228)], fill=(214, 48, 49))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(214, 48, 49))
    d.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), fill=(255, 255, 255))
    im.save(os.path.join(AQUI, "icone.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.resize((64, 64), Image.LANCZOS).save(os.path.join(AQUI, "icone.png"))


# Retrato frontal: cabelo cacheado escuro, barba curta, camisa vermelha, alça da bolsa.
PALETA = {
    ".": None,
    "H": (24, 18, 14), "h": (58, 42, 32),        # cabelo
    "S": (204, 146, 108), "s": (172, 118, 84),   # pele / sombra
    "B": (122, 86, 64), "D": (52, 36, 28),       # barba rala / bigode
    "E": (20, 16, 14), "W": (240, 236, 230),     # olho
    "M": (140, 74, 62),                          # boca
    "R": (200, 40, 44), "r": (150, 26, 32),      # camisa
    "K": (30, 30, 34),                           # alça
}
PIXELS = [
    ".......h.H..H.h.H.......",
    "......h.HH.Hh.HH.h......",
    "....hHHHHhHHHHhHHHHh....",
    "...HHhHHHHHHhHHHHHhHH...",
    "..hHHHHHhHHHHHHhHHHHHh..",
    "..HHhHHHHHHHHHHHHHHhHH..",
    ".hHHHHHHhHHHHHhHHHHHHHh.",
    ".HHHhHSSSSSSSSSSSShHHHH.",
    ".hHHHSSSSSSSSSSSSSSHHHh.",
    "..HHSSSSSSSSSSSSSSSSHH..",
    "..HHSSHHHSSSSSSHHHSSHH..",
    "..hSSSSSSSSSSSSSSSSSSh..",
    "..sSSWEESSSSSSSSEEWSSs..",
    "..sSSSSSSSSssSSSSSSSSs..",
    "...SSSSSSSSssSSSSSSSS...",
    "...SSSSSSSSSssSSSSSSS...",
    "...BSSSSSSssssSSSSSSB...",
    "...BBSSSSDDDDDDSSSSBB...",
    "....BBSSBDMMMMDBSSBB....",
    "....BBBBBBBBBBBBBBBB....",
    ".....BBBBBBBBBBBBBB.....",
    "......BBBBBBBBBBBB......",
    "........ssSSSSss........",
    "........sSSSSSSs........",
    ".....RRRRsSSSSsRRRRK....",
    "...RRRRRRRsssssRRRKRR...",
    "..RRRRRRRRRRRRRRRKRRRR..",
    ".RRRRRRRRRRRRRRRKRRRRRR.",
    ".RRrRRRRRRRRRRRKRRRRrRR.",
    "RRRrRRRRRRRRRRKRRRRRrRRR",
    "RRRrRRRRRRRRRKRRRRRRrRRR",
    "RRRrRRRRRRRRKRRRRRRRrRRR",
    "RRRrRRRRRRRKRRRRRRRRrRRR",
    "RRRrRRRRRRKRRRRRRRRRrRRR",
]


def retrato(escala=8):
    w = max(len(l) for l in PIXELS)
    im = Image.new("RGBA", (w, len(PIXELS)), (0, 0, 0, 0))
    for y, linha in enumerate(PIXELS):
        for x, ch in enumerate(linha.ljust(w, ".")):
            cor = PALETA[ch]
            if cor:
                im.putpixel((x, y), cor + (255,))
    im = im.resize((w * escala, len(PIXELS) * escala), Image.NEAREST)
    im.save(os.path.join(AQUI, "italo.png"))


if __name__ == "__main__":
    assert all(len(l) == 24 for l in PIXELS), [len(l) for l in PIXELS]
    icone()
    retrato()
    print("ok")
