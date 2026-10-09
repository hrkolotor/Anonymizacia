"""Kontrolné súčty a validácie slovenských identifikátorov."""

import calendar
import datetime
import ipaddress

from .text_utils import digits


def rodne_cislo(value: str) -> bool:
    """Rodné číslo SR: 9 číslic (narodení do 1953) alebo 10 číslic deliteľných 11.
    Mesiac +50 u žien, od roku 2004 aj +20 / +70."""
    d = digits(value)
    if len(d) not in (9, 10):
        return False
    yy, mm, dd = int(d[0:2]), int(d[2:4]), int(d[4:6])
    if len(d) == 9:
        if yy >= 54:
            return False
        year = 1900 + yy
    else:
        year = 1900 + yy if yy >= 54 else 2000 + yy
        if year > datetime.date.today().year:
            return False
        if int(d) % 11 != 0:
            # výnimka pre čísla pridelené do roku 1985: zvyšok 10 a kontrolná číslica 0
            if not (int(d[:9]) % 11 == 10 and d[9] == "0"):
                return False
    m = mm
    if m > 70 and year >= 2004:
        m -= 70
    elif m > 50:
        m -= 50
    elif m > 20 and year >= 2004:
        m -= 20
    if not 1 <= m <= 12:
        return False
    return 1 <= dd <= calendar.monthrange(year, m)[1]


def ico(value: str) -> bool:
    """IČO: 8 číslic, váhy 8..2, kontrolná číslica (11 - súčet mod 11) mod 10."""
    d = digits(value)
    if len(d) != 8:
        return False
    total = sum(int(d[i]) * w for i, w in enumerate(range(8, 1, -1)))
    return (11 - total % 11) % 10 == int(d[7])


def dic(value: str) -> bool:
    d = digits(value)
    return len(d) == 10 and d[0] in "1234"


def ic_dph(value: str) -> bool:
    d = digits(value)
    return len(d) == 10 and int(d) % 11 == 0


def iban(value: str) -> bool:
    s = "".join(value.split()).upper()
    if len(s) < 15 or len(s) > 34 or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    if s.startswith("SK") and len(s) != 24:
        return False
    rearranged = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


def luhn(value: str) -> bool:
    d = digits(value)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, c in enumerate(reversed(d)):
        n = int(c)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def ipv4(value: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(value.strip())
    except ValueError:
        return False
    return not (ip.is_loopback or ip.is_unspecified)


def has_digit_and_letter(value: str) -> bool:
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)
