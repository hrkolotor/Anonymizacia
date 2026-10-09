"""Typy entít a ich zobrazované názvy."""

ENTITY_LABELS = {
    "OSOBA": "Meno osoby",
    "RODNE_CISLO": "Rodné číslo",
    "DATUM_NARODENIA": "Dátum narodenia",
    "ADRESA": "Adresa",
    "TELEFON": "Telefón",
    "EMAIL": "E-mail",
    "IBAN": "IBAN",
    "UCET": "Číslo účtu",
    "KARTA": "Platobná karta",
    "ICO": "IČO",
    "DIC": "DIČ",
    "IC_DPH": "IČ DPH",
    "DOKLAD": "Číslo dokladu (OP, pas)",
    "SPZ": "EČV / ŠPZ",
    "IP_ADRESA": "IP adresa",
    "ORGANIZACIA": "Organizácia",
    "LOKALITA": "Lokalita",
    "VLASTNE": "Vlastný výraz (deny-list)",
}

# Organizácie a samotné názvy miest nie sú osobné údaje fyzických osôb,
# preto sú predvolene vypnuté. Zapnúť sa dajú v config.yaml.
DEFAULT_DISABLED = {"ORGANIZACIA", "LOKALITA"}

ALL_ENTITIES = list(ENTITY_LABELS)
