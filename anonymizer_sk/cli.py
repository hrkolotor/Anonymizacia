"""Príkazový riadok.

  python -m anonymizer_sk anonymize VSTUP... -o VYSTUP --mode reversible|irreversible
  python -m anonymizer_sk restore VSTUP... --vault VYSTUP/trezor.vault -o OBNOVENE
  python -m anonymizer_sk scan VSTUP            # náhľad nálezov (zobrazí originály!)
  python -m anonymizer_sk selftest              # rýchly test inštalácie

Heslo k trezoru: premenná ANON_PASSPHRASE alebo interaktívna výzva.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path

from .api import Anonymizer, collect, restore_bytes
from .config import Config
from .detector import Detector
from .entities import ENTITY_LABELS
from .vault import Vault, VaultError


def _passphrase(confirm: bool) -> str:
    env = os.environ.get("ANON_PASSPHRASE")
    if env:
        return env
    pw = getpass.getpass("Heslo k trezoru: ")
    if confirm and getpass.getpass("Zopakujte heslo: ") != pw:
        sys.exit("Heslá sa nezhodujú.")
    if len(pw) < 12:
        sys.exit("Heslo musí mať aspoň 12 znakov.")
    return pw


def _cfg(args) -> Config:
    cfg = Config.load(args.config)
    if getattr(args, "engine", None):
        cfg.engine = args.engine
    if getattr(args, "threshold", None) is not None:
        cfg.threshold = args.threshold
    if getattr(args, "no_numbers", False):
        cfg.numbered_tokens = False
    return cfg


def cmd_anonymize(args):
    cfg = _cfg(args)
    out_dir = Path(args.output)
    vault, vault_path, pw = None, None, None
    if args.mode == "reversible":
        vault_path = Path(args.vault) if args.vault else out_dir / "trezor.vault"
        if vault_path.exists():
            pw = _passphrase(confirm=False)
            vault = Vault.open(vault_path, pw)
            print(f"Pokračujem v existujúcom trezore {vault_path} (tokeny ostanú konzistentné).")
        else:
            pw = _passphrase(confirm=True)
            vault = Vault()
    anon = Anonymizer(args.mode, cfg, vault)
    print(f"Režim: {args.mode} | detekcia: {anon.detector.engine_name}")
    total, failed = 0, 0
    for path in collect(args.inputs):
        try:
            target, report = anon.anonymize_file(path, out_dir)
        except Exception as exc:
            failed += 1
            print(f"  CHYBA {path}: {exc}", file=sys.stderr)
            continue
        total += len(report.findings)
        print(f"  {path.name} -> {target.name}: {len(report.findings)} náhrad")
        for w in report.warnings:
            print(f"    ! {w}")
    if vault is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        vault.save(vault_path, pw)
        print(f"Trezor uložený: {vault_path}  (uchovávajte ho oddelene od anonymizovaných súborov)")
    anon.finish()
    print(f"Spolu {total} náhrad. Pred zdieľaním výstup skontrolujte (report.json).")
    return 1 if failed else 0


def cmd_restore(args):
    try:
        vault = Vault.open(args.vault, _passphrase(confirm=False))
    except VaultError as exc:
        sys.exit(str(exc))
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in collect(args.inputs):
        try:
            data, n = restore_bytes(path.read_bytes(), path.name, vault, Config.load(args.config))
        except Exception as exc:
            print(f"  CHYBA {path}: {exc}", file=sys.stderr)
            continue
        stem = path.stem.removesuffix("_anonym")
        target = out_dir / f"{stem}_obnovene{path.suffix}"
        target.write_bytes(data)
        print(f"  {path.name} -> {target.name}: " + ("originál z trezoru" if n < 0 else f"{n} tokenov vrátených"))
    return 0


def cmd_scan(args):
    cfg = _cfg(args)
    from .core import Planner, Report
    from .handlers import handler_for
    from .pseudonymizer import Pseudonymizer

    det = Detector(cfg)
    print(f"Detekcia: {det.engine_name}\n")
    for path in collect(args.inputs):
        print(f"== {path}")
        report = Report()
        planner = Planner(det, Pseudonymizer("reversible"), report=report)
        handler_for(path.name).process(path.read_bytes(), planner, cfg, name=path.name)
        tokens = planner.pseudo.tokens
        for f in report.findings:
            print(f"  {f['entity']:16} {f['score']:.2f}  {f['token']:18} {tokens.get(f['token'], '')!r:40} "
                  f"[{f['source']}]")
        for w in report.warnings:
            print(f"  ! {w}")
    return 0


def cmd_selftest(args):
    cfg = _cfg(args)
    det = Detector(cfg)
    sample = ("Predávajúci: Ing. Ján Novák, nar. 15. 3. 1980, r. č. 800315/1233, trvalý pobyt: Hlavná 12, "
              "811 01 Bratislava, tel. +421 905 123 456, e-mail jan.novak@example.sk")
    found = {s.entity for s in det.detect(sample)}
    expected = {"OSOBA", "DATUM_NARODENIA", "RODNE_CISLO", "ADRESA", "TELEFON", "EMAIL"}
    print(f"Detekcia: {det.engine_name}")
    print("Nájdené:", ", ".join(sorted(found)))
    missing = expected - found
    print("OK" if not missing else f"CHÝBA: {missing}")
    return 0 if not missing else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="anonymizer_sk", description="Anonymizácia osobných údajov v dokumentoch")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--config", help="cesta k config.yaml")
        p.add_argument("--engine", choices=["auto", "presidio", "rules", "rules+ner"])
        p.add_argument("--threshold", type=float, help="minimálne skóre nálezu (predvolene 0.5)")

    a = sub.add_parser("anonymize", help="anonymizovať súbory alebo priečinky")
    a.add_argument("inputs", nargs="+")
    a.add_argument("-o", "--output", required=True, help="výstupný priečinok")
    a.add_argument("--mode", choices=["reversible", "irreversible"], required=True,
                   help="reversible = pseudonymizácia so šifrovaným trezorom, irreversible = trvalá anonymizácia")
    a.add_argument("--vault", help="cesta k trezoru (predvolene VYSTUP/trezor.vault); existujúci sa doplní")
    a.add_argument("--no-numbers", action="store_true", help="trvalý režim: [OSOBA] namiesto [OSOBA_001]")
    common(a)
    a.set_defaults(fn=cmd_anonymize)

    r = sub.add_parser("restore", help="vrátiť originálne údaje z trezoru")
    r.add_argument("inputs", nargs="+")
    r.add_argument("--vault", required=True)
    r.add_argument("-o", "--output", required=True)
    r.add_argument("--config")
    r.set_defaults(fn=cmd_restore)

    s = sub.add_parser("scan", help="náhľad nálezov bez zápisu (zobrazí originálne hodnoty)")
    s.add_argument("inputs", nargs="+")
    common(s)
    s.set_defaults(fn=cmd_scan)

    t = sub.add_parser("selftest", help="overí, že detekcia funguje")
    common(t)
    t.set_defaults(fn=cmd_selftest)

    u = sub.add_parser("ui", help="spustiť grafické rozhranie v prehliadači")
    u.add_argument("--no-browser", action="store_true", help="neotvárať prehliadač (adresa je v logu)")
    u.set_defaults(fn=lambda a: __import__("anonymizer_sk.desktop", fromlist=["main"]).main(
        ["--no-browser"] if a.no_browser else []))

    sub.add_parser("entities", help="zoznam typov údajov").set_defaults(
        fn=lambda _: print("\n".join(f"{k:16} {v}" for k, v in ENTITY_LABELS.items())) or 0)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    return args.fn(args)
