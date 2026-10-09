# anonymizer-sk

Anonymizácia osobných a citlivých údajov v slovenských dokumentoch: **Word, PDF (textové aj skenované), e-maily (.eml), TXT**.
Dva režimy:

| Režim | Čo urobí | Dá sa vrátiť? |
|---|---|---|
| `reversible` (pseudonymizácia) | údaje nahradí tokenmi `[OSOBA_001]`, `[RODNE_CISLO_001]` …; mapovanie uloží do **šifrovaného trezoru** (AES-256-GCM, kľúč z hesla cez scrypt) | áno, s trezorom a heslom |
| `irreversible` (anonymizácia) | rovnaké tokeny (alebo len `[OSOBA]`), nič sa neukladá, odstránia sa metadáta, autori revízií, smerovacie hlavičky e-mailov | nie |

## Rýchly štart

```bash
# systém: tesseract-ocr, tesseract-ocr-slk, poppler-utils  (alebo použite Dockerfile)
pip install -r requirements.txt

python -m anonymizer_sk selftest                      # overí inštaláciu a ktorý engine beží
python -m anonymizer_sk scan zmluva.docx              # náhľad nálezov (zobrazí originály, len lokálne!)

export ANON_PASSPHRASE='dlhe-silne-heslo'              # inak sa program spýta
python -m anonymizer_sk anonymize vstup/ -o vystup/ --mode reversible
python -m anonymizer_sk anonymize vstup/ -o vystup/ --mode irreversible
python -m anonymizer_sk restore vystup/*_anonym.* --vault vystup/trezor.vault -o obnovene/
```

Pri spracovaní priečinka zdieľajú všetky súbory jeden trezor, takže **tá istá osoba má rovnaký token vo všetkých dokumentoch**. Keď zadáte existujúci trezor (`--vault`), nové dokumenty naň nadviažu.
Trezor ukladajte **oddelene** od anonymizovaných súborov; kto má oboje aj heslo, vidí originál.

Obnova funguje aj na texte, ktorý vznikol z anonymizovaného dokumentu, napr. na zhrnutí od LLM s tokenmi `[OSOBA_001]`: uložte ho ako .txt a spustite `restore`.

## Desktopová verzia (Windows .exe)

Pre bežných používateľov je určené grafické rozhranie, ktoré sa otvorí v prehliadači, no beží výlučne na danom počítači (`127.0.0.1`, prístup chránený náhodným tokenom). Postup v rozhraní:

1. Pretiahnuť dokumenty (aj celý priečinok).
2. Skontrolovať nájdené údaje. Údaje sú zoskupené podľa osoby vrátane všetkých gramatických tvarov, každý s ukážkou kontextu. Zrušením zaškrtnutia sa údaj ponechá, chýbajúci výraz sa dá doplniť.
3. Zvoliť režim **vratne** (heslo + súbor trezoru) alebo **natrvalo**.
4. Stiahnuť ZIP s dokumentmi a protokolom, pri vratnom režime aj trezor.

Na samostatnej karte sa obnovujú originály: anonymizované dokumenty + trezor + heslo.
Dokumenty sa držia iba v pamäti. Aplikácia sa ukončí po zatvorení okna alebo po 3 minútach bez aktivity a druhé spustenie len otvorí už bežiace okno.

Vyskúšanie bez inštalácie: `python -m anonymizer_sk ui`

### Zostavenie inštalátora

Na Windows s Pythonom 3.12 (64-bit):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Skript nainštaluje závislosti, pribalí Tesseract (so slovenčinou) a Poppler, spustí testy, zostaví `Anonymizacia.exe` (PyInstaller), overí, že odpovedá, a vytvorí `dist\Anonymizacia-0.1.0-setup.exe` (Inno Setup). Inštalátor nevyžaduje práva správcu a vytvorí zástupcu v ponuke Štart a voliteľne na ploche.
Rovnaký postup beží v GitHub Actions (`.github/workflows/build-windows.yml`): po pushnutí tagu `v*` alebo ručnom spustení vznikne inštalátor ako artefakt.

