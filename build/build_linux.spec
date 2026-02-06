# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ReLIMS Print Service (Linux)
# Build: pyinstaller build/build_linux.spec

import sys
from pathlib import Path

block_cipher = None
base_dir = Path(SPECPATH).parent

a = Analysis(
    [str(base_dir / 'app_linux.py')],
    pathex=[str(base_dir)],
    binaries=[],
    datas=[
        (str(base_dir / 'static'), 'static'),
    ],
    hiddenimports=['pystray._xorg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='relims-print-service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
