# -*- mode: python ; coding: utf-8 -*-
# --onedir build: produces dist/egx-intelligence-api/ folder.
# The folder is bundled as a Tauri resource, avoiding the %TEMP% self-extraction
# that triggers Windows Defender ASR rule "Block executable files from running
# unless they meet a prevalence, age, or trusted list criteria".
import os
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['aiosqlite']
tmp_ret = collect_all('app')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

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
