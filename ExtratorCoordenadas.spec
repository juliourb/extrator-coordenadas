# -*- mode: python ; coding: utf-8 -*-
# Gera um único executável com o Tesseract embutido:
#   .venv\Scripts\pyinstaller ExtratorCoordenadas.spec --noconfirm

import os
import sys

# O venv foi criado a partir do Anaconda: os módulos nativos dele (_sqlite3,
# _tkinter, _ctypes, ...) dependem de DLLs em <anaconda>\Library\bin, que o
# PyInstaller não acha sozinho. Sem elas o exe só roda em máquinas com Anaconda.
_conda_bin = os.path.join(sys.base_prefix, 'Library', 'bin')
_extra_bins = [(os.path.join(_conda_bin, dll), '.')
               for dll in ('sqlite3.dll', 'tcl86t.dll', 'tk86t.dll', 'ffi.dll', 'ffi-8.dll',
                           'libexpat.dll', 'liblzma.dll', 'libbz2.dll', 'libmpdec-4.dll', 'zlib.dll')
               if os.path.exists(os.path.join(_conda_bin, dll))]

a = Analysis(
    ['app.py'],
    pathex=[_conda_bin] if os.path.isdir(_conda_bin) else [],
    binaries=_extra_bins,
    datas=[('tesseract', 'tesseract'), ('extrator/wkt.json', 'extrator'),
           ('assets/icone.ico', 'assets'), ('assets/italo.png', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Bibliotecas instaladas só para testes/desenvolvimento
    excludes=['pyproj', 'pyogrio', 'pandas', 'matplotlib', 'IPython', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ExtratorCoordenadas',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icone.ico',
)