Bez podpisu certifikátom zobrazí Windows SmartScreen varovanie „Neznámy vydavateľ“. Na nasadenie vo firme odporúčam podpísať: `build.ps1 -SignCert firma.pfx -SignPassword ...`.
Nastavenia (prah, zoznamy výrazov) môže správca nasadiť ako `%LOCALAPPDATA%\anonymizer-sk\config.yaml` (vzor `config.example.yaml`).

Desktopová verzia 0.1 používa slovenské pravidlá bez Presidia a NER modelu, teda časť pokrytú testami. NER doplníme cez ONNX Runtime (inštalátor tak narastie asi o 150 až 250 MB, nie o 1,5 GB ako s torch), keď sa overí na reálnych dokumentoch.

## Čo sa rozpoznáva

| Typ | Ako |
|---|---|
| `RODNE_CISLO` | formát + deliteľnosť 11 + platný dátum (aj ženy +50, od 2004 +20/+70, 9-miestne do 1953) |
| `ICO`, `DIC`, `IC_DPH` | kontrolný súčet IČO, deliteľnosť IČ DPH; vyžaduje kontext („IČO:“) |
| `IBAN`, `UCET`, `KARTA` | mod-97, domáci formát `123-456/0900` s kontextom, Luhn |
| `TELEFON`, `EMAIL`, `IP_ADRESA` | +421 / 09xx / pevné linky, e-mail, IPv4 |
| `DOKLAD`, `SPZ`, `DATUM_NARODENIA` | OP/pas s kontextom, EČV, dátum pri „nar.“ |
| `ADRESA` | ulica + číslo + PSČ + obec; hodnoty po „trvalý pobyt:“, „bytom“, „sídlo:“ … |
| `OSOBA` | tituly (Ing., JUDr. …), ~200 slovenských krstných mien v pádoch, polia zmlúv („Predávajúci:“, „Meno a priezvisko:“), „pán/pani X“, oslovenie a podpis v e-mailoch, **NER model** |
| `ORGANIZACIA`, `LOKALITA` | s.r.o./a.s. a NER; predvolene **vypnuté** (nie sú osobné údaje) |
| `VLASTNE` | vlastný zoznam výrazov (`deny_list`) |

Skloňovanie: priezvisko nájdené raz (`Ján Novák`) sa dohľadá aj v ďalších tvaroch (`Nováka`, `Novákovi`, `pán Novák`) v celom dokumente aj v ďalších súboroch toho istého behu. Tvary sa zlúčia do jednej osoby: `[OSOBA_001]`, `[OSOBA_001/2]` … (varianty kvôli presnej obnove). `Nováková` sa vedie ako iná osoba než `Novák`.
Rozpoznávače bežia nad textom bez diakritiky, takže fungujú aj na OCR výstupe, ktorý stratil mäkčene.

## Architektúra

```
súbor ─► handler formátu ─► segmenty textu ─► Detector ─► Pseudonymizer ─► náhrady späť do formátu
          (docx/pdf/eml/txt)                    │                │
                                                │                └─ Vault (šifrovaný, len reversible)
                                                ├─ Presidio AnalyzerEngine (jazyk "sk")
                                                │     ├─ SlovakRulesRecognizer  (rules.py)
                                                │     └─ SlovakNerRecognizer    (SlovakBERT NER)
                                                └─ fallback bez Presidia: rules.py (+ voliteľne NER)
```

- **DOCX**: pracuje priamo s XML, takže pokryje hlavný text, tabuľky, hlavičky, päty, poznámky pod čiarou, komentáre, textové polia aj vymazaný text zo sledovaných zmien. Meno rozdelené do viacerých runov sa nahradí bez straty formátovania. Zo súboru odstráni autora, posledného editora, firmu a autorov revízií aj komentárov.
- **PDF**: slová s pozíciami berie z textovej vrstvy; ak strana nemá text alebo obsahuje obrázky, doplní OCR. Stranu vyrenderuje, údaje prekryje čiernym obdĺžnikom s tokenom a z obrázkov zostaví nové PDF s OCR vrstvou. Rasterizácia je zámerná: vo výstupe nezostanú skryté vrstvy, metadáta, formuláre, anotácie ani prílohy. Vratný režim uloží originál PDF šifrovane do trezoru.
- **EML**: spracuje hlavičky (From/To/Cc/Subject …), textové aj HTML telá, odkazy `mailto:` a prílohy (DOCX/PDF/TXT rovnakými handlermi so spoločnými tokenmi). Odstráni `Received`, `X-Originating-IP`, DKIM a ďalšie hlavičky s IP adresami. Nepodporované prílohy (obrázky, archívy) odstráni a zapíše do reportu.

