# -*- coding: utf-8 -*-
# PyInstaller spec file for Automatizador de Fichas
# Build: pyinstaller build.spec
# Output: dist/AutomatizadorFichas.exe (onefile, windowed)

import sys
import os
from pathlib import Path

# Project root - use sys.argv[0] (spec file path) or cwd
SPEC_DIR = Path(os.path.dirname(os.path.abspath(sys.argv[0])))
PROJECT_ROOT = SPEC_DIR
SRC_DIR = PROJECT_ROOT / "src"
RESOURCES_DIR = SRC_DIR / "resources"

block_cipher = None

# Hidden imports needed for PyInstaller to detect automatically
hiddenimports = [
    # PySide6 core
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtSvg",
    
    # QScintilla (PyQt6 binding) - explicitly included despite PyQt6 exclusion
    "PyQt6.Qsci",
    
    # Standard library modules that PyInstaller might miss
    "json",
    "re",
    "unicodedata",
    "pathlib",
    "datetime",
    "copy",
    "logging",
    "typing",
    "dataclasses",
    "enum",
    "functools",
    "itertools",
    "collections",
    "contextlib",
    "weakref",
    "abc",
    "importlib",
    "importlib.resources",
    "pkgutil",
    "inspect",
    "textwrap",
    "string",
    "hashlib",
    "base64",
    "mimetypes",
    "urllib.parse",
    "html",
    "csv",
    "sqlite3",
    "configparser",
    "argparse",
    "subprocess",
    "threading",
    "queue",
    "time",
    "os",
    "sys",
    "platform",
    "locale",
    "gettext",
    "tempfile",
    "shutil",
    "stat",
    "fnmatch",
    "glob",
    "pickle",
    "shelve",
    "marshal",
    "struct",
    "zlib",
    "gzip",
    "bz2",
    "lzma",
    "zipfile",
    "tarfile",
    "email",
    "json",
    "csv",
    "xml.etree.ElementTree",
    "html.parser",
    "urllib.request",
    "urllib.error",
    "http.client",
    "socket",
    "ssl",
    "select",
    "selectors",
    "asyncio",
    "concurrent.futures",
    "multiprocessing",
    "ctypes",
    "ctypes.util",
    "ctypes.wintypes",
    "msvcrt",
    "winreg",
    "winsound",
]

# Collect data files (resources)
datas = [
    # Themes
    (str(RESOURCES_DIR / "themes" / "light.qss"), "resources/themes"),
    (str(RESOURCES_DIR / "themes" / "dark.qss"), "resources/themes"),
    (str(RESOURCES_DIR / "themes" / "system.qss"), "resources/themes"),
    
    # Editor themes
    (str(RESOURCES_DIR / "editor_themes" / "vscode.json"), "resources/editor_themes"),
    (str(RESOURCES_DIR / "editor_themes" / "monokai.json"), "resources/editor_themes"),
    (str(RESOURCES_DIR / "editor_themes" / "dracula.json"), "resources/editor_themes"),
    (str(RESOURCES_DIR / "editor_themes" / "github.json"), "resources/editor_themes"),
    (str(RESOURCES_DIR / "editor_themes" / "solarized.json"), "resources/editor_themes"),
    
    # Icons
    (str(RESOURCES_DIR / "salutem_ferramenta_interna_logo.png"), "resources/icons"),
    
    # SKILL.md (está um nível acima do PROJECT_ROOT)
    (str(PROJECT_ROOT.parent / "Automatiza Ficha - Exemplos" / "SKILL.md"), "Automatiza Ficha - Exemplos"),
]

# Binary dependencies (none needed for pure Python)
binaries = []

# Exclude unnecessary modules to reduce size
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
    "setuptools",
    "pip",
    "wheel",
    "pkg_resources",
    "distutils",
    "pydoc",
    "doctest",
    "unittest",
    "test",
    "tests",
    "IPython",
    "jupyter",
    "notebook",
    "sphinx",
    "docutils",
    "pygments",
    "black",
    "flake8",
    "mypy",
    "pylint",
    "bandit",
    "safety",
    "coverage",
    # Exclude PyQt6 to avoid conflict with PySide6 (we only need PyQt6.Qsci)
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtPrintSupport",
    "PyQt6.QtSvg",
    "PyQt6.QtNetwork",
    "PyQt6.QtSql",
    "PyQt6.QtXml",
    "PyQt6.QtTest",
    "PyQt6.QtOpenGL",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebChannel",
    "PyQt6.QtPositioning",
    "PyQt6.QtLocation",
    "PyQt6.QtSensors",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtQuick",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtQml",
    "PyQt6.QtQuick3D",
    "PyQt6.QtCharts",
    "PyQt6.QtDataVisualization",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtLabsPlatform",
    "PyQt6.QtLabsSettings",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
    "PyQt6.QtQuickTimeline",
    "PyQt6.QtScxml",
    "PyQt6.QtStateMachine",
    "PyQt6.QtWebSockets",
    "PyQt6.QtXmlPatterns",
]

a = Analysis(
    ["src/main.py"],
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
    console=False,  # windowed (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RESOURCES_DIR / "salutem_ferramenta_interna_logo.png"),
)

# Splash screen (PyInstaller 6+)
splash = Splash(
    str(RESOURCES_DIR / "salutem_ferramenta_interna_logo.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(50, 50),
    text_size=12,
    text_color="white",
)

# Collect everything
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AutomatizadorFichas",
)