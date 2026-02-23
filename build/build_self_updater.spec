# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ReLIMS Self-Updater (cross-platform)
# Build: pyinstaller build/build_self_updater.spec

from pathlib import Path

block_cipher = None
base_dir = Path(SPECPATH).parent

a = Analysis(
    [str(base_dir / 'build' / 'self_update.py')],
    pathex=[str(base_dir / 'build')],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name='relims-self-updater',
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
