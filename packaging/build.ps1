<#
  Zostaví Anonymizacia.exe a inštalátor Anonymizacia-<verzia>-setup.exe.

  Spustenie (PowerShell, v koreňovom priečinku projektu):
      powershell -ExecutionPolicy Bypass -File packaging\build.ps1

  Potrebné: Python 3.11/3.12 (64-bit), internet pri prvom behu.
  Skript doinštaluje (ak chýbajú): Tesseract OCR, Poppler, Inno Setup 6 – cez Chocolatey alebo
  stiahnutím. Výsledok: dist\Anonymizacia-<verzia>-setup.exe

  Parametre:
    -SkipTests        nespúšťať testy pred zostavením
    -SignCert <pfx>   podpísať .exe a inštalátor firemným certifikátom (odporúčané, inak SmartScreen varuje)
#>
param(
    [switch]$SkipTests,
    [string]$SignCert = "",
    [string]$SignPassword = ""
)
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Build = Join-Path $Root "build"
$Tools = Join-Path $Build "tools"

function Step($msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }

# ------------------------------------------------------------------ Python prostredie
Step "Python prostredie"
if (-not (Test-Path ".venv-build")) { python -m venv .venv-build }
$Py = Join-Path $Root ".venv-build\Scripts\python.exe"
& $Py -m pip install --upgrade pip | Out-Null
& $Py -m pip install -r requirements-desktop.txt

# ------------------------------------------------------------------ Tesseract
Step "Tesseract OCR"
$TessSrc = @("$env:ProgramFiles\Tesseract-OCR", "${env:ProgramFiles(x86)}\Tesseract-OCR") |
    Where-Object { Test-Path (Join-Path $_ "tesseract.exe") } | Select-Object -First 1
if (-not $TessSrc) {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install tesseract -y --no-progress
    } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
    } else {
        throw "Nainštalujte Tesseract (https://github.com/UB-Mannheim/tesseract/wiki) a spustite skript znova."
    }
    $TessSrc = "$env:ProgramFiles\Tesseract-OCR"
}
$TessDst = Join-Path $Tools "tesseract"
if (Test-Path $TessDst) { Remove-Item $TessDst -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $TessDst "tessdata") | Out-Null
Copy-Item (Join-Path $TessSrc "*.exe") $TessDst
Copy-Item (Join-Path $TessSrc "*.dll") $TessDst
Copy-Item (Join-Path $TessSrc "tessdata\configs") (Join-Path $TessDst "tessdata") -Recurse -ErrorAction SilentlyContinue
# pdf.ttf je potrebný na OCR textovú vrstvu vo výstupnom PDF
Copy-Item (Join-Path $TessSrc "tessdata\pdf.ttf") (Join-Path $TessDst "tessdata") -ErrorAction SilentlyContinue
# len potrebné jazyky – inštalátor ostane menší
foreach ($lang in @("eng", "slk", "osd")) {
    $dst = Join-Path $TessDst "tessdata\$lang.traineddata"
    $src = Join-Path $TessSrc "tessdata\$lang.traineddata"
    if (Test-Path $src) { Copy-Item $src $dst }
    else {
        Write-Host "Sťahujem $lang.traineddata"
        Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata" -OutFile $dst
    }
}

# ------------------------------------------------------------------ Poppler
Step "Poppler"
$PopDst = Join-Path $Tools "poppler"
if (-not (Test-Path (Join-Path $PopDst "bin\pdftoppm.exe"))) {
    $headers = @{ "User-Agent" = "anonymizer-build" }
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }   # limit API v GitHub Actions
    $rel = Invoke-RestMethod "https://api.github.com/repos/oschwartz10612/poppler-windows/releases/latest" -Headers $headers
    $asset = $rel.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1
    $zip = Join-Path $Build "poppler.zip"
    New-Item -ItemType Directory -Force $Build | Out-Null
    Invoke-WebRequest $asset.browser_download_url -OutFile $zip
    $tmp = Join-Path $Build "poppler-tmp"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip $tmp
    $bin = Get-ChildItem $tmp -Recurse -Filter "pdftoppm.exe" | Select-Object -First 1
    New-Item -ItemType Directory -Force (Join-Path $PopDst "bin") | Out-Null
    Copy-Item (Join-Path $bin.DirectoryName "*") (Join-Path $PopDst "bin") -Recurse
    Remove-Item $tmp, $zip -Recurse -Force
}

# ------------------------------------------------------------------ testy
if (-not $SkipTests) {
    Step "Testy"
    $env:ANONYMIZER_TESSERACT = Join-Path $TessDst "tesseract.exe"
    $env:ANONYMIZER_POPPLER = Join-Path $PopDst "bin"
    $env:TESSDATA_PREFIX = Join-Path $TessDst "tessdata"
    & $Py tests\test_anonymizer.py
    if ($LASTEXITCODE -ne 0) { throw "Testy zlyhali – inštalátor sa nezostaví." }
    Remove-Item Env:ANONYMIZER_TESSERACT, Env:ANONYMIZER_POPPLER, Env:TESSDATA_PREFIX
}

# ------------------------------------------------------------------ PyInstaller
Step "PyInstaller"
& $Py -m PyInstaller packaging\anonymizer.spec --noconfirm --clean --distpath dist --workpath build\pyi
if ($LASTEXITCODE -ne 0) { throw "PyInstaller zlyhal." }

# rýchla kontrola zostaveného programu: spustí server bez prehliadača a hneď ho ukončí
Step "Kontrola .exe"
$p = Start-Process "dist\Anonymizacia\Anonymizacia.exe" -ArgumentList "--no-browser" -PassThru
Start-Sleep -Seconds 6
$info = Get-Content (Join-Path $env:LOCALAPPDATA "anonymizer-sk\instance.json") -Raw | ConvertFrom-Json
$r = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($info.port)/api/ping" -Headers @{ "X-Token" = $info.token } `
    -ContentType "application/json" -Body "{}"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($info.port)/api/quit" -Headers @{ "X-Token" = $info.token } `
    -ContentType "application/json" -Body "{}" | Out-Null
Start-Sleep -Seconds 2
if (-not $p.HasExited) { Stop-Process $p -Force }
if (-not $r.ok) { throw "Zostavený program neodpovedá." }
Write-Host "Anonymizacia.exe odpovedá – OK"

# ------------------------------------------------------------------ podpis (voliteľné)
function Sign($file) {
    if (-not $SignCert) { return }
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
        Where-Object { $_.FullName -like "*x64*" } | Select-Object -Last 1
    & $signtool.FullName sign /f $SignCert /p $SignPassword /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $file
}
Sign "dist\Anonymizacia\Anonymizacia.exe"

# ------------------------------------------------------------------ Inno Setup
Step "Inštalátor"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    if (Get-Command choco -ErrorAction SilentlyContinue) { choco install innosetup -y --no-progress }
    elseif (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
    } else { throw "Nainštalujte Inno Setup 6 (https://jrsoftware.org/isdl.php)." }
    $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
& $iscc packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup zlyhal." }
$setup = Get-ChildItem dist -Filter "Anonymizacia-*-setup.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
Sign $setup.FullName

Step "Hotovo"
Write-Host ("Inštalátor: {0}  ({1:N0} MB)" -f $setup.FullName, ($setup.Length / 1MB))
