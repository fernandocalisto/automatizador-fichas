#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "==> Executando suite de testes (headless)..."
QT_QPA_PLATFORM=offscreen python -m pytest -c pytest.ini tests

echo "==> Compilando executável com PyInstaller (build.spec)..."
python -m PyInstaller --clean --noconfirm build.spec

if [ -f "dist/AutomatizadorFichas.exe" ]; then
  BIN_PATH="dist/AutomatizadorFichas.exe"
elif [ -f "dist/AutomatizadorFichas" ]; then
  BIN_PATH="dist/AutomatizadorFichas"
else
  echo "Erro: binário não encontrado em dist/" >&2
  exit 1
fi

echo "==> Build concluído: $BIN_PATH ($(du -h "$BIN_PATH" | cut -f1))"
