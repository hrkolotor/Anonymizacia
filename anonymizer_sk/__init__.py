"""Anonymizácia a pseudonymizácia osobných údajov v slovenských dokumentoch.

Detekcia: slovenské rozpoznávače (regex + kontrolné súčty + kontext) a voliteľne
NER model, orchestrované cez Presidio. Výstup: vratný (šifrovaný trezor) alebo
trvalý režim pre TXT, DOCX, PDF (textové aj skenované) a EML.
"""

__version__ = "0.1.0"
