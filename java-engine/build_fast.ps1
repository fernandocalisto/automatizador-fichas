$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$JarPath = Join-Path $RepoRoot "resources\bin\jasper-daemon.jar"
$SrcDir = Join-Path $PSScriptRoot "src\main\java\com\jasper\cli"

if (-not (Test-Path $JarPath)) {
    throw "Fat JAR não encontrado em: $JarPath"
}

function Resolve-JdkTool([string]$ToolName) {
    if ($env:JAVA_HOME) {
        $candidate = Join-Path $env:JAVA_HOME "bin\$ToolName"
        if (Test-Path $candidate) { return $candidate }
    }
    $jdk27 = "C:\Program Files\Java\jdk-27\bin\$ToolName"
    if (Test-Path $jdk27) { return $jdk27 }
    $cmd = Get-Command $ToolName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Ferramenta JDK '$ToolName' não encontrada."
}

$JavacExe = Resolve-JdkTool "javac.exe"
$JarExe = Resolve-JdkTool "jar.exe"

$TmpClasses = Join-Path ([System.IO.Path]::GetTempPath()) ("jasper_daemon_classes_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TmpClasses -Force | Out-Null

try {
    $JavaSources = @(Get-ChildItem -Path $SrcDir -Filter "*.java" -File | ForEach-Object { $_.FullName })
    if ($JavaSources.Count -eq 0) {
        throw "Nenhum arquivo .java encontrado em $SrcDir"
    }

    Write-Host "Compilando $($JavaSources.Count) arquivos Java (--release 11)..."
    & $JavacExe --release 11 -encoding UTF-8 -cp $JarPath -d $TmpClasses $JavaSources
    if ($LASTEXITCODE -ne 0) {
        throw "Falha na compilação javac (exit code $LASTEXITCODE)."
    }

    Write-Host "Atualizando fat JAR in-place: $JarPath"
    & $JarExe uf $JarPath -C $TmpClasses .
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao atualizar o fat JAR (exit code $LASTEXITCODE)."
    }

    Write-Host "Build concluído com sucesso: $JarPath"
} finally {
    if (Test-Path $TmpClasses) {
        Remove-Item -Recurse -Force $TmpClasses -ErrorAction SilentlyContinue
    }
}
