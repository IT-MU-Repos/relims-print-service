# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ReLIMS Print Service (Windows)
# Build: pyinstaller build/build_service.spec

from pathlib import Path

block_cipher = None
base_dir = Path(SPECPATH).parent
service_dir = base_dir / 'service'

a = Analysis(
    [str(service_dir / 'app.py')],
    pathex=[str(service_dir)],
    binaries=[],
    datas=[
        (str(service_dir / 'static'), 'static'),
    ],
    hiddenimports=['win32print', 'win32api'],
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
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(base_dir / 'build' / 'icon.ico') if (base_dir / 'build' / 'icon.ico').exists() else None,
)
