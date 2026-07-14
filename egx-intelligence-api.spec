# -*- mode: python ; coding: utf-8 -*-
# --onedir build: produces dist/egx-intelligence-api/ folder.
# The folder is bundled as a Tauri resource, avoiding the %TEMP% self-extraction
# that triggers Windows Defender ASR rule "Block executable files from running
# unless they meet a prevalence, age, or trusted list criteria".
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['aiosqlite']
tmp_ret = collect_all('app')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Bundle vcruntime140.dll alongside the exe so python312.dll can load it
# on machines where the VC++ 2015-2022 redistributable is not installed.
_python_dir = Path(sys.executable).parent
for _dll in ('vcruntime140.dll', 'vcruntime140_1.dll'):
    _dll_path = _python_dir / _dll
    if _dll_path.exists():
        binaries.append((str(_dll_path), '.'))

a = Analysis(
    ['desktop\\sidecar_server.py'],
    pathex=[os.getcwd()],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='egx-intelligence-api',
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='egx-intelligence-api',
)
