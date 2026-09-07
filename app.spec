# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：图片分类器（one-dir，console，带图标）。
模型/静态/词典外置到打包目录，运行数据走 %APPDATA%\\ImageTagger。
"""
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['server.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('static', 'static'),
        ('eht_tags.json', '.'),
        ('danbooru_zh.csv', '.'),
        ('assets/app.ico', 'assets'),
    ],
    hiddenimports=(
        collect_submodules('onnxruntime') +
        [
            'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
            'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
            'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
            'uvicorn.lifespan', 'uvicorn.lifespan.on',
            'pydantic', 'numpy',
        ]
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=['customtkinter', 'test', 'pytest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ImageTagger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon='assets/app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='ImageTagger',
)
