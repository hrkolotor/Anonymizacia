"""Slovenské rozpoznávače osobných údajov.

Všetky regulárne výrazy bežia nad textom bez diakritiky (text_utils.fold), ktorý má
rovnakú dĺžku ako originál. Preto sú vzory písané v ASCII a fungujú aj na OCR výstupe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import validators as V
from .text_utils import fold

# ---------------------------------------------------------------- stavebné bloky
UP = r"[A-Z]"
LET = r"[^\W\d_]"
NB = r"(?<![^\W\d_])"          # začiatok slova
NA = r"(?![^\W\d_])"           # koniec slova
SP = r"[ \t ]+"           # medzera bez nového riadku
OS = r"[ \t ]*"
WORD_CAP = rf"{UP}{LET}+(?:-{UP}{LET}+)?"

TITLES_PRE = (r"(?:Ing\.(?:[ ]?arch\.)?|Mgr\.(?:[ ]?art\.)?|Bc\.|JUDr\.|MUDr\.|MDDr\.|MVDr\.|PhDr\.|"
              r"RNDr\.|PaedDr\.|PharmDr\.|ThDr\.|ICDr\.|doc\.|prof\.|Dr\.)")
TITLES_POST = r"(?:PhD\.|CSc\.|DrSc\.|MBA|LL\.M\.|ArtD\.|MPH|DiS\.)"
POST = rf"(?:,?{OS}{TITLES_POST})*"
NAME_VAL = (rf"(?:{TITLES_PRE}{OS})*{WORD_CAP}(?:{SP}(?:{TITLES_PRE}{OS})?{WORD_CAP}){{0,3}}{POST}")

ORG_SUFFIX = re.compile(
    rf",?{OS}(?:s\.{OS}r\.{OS}o\.|spol\.{OS}s{OS}r\.{OS}o\.|a\.{OS}s\.|k\.{OS}s\.|v\.{OS}o\.{OS}s\.|"
    rf"n\.{OS}o\.|o\.{OS}z\.|s\.{OS}p\.|SE{NA}|GmbH|Ltd\.?|Inc\.?)")
ORG_WORDS = re.compile(r"(?i)\b(banka|sporitelna|poistovna|urad|ministerstvo|mesto|obec|republika|"
                       r"spolocnost|druzstvo|nadacia|zdruzenie|agentura|fakulta|univerzita|nemocnica)\b")

MONTHS = r"(?:januara|februara|marca|aprila|maja|juna|jula|augusta|septembra|oktobra|novembra|decembra)"
DATE = rf"(?:\d{{1,2}}\.{OS}\d{{1,2}}\.{OS}(?:19|20)\d{{2}}|\d{{1,2}}\.{OS}{MONTHS}{SP}(?:19|20)\d{{2}})"

FIRST_NAMES_M = """Adam Adrian Alex Alexander Alojz Andrej Anton Augustin Bohumil Bohuslav Boris Branislav
Dalibor Daniel David Denis Dezider Dominik Dusan Eduard Emil Erik Ernest Eugen Filip Frantisek Gabriel Gustav
Herbert Hugo Igor Imrich Ivan Jakub Jan Jaroslav Jonas Jozef Julius Juraj Kamil Karol Kristian Ladislav Leo
Leopold Lubomir Lubos Lukas Marek Marian Mario Martin Matej Matus Michal Mikulas Milan Miloslav Miroslav
Nikolas Norbert Oliver Ondrej Oskar Patrik Pavel Pavol Peter Radoslav Rastislav Rene Richard Robert Roman
Rudolf Samuel Sebastian Simon Slavomir Stanislav Stefan Svatopluk Tadeas Teodor Tibor Tomas Valentin Viktor
Viliam Vincent Vladimir Vladislav Vojtech Zdenko Zoltan""".split()
FIRST_NAMES_F = """Adriana Agata Alena Alexandra Alzbeta Andrea Anezka Anna Barbora Beata Bozena Dana Daniela
Denisa Diana Dominika Dorota Edita Elena Ella Ema Emilia Emma Erika Eva Gabriela Gizela Hana Helena Ingrid Ivana
Iveta Jana Jarmila Jaroslava Jozefina Judita Julia Kamila Katarina Klara Kristina Kvetoslava Laura Lea Lenka
Libusa Lucia Ludmila Magdalena Marcela Margita Maria Marta Martina Michaela Miroslava Monika Natalia Natasa
Nikola Nina Olga Patricia Paulina Petra Radka Renata Romana Ruzena Sabina Sara Silvia Simona Sofia Sona
Stanislava Stefania Svetlana Tamara Tatiana Terezia Vanda Veronika Viera Viktoria Vladimira Zdenka Zlatica
Zofia Zora Zuzana""".split()
_VOWEL_DROP = {"Peter": "Petr", "Pavol": "Pavl", "Pavel": "Pavl", "Karol": "Karl", "Marek": "Mark"}


def _name_forms(n: str) -> str:
    """Regulárny výraz pokrývajúci bežné pády krstného mena."""
    if n.endswith("ia"):
        return rf"{n[:-1]}(?:a|e|u|ou|i)"
    if n.endswith("a"):
        return rf"{n[:-1]}(?:a|y|e|u|ou|i)"
    if n.endswith("o"):
        return rf"{n[:-1]}(?:o|a|ovi|om|u)"
    if n.endswith("e"):
        return rf"{n}(?:a|ovi|om)?"
    if n in _VOWEL_DROP:
        return rf"(?:{n}|{_VOWEL_DROP[n]}(?:a|ovi|om|e|u|i))"
    return rf"{n}(?:a|ovi|om|e|u|i)?"


FIRST_NAME = NB + "(?:" + "|".join(_name_forms(n) for n in FIRST_NAMES_M + FIRST_NAMES_F) + ")" + NA


def _labels(words: list[str]) -> str:
    words = sorted(words, key=len, reverse=True)
    return "|".join(w.replace(" ", r"[ \t]+").replace(".", r"\.") for w in words)


PERSON_LABELS = _labels("""meno a priezvisko|meno, priezvisko|priezvisko a meno|titul, meno a priezvisko|meno|
priezvisko|rodne priezvisko|zastupeny|zastupena|v zastupeni|konatel|konatelka|splnomocnenec|splnomocnitel|
kupujuci|predavajuci|najomca|prenajimatel|zamestnanec|zamestnankyna|dlznik|veritel|pacient|pacientka|ziadatel|
ziadatelka|darca|obdarovany|obdarovana|odosielatel|adresat|vypracoval|vypracovala|schvalil|schvalila|
kontaktna osoba|zodpovedna osoba|ucastnik|klient|klientka|poistenec|poistnik|objednavatel|zhotovitel|
uzivatel|spotrebitel|manzel|manzelka|svedok|vlastnik|majitel|student|studentka|ziak|lekar|lekarka|
osetrujuci lekar""".replace("\n", "").split("|"))

ADDRESS_LABELS = _labels("""adresa trvaleho pobytu|trvaly pobyt|trvale bytom|bytom|bydliskom|bydlisko|
adresa bydliska|korespondencna adresa|dorucovacia adresa|prechodny pobyt|miesto podnikania|sidlo|adresa
""".replace("\n", "").split("|"))

ADDR_STOP = (r"(?=[ \t]*(?:\n|;|$|\)|(?<=[^\W\d_]{4})\.[ \t]+[A-Z]|,[ \t]*(?i:nar|r\.[ \t]?c|rodne|ico|dic|ic[ \t]?dph|tel|mob|e-?mail|"
             r"c\.[ \t]?op|op[ \t]?c|datum|iban|c\.[ \t]?u|cislo|zapisan|zastupen|bankov)))")

ADDRESS = (rf"{NB}(?:(?:ul\.|ulica|nam\.|namestie|trieda|cesta){SP})?(?:{UP}[\w.]*|\d{{1,2}}\.)"
           rf"(?:{SP}[\w.]+){{0,3}}?{SP}\d{{1,5}}(?:/(?:\d{{1,5}}[a-zA-Z]?|[A-Z]))?[a-zA-Z]?,?{SP}\d{{3}}{OS}\d{{2}}{SP}"
           rf"{UP}{LET}+(?:(?:{OS}-{OS}|{SP}(?:nad|pod|pri){SP}|{SP}){UP}{LET}+)?(?:{SP}\d{{1,2}}(?!\d))?")
STREET_ONLY = rf"{NB}(?:ul\.|ulica){SP}{UP}{LET}+(?:{SP}{LET}+)?{SP}\d{{1,5}}(?:/\d{{1,5}})?[a-zA-Z]?"

SIGNOFF = (rf"(?im)^[ \t]*(?:s[ \t]+pozdravom|s[ \t]+uctou|s[ \t]+priatelskym[ \t]+pozdravom|dakujem|vdaka|"
           rf"pekny[ \t]+den|best[ \t]+regards|kind[ \t]+regards|regards)[ \t]*[,.!]?[ \t]*\n(?:[ \t]*\n)?[ \t]*"
           rf"(?P<v>(?-i:(?:{TITLES_PRE}{OS})*{WORD_CAP}(?:{SP}{WORD_CAP}){{1,2}}{POST}))")
GREETING = (rf"(?i:{NB}(?:ahoj|cau|zdravim|dobry[ \t]+den|dobre[ \t]+rano|vazen[yaei]|mil[yaei])){OS},?{OS}"
            rf"(?i:(?:pan|pani|pane|panie|p\.){SP})?(?:{TITLES_PRE}{OS})*"
            rf"(?P<v>{WORD_CAP}(?:{SP}{WORD_CAP})?)(?={OS}[,!\n])")
HONORIFIC = (rf"(?i:{NB}(?:pan|pani|pana|panovi|panom|panej|panu|panie|p\.)){SP}(?:{TITLES_PRE}{OS})*"
             rf"(?P<v>{WORD_CAP}(?:{SP}{WORD_CAP})?){NA}")


# ---------------------------------------------------------------- dátové štruktúry
@dataclass
class Span:
    start: int
    end: int
    entity: str
    score: float
    source: str
    text: str = ""

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def __len__(self) -> int:
        return self.end - self.start


@dataclass
class Rule:
    name: str
    entity: str
    pattern: str
    score: float
    validator: Optional[Callable[[str], bool]] = None
    context: tuple = ()
    require_context: bool = False
    group: str | int = 0
    window: int = 45
    post: Optional[Callable[[str, int, int], Optional[tuple]]] = None
    _re: re.Pattern = field(init=False, repr=False)

    def __post_init__(self):
        self._re = re.compile(self.pattern, re.MULTILINE)

    def find(self, folded: str):
        low = folded.lower()
        for m in self._re.finditer(folded):
            s, e = m.span(self.group)
            if s < 0 or s == e:
                continue
            while e > s and folded[e - 1] in " \t,;:":
                e -= 1
            while s < e and folded[s] in " \t":
                s += 1
            value = folded[s:e]
            if self.validator and not self.validator(value):
                continue
            entity, score = self.entity, self.score
            if self.context:
                window = low[max(0, s - self.window):s] + " " + low[e:e + 15]
                if any(c in window for c in self.context):
                    score = min(1.0, score + 0.3)
                elif self.require_context:
                    continue
            if self.post:
                res = self.post(folded, s, e)
                if res is None:
                    continue
                entity, s, e = res
            yield Span(s, e, entity, round(score, 3), self.name)


def _person_or_org(folded: str, s: int, e: int):
    m = ORG_SUFFIX.match(folded, e)
    if m:
        return "ORGANIZACIA", s, m.end()
    if ORG_WORDS.search(folded[s:e]):
        return "ORGANIZACIA", s, e
    return "OSOBA", s, e


CTX_RC = ("rodne cislo", "rodneho cisla", "r.c", "r. c", "rc:", "rc ", "birth number")
CTX_PHONE = ("tel", "mobil", "kontakt", "t.c", "phone")


def build_rules() -> list[Rule]:
    return [
        # --- identifikátory s kontrolným súčtom
        Rule("rc_slash", "RODNE_CISLO", r"(?<![\d/])\d{6}[ \t]?/[ \t]?\d{3,4}(?![\d/])", 0.6,
             V.rodne_cislo, CTX_RC),
        Rule("rc_plain", "RODNE_CISLO", r"(?<!\d)\d{9,10}(?!\d)", 0.6, V.rodne_cislo, CTX_RC,
             require_context=True),
        Rule("ico", "ICO", r"(?<!\d)\d{2}[ \t]?\d{3}[ \t]?\d{3}(?!\d)", 0.6, V.ico,
             ("ico", "identifikacne cislo organizacie"), require_context=True),
        Rule("dic", "DIC", r"(?<!\d)\d{10}(?!\d)", 0.6, V.dic, ("dic", "danove identifikacne"),
             require_context=True, window=25),
        Rule("ic_dph", "IC_DPH", rf"{NB}SK{OS}\d{{10}}(?!\d)", 0.85, V.ic_dph, ("ic dph", "dph")),
        Rule("iban_sk", "IBAN", rf"{NB}SK\d{{2}}(?:{OS}\d{{4}}){{5}}(?!\d)", 0.95, V.iban),
        Rule("iban", "IBAN", rf"{NB}[A-Z]{{2}}\d{{2}}(?:{OS}[A-Z0-9]{{4}}){{2,7}}(?:{OS}[A-Z0-9]{{1,3}})?(?![A-Z0-9])",
             0.9, V.iban),
        Rule("ucet", "UCET", r"(?<![\d-])(?:\d{1,6}-)?\d{2,10}[ \t]?/[ \t]?\d{4}(?!\d)", 0.55, None,
             ("ucet", "c. u", "c.u", "cislo uctu", "bankove spojenie"), require_context=True),
        Rule("karta", "KARTA", r"(?<!\d)\d{4}(?:[ -]?\d{4}){2}[ -]?\d{1,7}(?!\d)", 0.7, V.luhn,
             ("kart", "card", "visa", "mastercard")),
        # --- kontakty
        Rule("email", "EMAIL", r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}", 0.95),
        Rule("tel_sk_intl", "TELEFON", r"(?<![\w+])(?:\+|00)421[ \t/-]?\d{3}[ \t/-]?\d{3}[ \t/-]?\d{3}(?!\d)",
             0.9),
        Rule("tel_sk_mobil", "TELEFON", r"(?<![\d+])09\d{2}[ \t/-]?\d{3}[ \t/-]?\d{3}(?!\d)", 0.75, None,
             CTX_PHONE),
        Rule("tel_sk_pevna", "TELEFON", r"(?<![\d+])0\d{1,3}[ \t]?/[ \t]?\d{3}[ \t]?\d{2,3}[ \t]?\d{2,3}(?!\d)",
             0.45, None, CTX_PHONE),
        Rule("tel_intl", "TELEFON", r"(?<![\w+])\+(?!421)\d{1,3}[ \t-]?\d{2,4}(?:[ \t-]?\d{2,4}){2,4}(?!\d)",
             0.6, None, CTX_PHONE),
        Rule("ipv4", "IP_ADRESA", r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", 0.6, V.ipv4,
             ("ip", "adresa servera", "host")),
        # --- doklady, vozidlá, dátum narodenia
        Rule("doklad", "DOKLAD", rf"{NB}[A-Z]{{2}}[ \t]?\d{{6}}(?!\d)", 0.5, None,
             ("obciansky preukaz", "obcianskeho preukazu", "c. op", "op c", "cislo op", "op:", "op.",
              "pas", "cislo dokladu", "doklad totoznosti", "preukaz"), require_context=True),
        Rule("spz", "SPZ", rf"{NB}[A-Z]{{2}}[ \t-]?\d{{3}}[ \t-]?[A-Z]{{2}}{NA}", 0.5, None,
             ("ecv", "spz", "evidencne cislo", "evidencneho cisla", "vozidl", "auto")),
        Rule("datum_nar", "DATUM_NARODENIA", DATE, 0.6, None,
             ("nar.", "nar ", "narod", "datum narodenia", "d. n.", "born"), require_context=True, window=30),
        # --- adresy
        Rule("adresa", "ADRESA", ADDRESS, 0.85),
        Rule("ulica", "ADRESA", STREET_ONLY, 0.7),
        Rule("adresa_label", "ADRESA",
             rf"(?i:{NB}(?:{ADDRESS_LABELS})){NA}{OS}:?{OS}\n?{OS}(?P<v>[^\n;]{{4,120}}?){ADDR_STOP}", 0.8,
             V.has_digit_and_letter, group="v"),
        # --- mená
        Rule("osoba_label",
             "OSOBA", rf"(?i:{NB}(?:{PERSON_LABELS})){NA}{OS}(?:\([^)\n]{{0,30}}\))?{OS}[:\-–]{OS}\n?{OS}"
                      rf"(?P<v>{NAME_VAL})", 0.9, group="v", post=_person_or_org),
        Rule("osoba_zastupeny", "OSOBA",
             rf"(?i:{NB}(?:zastupen[ya]|v[ \t]+zastupeni)(?:[ \t]+(?:konatelom|konatelkou|splnomocnencom|"
             rf"riaditelom|riaditelkou|predsedom|predsednickou))?){OS}:?{OS}(?P<v>{NAME_VAL})", 0.85,
             group="v", post=_person_or_org),
        Rule("osoba_titul", "OSOBA",
             rf"{NB}(?:{TITLES_PRE}{OS})+{WORD_CAP}(?:{SP}{WORD_CAP}){{0,2}}{POST}", 0.85),
        Rule("osoba_krstne", "OSOBA",
             rf"{FIRST_NAME}(?:{SP}{FIRST_NAME})?{SP}{WORD_CAP}{NA}{POST}", 0.8),
        Rule("osoba_oslovenie", "OSOBA", HONORIFIC, 0.75, group="v"),
        Rule("osoba_pozdrav", "OSOBA", GREETING, 0.7, group="v"),
        Rule("osoba_podpis", "OSOBA", SIGNOFF, 0.8, group="v"),
        # --- organizácie (predvolene vypnuté)
        Rule("organizacia", "ORGANIZACIA",
             rf"{NB}{UP}[\w&.-]*(?:{SP}[\w&.-]+){{0,4}}?{ORG_SUFFIX.pattern}", 0.7),
    ]


class RuleDetector:
    """Spustí všetky pravidlá a vráti surové (neprekrytie neriešené) nálezy."""

    def __init__(self):
        self.rules = build_rules()

    def raw_spans(self, text: str) -> list[Span]:
        folded = fold(text)
        out: list[Span] = []
        for rule in self.rules:
            out.extend(rule.find(folded))
        return out
