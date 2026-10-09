"""Vstupný bod pre PyInstaller (Anonymizacia.exe)."""

import sys

from anonymizer_sk.desktop import main

if __name__ == "__main__":
    sys.exit(main())
