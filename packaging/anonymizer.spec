# -*- mode: python ; coding: utf-8 -*-
# PyInstaller špecifikácia – spúšťa sa z build.ps1:  pyinstaller packaging/anonymizer.spec
# Predpokladá, že build.ps1 pripravil build/tools/tesseract a build/tools/poppler.

from pathlib import Path

ROOT = Path(SPECPATH).parent
TOOLS = ROOT / "build" / "tools"

datas = [(str(ROOT / "anonymizer_sk" / "webapp" / "static"), "anonymizer_sk/webapp/static")]
if TOOLS.exists():
    datas.append((str(TOOLS), "tools"))
else:
    print("UPOZORNENIE: build/tools chýba – .exe nebude obsahovať Tesseract a Poppler")

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=[
        # handlery sa načítavajú dynamicky (importlib)
        "anonymizer_sk.handlers.text", "anonymizer_sk.handlers.docx",
        "anonymizer_sk.handlers.pdf", "anonymizer_sk.handlers.eml",
    ],
    excludes=["tkinter", "matplotlib", "numpy.tests", "IPython", "pytest",
              "presidio_analyzer", "spacy", "transformers", "torch", "docx", "reportlab"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Anonymizacia",
    icon=str(ROOT / "packaging" / "icon.ico"),
    console=False,                 # bez čierneho okna; log je v %LOCALAPPDATA%\anonymizer-sk
    version=str(ROOT / "packaging" / "version.txt"),
    upx=False,                     # UPX zvyšuje falošné poplachy antivírusov
)
coll = COLLECT(exe, a.binaries, a.datas, name="Anonymizacia", upx=False)
