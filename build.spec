# -*- coding: utf-8 -*-
# PyInstaller spec file for Automatizador de Fichas (PySide6 v0.2.0+)
# Build: python -m PyInstaller --clean --noconfirm build.spec
# Output: dist/AutomatizadorFichas.exe (onefile, windowed)

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve() if "SPECPATH" in globals() else Path.cwd().resolve()
PROJECT_ROOT = SPEC_DIR
SRC_DIR = PROJECT_ROOT / "src"
RESOURCES_DIR = SRC_DIR / "resources"

block_cipher = None

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "src.resources.resources_rc",
]

datas = [
    (str(RESOURCES_DIR / "themes"), "resources/themes"),
    (str(RESOURCES_DIR / "editor_themes"), "resources/editor_themes"),
    (str(RESOURCES_DIR / "salutem_ferramenta_interna_logo.png"), "resources"),
    (str(RESOURCES_DIR / "select_padrao_ouro_jasper.sql"), "resources"),
    (str(RESOURCES_DIR / "SKILL.md"), "resources"),
]

binaries = []

excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "cv2",
    "torch",
    "tensorflow",
    "sklearn",
    "pytest",
    "pytest_cov",
    "pytest_qt",
    "unittest",
    "test",
    "tests",
    "IPython",
    "jupyter",
    "notebook",
    "sphinx",
    "PyQt5",
    "PyQt6",
]

a = Analysis(
    [str(SRC_DIR / "main.py")],
    pathex=[str(PROJECT_ROOT), str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AutomatizadorFichas",
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
    icon=str(RESOURCES_DIR / "salutem_ferramenta_interna_logo.png"),
)