Prečo nie Presidio Anonymizer: náhrady treba premietnuť do runov vo Worde, do súradníc v PDF a do uzlov HTML, a navyše držať konzistentné tokeny naprieč súbormi. Preto sa náhrady robia vlastným kódom a Presidio slúži na detekciu.

## Stav a overenie

**Otestované** (8/8 testov, `python tests/test_anonymizer.py`, s `--engine rules`):
validátory, detekcia, oba režimy na TXT, DOCX, textovom PDF, skenovanom PDF a EML s prílohami. Testy kontrolujú, že vo výstupe nezostal žiadny z originálov (vrátane OCR výstupného PDF), a že obnova z trezoru vráti pôvodný obsah.

Rozhranie má vlastný end-to-end test v reálnom prehliadači (`python tests/test_ui.py`, Playwright + Chromium). Test nahrá súbory, ponechá jeden nález, doplní výraz, anonymizuje vratne, stiahne výsledok, skontroluje, že v ňom nič nezostalo, overí odmietnutie zlého hesla a obnoví originály. Overené je aj ukončenie aplikácie po zatvorení okna či pri nečinnosti, odmietnutie požiadaviek bez tokenu alebo s cudzou hlavičkou Host a správanie pri druhom spustení.

Zostavenie na Windows (GitHub Actions, `windows-latest`) prechádza: testy so slovenským OCR, PyInstaller, kontrola, že `Anonymizacia.exe` odpovedá, a Inno Setup. Inštalátor sa stiahne ako artefakt *Anonymizacia-setup*.

**Neotestované, treba overiť u vás** (v prostredí, kde kód vznikol, boli PyPI aj Hugging Face blokované):
- inštalácia a používanie `setup.exe` na bežnom počítači (SmartScreen, antivírus, rôzne verzie Windows),
- `presidio_engine.py`, teda napojenie na Presidio s prázdnym spaCy modelom „sk“,
- `ner.py` so SlovakBERT NER, hlavne mapovanie labelov `LABEL_n` a výsledky na reálnych textoch,
- OCR so slovenčinou (`slk`); testy bežali s `eng`, čo je pomalšie a menej presné na diakritike,
- Dockerfile.

Po inštalácii spustite `python -m anonymizer_sk selftest --engine presidio` a testy.

## Známe obmedzenia

- Žiadna automatika nenájde 100 % údajov. Pred zdieľaním skontrolujte výstup (`*.report.json`, `scan`).
- Mená bez krstného mena, titulu či návestia sa nájdu len cez NER alebo dohľadaním už známeho priezviska.
- Obrázky vo Worde (napr. naskenovaný OP vložený do .docx) sa neanalyzujú, report na ne upozorní.
- Ručne písaný text a veľmi zlé skeny OCR nezvládne.
- Pseudonymizované dáta sú podľa GDPR stále osobné údaje. Až trvalý režim, bez trezoru a s overením, smeruje k anonymizácii.

## Ďalšie kroky

1. Overiť Presidio + NER na reálnych dokumentoch, doladiť `threshold` a zoznamy.
2. Zostaviť testovaciu sadu z reálnych (anonymizovaných) dokumentov a merať presnosť a úplnosť.
3. Pridať GLiNER2-PII ako ďalší rozpoznávač do Presidio registra a porovnať so SlovakBERT.
4. Pridať kontrolnú obrazovku (human-in-the-loop) nad `scan`, kde človek potvrdí alebo doplní nálezy.
