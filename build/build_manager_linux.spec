# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ReLIMS Print Manager (Linux)
# Build: pyinstaller build/build_manager_linux.spec

from pathlib import Path

block_cipher = None
base_dir = Path(SPECPATH).parent
manager_dir = base_dir / 'manager'

a = Analysis(
    [str(manager_dir / 'main_linux.py')],
    pathex=[str(manager_dir)],
    binaries=[],
    datas=[],
    hiddenimports=['pystray._xorg', 'pystray._appindicator'],
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
    name='relims-print-manager',
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
