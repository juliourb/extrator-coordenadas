"""Renderização de páginas e OCR com o Tesseract embutido."""

import os
import sys
import subprocess
from dataclasses import dataclass

import pymupdf
import pytesseract
from PIL import Image, ImageFilter, ImageOps


def _base_dir() -> str:
    # Empacotado (PyInstaller) os arquivos ficam em sys._MEIPASS
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


TESSERACT_DIR = os.path.join(_base_dir(), "tesseract")
TESSDATA_DIR = os.path.join(TESSERACT_DIR, "tessdata").replace("\\", "/")
pytesseract.pytesseract.tesseract_cmd = os.path.join(TESSERACT_DIR, "tesseract.exe")
# A pasta pode ter espaços; passar via variável de ambiente evita problemas de aspas no --tessdata-dir
os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR

# Evita abrir uma janela de console a cada chamada do tesseract no exe sem console
if os.name == "nt":
    _orig_popen = subprocess.Popen

    class _SilentPopen(_orig_popen):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    pytesseract.pytesseract.subprocess.Popen = _SilentPopen


def _config(psm: int, extra: str = "") -> str:
    return f"--psm {psm} {extra}".strip()


def render(page: pymupdf.Page, dpi: int, clip=None, rotate: int = 0) -> Image.Image:
    """Renderiza a página em tons de cinza."""
    mat = pymupdf.Matrix(dpi / 72, dpi / 72).prerotate(rotate)
    pix = page.get_pixmap(matrix=mat, colorspace=pymupdf.csGRAY, clip=clip)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def binarize(im: Image.Image, blur: float = 1.0, thresh: int = 170) -> Image.Image:
    """Normaliza contraste e binariza. O desfoque leve une os pontos da fonte matricial."""
    im = ImageOps.autocontrast(im, cutoff=2)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return im.point(lambda v: 255 if v > thresh else 0)


def ocr_text(im: Image.Image, psm: int = 6, lang: str = "por", extra: str = "") -> str:
    return pytesseract.image_to_string(im, lang=lang, config=_config(psm, extra))


@dataclass
class Word:
    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    conf: float
    line: tuple

    @property
    def xc(self):
        return (self.x0 + self.x1) / 2

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2


def ocr_words(im: Image.Image, psm: int = 6, lang: str = "por", extra: str = "") -> list[Word]:
    d = pytesseract.image_to_data(im, lang=lang, config=_config(psm, extra),
                                  output_type=pytesseract.Output.DICT)
    words = []
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if not t:
            continue
        words.append(Word(t, d["left"][i], d["top"][i], d["left"][i] + d["width"][i],
                          d["top"][i] + d["height"][i], float(d["conf"][i]),
                          (d["block_num"][i], d["par_num"][i], d["line_num"][i])))
    return words
