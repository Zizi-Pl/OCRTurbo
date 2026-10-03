import os
import json
import asyncio
import re
import io
import base64
import threading
import unicodedata
from collections import Counter
from datetime import datetime
import httpx
from PIL import Image, ImageEnhance, ImageOps
from thefuzz import process, fuzz

import config


def normalizuj_nip(nip: str) -> str:
    """Usuwa wszystko co nie jest cyfrą (PL, spacje, myślniki, kropki)."""
    if not nip:
        return ""
    return re.sub(r"\D", "", str(nip))


def sprawdz_poprawnosc_nip(nip: str) -> bool:
    """Sprawdza sumę kontrolną polskiego NIP (odrzuca halucynacje AI)."""
    nip_czysty = normalizuj_nip(nip)
    if len(nip_czysty) != 10:
        return False

    wagi = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    suma = sum(int(nip_czysty[i]) * wagi[i] for i in range(9))
    suma_kontrolna = suma % 11

    if suma_kontrolna == 10:
        return False

    return suma_kontrolna == int(nip_czysty[9])


# --- ŚCIEŻKI DO PLIKÓW STRUKTURY ---
KARTOTEKA_FILE = os.path.join(config.KATALOG_DANYCH, "kartoteka_towarowa.json")
ALIASY_FILE = os.path.join(config.KATALOG_DANYCH, "aliasy_ocr.json")

# --- CACHE BAZY W PAMIĘCI RAM ---
_CACHE_BAZY = {
    "sciezka": None,
    "mtime": 0.0,
    "towary": [],
    "indeks": {},
}
_BLOKADA_CACHE = threading.Lock()
PROG_ROZMYTY = 75

_TABELA_L = str.maketrans({"ł": "l", "Ł": "L"})


def usun_diakrytyki(tekst: str) -> str:
    """Usuwa polskie znaki diakrytyczne i normalizuje tekst."""
    if not tekst:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(tekst).translate(_TABELA_L))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def parsuj_liczbe(wartosc):
    """Bezpiecznie wyciąga liczbę zmiennoprzecinkową z tekstu."""
    if wartosc is None or isinstance(wartosc, bool):
        return None
    if isinstance(wartosc, (int, float)):
        return float(wartosc)
    s = re.sub(r"[^\d,.\-]", "", str(wartosc).replace("\xa0", ""))
    if not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    if s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parsuj_kwote(wartosc) -> float:
    liczba = parsuj_liczbe(wartosc)
    return liczba if liczba is not None else 0.0


def parsuj_vat(wartosc):
    liczba = parsuj_liczbe(wartosc)
    return None if liczba is None else int(round(liczba))


def normalizuj_date(tekst: str) -> str:
    """Konwertuje różne formaty daty do formatu DD.MM.RRRR."""
    s = str(tekst or "").strip()
    m = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return f"{int(m.group(3)):02d}.{int(m.group(2)):02d}.{m.group(1)}"
    m = re.fullmatch(r"(\d{1,2})[-./](\d{1,2})[-./](\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    return s


def formatuj_liczbe(wartosc: float, min_miejsc: int, max_miejsc: int) -> str:
    s = f"{wartosc:.{max_miejsc}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    miejsca = len(s.split(".")[1]) if "." in s else 0
    if miejsca < min_miejsc:
        s = f"{wartosc:.{min_miejsc}f}"
    return s


def przelicz_brutto_na_netto(cena_brutto: float, vat_proc: int) -> float:
    """Wylicza cenę netto ze stawki brutto i procentu VAT."""
    if cena_brutto is None or cena_brutto <= 0:
        return 0.0
    mnoznik = 1.0 + (float(vat_proc) / 100.0)
    return round(cena_brutto / mnoznik, 4)


# --- OBSŁUGA KODÓW KRESKOWYCH, WAGOWYCH I KLASYFIKACJI STATYSTYCZNEJ ---
def sprawdz_poprawnosc_ean(kod_raw: str) -> bool:
    """Weryfikuje sumę kontrolną EAN-8 oraz EAN-13 (algorytm Modulo 10).

    Odrzuca m.in. 8-cyfrowe numery partii, które nie spełniają algorytmu.
    """
    if not kod_raw:
        return False
    s = re.sub(r"\D", "", str(kod_raw).strip())
    if len(s) not in (8, 13):
        return False

    cyfry = [int(c) for c in s]
    cyfra_kontrolna = cyfry[-1]
    dane = cyfry[:-1]

    if len(s) == 8:
        # Wagi EAN-8 od lewej: 3, 1, 3, 1, 3, 1, 3
        wagi = [3, 1, 3, 1, 3, 1, 3]
    else:
        # Wagi EAN-13 od lewej: 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3
        wagi = [1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3]

    suma = sum(d * w for d, w in zip(dane, wagi))
    obliczona_kontrolna = (10 - (suma % 10)) % 10
    return obliczona_kontrolna == cyfra_kontrolna


def czy_to_pkwiu_lub_cn(kod_raw: str) -> bool:
    """Wykrywa, czy odczytany ciąg jest symbolem PKWiU lub CN zamiast kodu artykułu."""
    if not kod_raw:
        return False
    s = str(kod_raw).strip()

    if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}(\.\d+)?", s):
        return True

    czyste_cyfry = re.sub(r"[^\d]", "", s)
    if len(czyste_cyfry) in (7, 8):
        if czyste_cyfry.startswith((
            "1011",
            "1012",
            "1013",
            "1020",
            "1030",
            "1040",
            "1050",
            "1071",
            "1089",
            "1092",
        )):
            return True
        if czyste_cyfry.startswith(("0201", "0202", "0203", "1601", "1602")):
            return True

    return False


def normalizuj_kod_porownawczy(kod_raw: str) -> str:
    """Zwraca zunifikowany kod do porównań (usuwa maski ?, obcina spacje)."""
    if not kod_raw:
        return ""
    s = str(kod_raw).strip()
    if "?" in s:
        s = s.split("?")[0].strip()
    return s


def wyodrebnij_kod_wazony(kod_raw: str) -> str:
    """Wycina prefiks z kodu wagowego (np. 29xxxx lub 28xxxx z maską lub minimum 6 cyfr)."""
    if not kod_raw:
        return ""
    s = str(kod_raw).strip()
    if "?" in s and (s.startswith("28") or s.startswith("29")):
        return s.split("?")[0].strip()
    czysty = re.sub(r"[^\dA-Za-z]", "", s)
    if len(czysty) >= 6 and czysty[:2] in ("28", "29"):
        return czysty[:6]
    return ""


# --- ZARZĄDZANIE RELACJAMI / ALIASAMI OCR (WŁASNE POWIĄZANIA) ---
def wczytaj_baze_mapowan() -> dict:
    sciezka = ALIASY_FILE if os.path.exists(ALIASY_FILE) else config.MAPA_FILE
    if os.path.exists(sciezka):
        try:
            with open(sciezka, "r", encoding="utf-8-sig") as f:
                dane = json.load(f)
            if not isinstance(dane, dict):
                return {}
            wynik = {}
            for k, v in dane.items():
                nazwa_faktura = str(k).strip().upper()
                if isinstance(v, dict):
                    wynik[nazwa_faktura] = {
                        "kod": str(v.get("kod", "")).strip(),
                        "nazwa_baza": str(v.get("nazwa_baza", "")).strip(),
                        "kod_dostawcy": str(v.get("kod_dostawcy", "")).strip(),
                    }
                else:
                    wynik[nazwa_faktura] = {
                        "kod": str(v).strip(),
                        "nazwa_baza": "",
                        "kod_dostawcy": "",
                    }
            return wynik
        except Exception:
            return {}
    return {}


def zapisz_baze_mapowan(mapa: dict) -> None:
    tymczasowy = ALIASY_FILE + ".tmp"
    try:
        with open(tymczasowy, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=4, ensure_ascii=False)
        os.replace(tymczasowy, ALIASY_FILE)
        with open(config.MAPA_FILE, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Błąd zapisu mapowań: {e}")


def dodaj_regule(
    mapa: dict,
    nazwa: str,
    kod: str,
    nazwa_baza: str = "",
    kod_dostawcy: str = "",
) -> None:
    klucz = _klucz_reguly(nazwa)
    do_usuniecia = [k for k in mapa if _klucz_reguly(k) == klucz]
    for k in do_usuniecia:
        del mapa[k]
    mapa[nazwa.strip().upper()] = {
        "kod": str(kod).strip(),
        "nazwa_baza": str(nazwa_baza).strip(),
        "kod_dostawcy": str(kod_dostawcy).strip(),
    }


def usun_regule(mapa: dict, nazwa: str) -> bool:
    klucz = _klucz_reguly(nazwa)
    do_usuniecia = [k for k in mapa if _klucz_reguly(k) == klucz]
    for k in do_usuniecia:
        del mapa[k]
    return bool(do_usuniecia)


def wczytaj_plik_mapowan_z_walidacja(sciezka: str) -> dict:
    with open(sciezka, "r", encoding="utf-8-sig") as f:
        dane = json.load(f)
    if not isinstance(dane, dict):
        raise ValueError("Plik JSON musi zawierać słownik powiązań.")
    wynik = {}
    for k, v in dane.items():
        wz = str(k).strip().upper()
        if isinstance(v, dict):
            kd = str(v.get("kod", "")).strip()
            nb = str(v.get("nazwa_baza", "")).strip()
            cn = str(v.get("kod_dostawcy", "")).strip()
        else:
            kd = str(v).strip()
            nb, cn = "", ""
        if wz and kd:
            wynik[wz] = {"kod": kd, "nazwa_baza": nb, "kod_dostawcy": cn}
    if not wynik:
        raise ValueError("Plik nie zawiera żadnych poprawnych reguł.")
    return wynik


def _klucz_reguly(nazwa) -> str:
    return usun_diakrytyki(normalizuj_nazwe(str(nazwa)))


# --- KARTOTEKA TOWAROWA I PARSER EXCELA / TXT Z PC-MARKET ---
def normalizuj_nazwe(tekst: str) -> str:
    if not tekst:
        return ""
    t = str(tekst).upper().strip()
    t = re.sub(r"[.,/\\_\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def importuj_baze_z_excela(sciezka_xlsx: str) -> tuple[list[dict], int, int]:
    import openpyxl

    wb = openpyxl.load_workbook(sciezka_xlsx, data_only=True, read_only=True)
    sheet_name = "Arkusz 2" if "Arkusz 2" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet_name]

    header = []
    towary_z_paczki = []

    for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
        if row_idx == 0:
            continue
        if not header and any(c and "Nazwa" in str(c) for c in row):
            header = [str(c).strip() if c is not None else "" for c in row]
            continue
        if not header:
            continue

        row_dict = dict(zip(header, row))
        nazwa = str(row_dict.get("Nazwa") or "").strip().upper()
        kod = str(row_dict.get("Kod") or "").strip()
        if not nazwa or not kod or nazwa == "NAZWA":
            continue

        jm = str(row_dict.get("Jm") or "kg").strip().lower()
        vat = str(row_dict.get("VAT") or "5").strip().replace("%", "")
        cena_ew = parsuj_kwote(row_dict.get("Cena ew."))
        asortyment = str(row_dict.get("Asortyment") or "").strip()

        kody_kreskowe = []
        kod_wew = kod
        kod_czysty = normalizuj_kod_porownawczy(kod)

        if "?" in kod or kod.startswith("29") or kod.startswith("28"):
            kody_kreskowe.append(kod)
            kod_wew = kod_czysty[2:] if len(kod_czysty) >= 6 else kod_czysty
        elif len(kod) == 13 and kod.isdigit():
            kody_kreskowe.append(kod)

        towary_z_paczki.append({
            "nazwa": nazwa,
            "kod": kod,
            "kod_wew": kod_wew,
            "kody_kreskowe": kody_kreskowe,
            "jm": jm,
            "vat": vat,
            "cena_ew": cena_ew,
            "asortyment": asortyment,
        })

    wb.close()

    kartoteka_mapa = {}
    if os.path.exists(KARTOTEKA_FILE):
        try:
            with open(KARTOTEKA_FILE, "r", encoding="utf-8") as f:
                istniejace = json.load(f)
                if isinstance(istniejace, list):
                    for t in istniejace:
                        k_norm = normalizuj_kod_porownawczy(t.get("kod", ""))
                        if k_norm:
                            kartoteka_mapa[k_norm] = t
        except Exception:
            kartoteka_mapa = {}

    dopisane = 0
    zaktualizowane = 0

    for t_nowy in towary_z_paczki:
        k_norm = normalizuj_kod_porownawczy(t_nowy.get("kod", ""))
        if not k_norm:
            continue

        if k_norm in kartoteka_mapa:
            kartoteka_mapa[k_norm].update(t_nowy)
            zaktualizowane += 1
        else:
            kartoteka_mapa[k_norm] = t_nowy
            dopisane += 1

    pelna_kartoteka = list(kartoteka_mapa.values())

    if pelna_kartoteka:
        tymczasowy = KARTOTEKA_FILE + ".tmp"
        with open(tymczasowy, "w", encoding="utf-8") as f:
            json.dump(pelna_kartoteka, f, indent=2, ensure_ascii=False)
        os.replace(tymczasowy, KARTOTEKA_FILE)

        with _BLOKADA_CACHE:
            _CACHE_BAZY["sciezka"] = KARTOTEKA_FILE
            try:
                _CACHE_BAZY["mtime"] = os.path.getmtime(KARTOTEKA_FILE)
            except OSError:
                _CACHE_BAZY["mtime"] = 0.0
            _CACHE_BAZY["towary"] = pelna_kartoteka
            _CACHE_BAZY["indeks"] = zbuduj_indeks_nazw(pelna_kartoteka)

    return pelna_kartoteka, dopisane, zaktualizowane


def zbuduj_indeks_nazw(baza: list[dict]) -> dict:
    mapa_nazw = {}
    for t in baza:
        surowa_nazwa = t.get("nazwa", "")
        czesci = surowa_nazwa.split("/")
        trzon = normalizuj_nazwe(czesci[0])

        if trzon and trzon not in mapa_nazw:
            mapa_nazw[trzon] = t

        if len(czesci) > 1:
            slowa_trzonu = trzon.split()
            kategoria = slowa_trzonu[0] if slowa_trzonu else ""
            for wariant in czesci[1:]:
                wariant_norm = normalizuj_nazwe(wariant)
                if not wariant_norm:
                    continue
                klucz1 = f"{trzon} {wariant_norm}"
                if klucz1 not in mapa_nazw:
                    mapa_nazw[klucz1] = t
                if kategoria and kategoria != trzon:
                    klucz2 = f"{kategoria} {wariant_norm}"
                    if klucz2 not in mapa_nazw:
                        mapa_nazw[klucz2] = t
    return mapa_nazw


def zbuduj_indeks_bez_diakrytykow(indeks: dict) -> dict:
    wynik = {}
    for nazwa, t_obj in indeks.items():
        wynik.setdefault(usun_diakrytyki(nazwa), t_obj)
    return wynik


def wczytaj_baze_pcmarket(sciezka: str = None) -> list[dict]:
    if not sciezka:
        konf = config.wczytaj_konfiguracje()
        sciezka = config.pobierz_aktualna_sciezke_bazy(konf)

    if (not sciezka or not os.path.exists(sciezka)) and os.path.exists(
        KARTOTEKA_FILE
    ):
        sciezka = KARTOTEKA_FILE

    if not sciezka or not os.path.exists(sciezka):
        return []

    if sciezka.lower().endswith(".xlsx"):
        towary, _, _ = importuj_baze_z_excela(sciezka)
        return towary

    if sciezka.lower().endswith(".json"):
        with _BLOKADA_CACHE:
            try:
                mtime = os.path.getmtime(sciezka)
                if (
                    _CACHE_BAZY["sciezka"] == sciezka
                    and _CACHE_BAZY["mtime"] == mtime
                ):
                    return _CACHE_BAZY["towary"]
                with open(sciezka, "r", encoding="utf-8-sig") as f:
                    towary = json.load(f)
                _CACHE_BAZY["sciezka"] = sciezka
                _CACHE_BAZY["mtime"] = mtime
                _CACHE_BAZY["towary"] = towary
                _CACHE_BAZY["indeks"] = zbuduj_indeks_nazw(towary)
                return towary
            except Exception as e:
                print(f"Błąd odczytu kartoteki JSON: {e}")
                return []

    with _BLOKADA_CACHE:
        try:
            mtime = os.path.getmtime(sciezka)
        except OSError:
            mtime = 0.0
        if _CACHE_BAZY["sciezka"] == sciezka and _CACHE_BAZY["mtime"] == mtime:
            return _CACHE_BAZY["towary"]

        towary = []
        kodowania = ["utf-8-sig", "windows-1250", "cp852"]
        linie = None

        for enc in kodowania:
            try:
                with open(sciezka, "r", encoding=enc) as f:
                    linie = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        if linie:
            try:
                for linia in linie:
                    kolumny = linia.strip().split("\t")
                    if len(kolumny) >= 3:
                        nazwa = kolumny[0].strip().upper()
                        kod = kolumny[2].strip().lstrip("'")
                        if nazwa and kod and nazwa != "NAZWA":
                            kody_kreskowe = (
                                [kod] if len(kod) >= 8 or "?" in kod else []
                            )
                            towary.append({
                                "nazwa": nazwa,
                                "kod": kod,
                                "kod_wew": (
                                    kod.split("?")[0].replace("29", "")
                                    if "?" in kod
                                    else kod
                                ),
                                "kody_kreskowe": kody_kreskowe,
                                "jm": "kg",
                                "vat": "5",
                                "cena_ew": 0.0,
                            })
            except Exception as e:
                print(f"Błąd parsowania bazy PC-Market: {e}")

        _CACHE_BAZY["sciezka"] = sciezka
        _CACHE_BAZY["mtime"] = mtime
        _CACHE_BAZY["towary"] = towary
        _CACHE_BAZY["indeks"] = zbuduj_indeks_nazw(towary)
        return towary


# --- ALGORYTM DOPASOWANIA TOWARU (FILOZOFIA PC-MARKET: NAZWA ZAWSZE PRIORYTETEM) ---
def dopasuj_towar_z_bazy(
    nazwa_faktura: str,
    kod_faktura: str,
    baza: list[dict],
    uzywaj_bazy: bool,
    mapowania: dict = None,
    indeks: dict = None,
    indeks_bez_og: dict = None,
) -> tuple[str, str, str, dict]:
    """Zwraca: (kod_dopasowany, kod_faktura_clean, pewnosc, obiekt_towaru_lub_none)"""
    kod_faktura_clean = str(kod_faktura or "").strip()

    # 0. Oczyszczenie z kodów CN, PKWiU oraz fałszywych numerów EAN (np. partii produkcyjnej)
    if czy_to_pkwiu_lub_cn(kod_faktura_clean):
        kod_faktura_clean = ""
    elif kod_faktura_clean.isdigit() and len(kod_faktura_clean) in (8, 13):
        if not sprawdz_poprawnosc_ean(kod_faktura_clean):
            kod_faktura_clean = ""

    nazwa_faktura_clean = normalizuj_nazwe(nazwa_faktura)
    nazwa_bez_og = usun_diakrytyki(nazwa_faktura_clean)

    if not uzywaj_bazy:
        kod_do_zwrotu = "" if "?" in kod_faktura_clean else kod_faktura_clean
        return kod_do_zwrotu, kod_faktura_clean, "ORYGINAL", None

    if mapowania is None:
        mapowania = wczytaj_baze_mapowan()

    # PRIORYTET 1: Reguły własne OCR / aliasy (aliasy_ocr.json)
    if kod_faktura_clean:
        for reg_nazwa, reg_dane in mapowania.items():
            if (
                isinstance(reg_dane, dict)
                and reg_dane.get("kod_dostawcy") == kod_faktura_clean
            ):
                k_wsk = str(reg_dane.get("kod"))
                t_znaleziony = (
                    next((x for x in baza if str(x.get("kod")) == k_wsk), None)
                    if baza
                    else None
                )
                return (
                    k_wsk,
                    kod_faktura_clean,
                    "REGULA_KOD_DOSTAWCY",
                    t_znaleziony,
                )

    for reg_nazwa, reg_dane in mapowania.items():
        if _klucz_reguly(reg_nazwa) == nazwa_bez_og:
            k_wsk = str(
                reg_dane.get("kod") if isinstance(reg_dane, dict) else reg_dane
            )
            t_znaleziony = (
                next((x for x in baza if str(x.get("kod")) == k_wsk), None)
                if baza
                else None
            )
            return k_wsk, kod_faktura_clean, "REGULA", t_znaleziony

    # PRIORYTET 2: Dopasowanie po nazwie w bazie PC-Market
    if baza:
        if indeks_bez_og is None:
            mapa_nazw = (
                indeks if indeks is not None else zbuduj_indeks_nazw(baza)
            )
            indeks_bez_og = zbuduj_indeks_bez_diakrytykow(mapa_nazw)

        # 2a. Dokładna nazwa
        if nazwa_bez_og in indeks_bez_og:
            t = indeks_bez_og[nazwa_bez_og]
            return (
                str(t.get("kod") or t.get("kod_wew")),
                kod_faktura_clean,
                "DOKLADNE",
                t,
            )

        # 2b. Nazwa bez wariantu producenta /WITKOWSKI/
        nazwa_bez_producenta = re.sub(r"/.*?/", "", nazwa_faktura_clean).strip()
        nazwa_czysta_og = usun_diakrytyki(normalizuj_nazwe(nazwa_bez_producenta))
        if nazwa_czysta_og in indeks_bez_og:
            t = indeks_bez_og[nazwa_czysta_og]
            return (
                str(t.get("kod") or t.get("kod_wew")),
                kod_faktura_clean,
                "DOKLADNE_BEZ_PROD",
                t,
            )

        # 2c. Dopasowanie rozmyte
        if nazwa_bez_og and indeks_bez_og:
            szukana_fraza = (
                nazwa_czysta_og
                if len(nazwa_czysta_og) >= 4
                else nazwa_bez_og
            )
            wynik = process.extractOne(
                szukana_fraza,
                list(indeks_bez_og.keys()),
                scorer=fuzz.token_sort_ratio,
            )
            if wynik and wynik[1] >= PROG_ROZMYTY:
                t = indeks_bez_og[wynik[0]]
                return (
                    str(t.get("kod") or t.get("kod_wew")),
                    kod_faktura_clean,
                    "ROZMYTE",
                    t,
                )

    # PRIORYTET 3: Prawdziwy, zwalidowany kod EAN-8 lub EAN-13
    if sprawdz_poprawnosc_ean(kod_faktura_clean):
        t_znaleziony = (
            next(
                (
                    x
                    for x in baza
                    if kod_faktura_clean in x.get("kody_kreskowe", [])
                ),
                None,
            )
            if baza
            else None
        )
        return kod_faktura_clean, kod_faktura_clean, "EAN", t_znaleziony

    # PRIORYTET 4: Kod wagowy (28xxxx / 29xxxx) – TYLKO jeśli istnieje w bazie PC-Market
    kod_z_wagi = wyodrebnij_kod_wazony(kod_faktura_clean)
    if kod_z_wagi and baza:
        for t in baza:
            if str(t.get("kod", "")).startswith(kod_z_wagi):
                return str(t.get("kod")), kod_faktura_clean, "WAGA_KOD", t

    # PRIORYTET 5: Indeks artykułu dostawcy (jeśli nie jest kodem wagowym z ?)
    if (
        kod_faktura_clean
        and "?" not in kod_faktura_clean
        and not kod_faktura_clean.startswith(("28", "29"))
    ):
        return (
            kod_faktura_clean,
            kod_faktura_clean,
            "INDEKS_DOSTAWCY",
            None,
        )

    return "", kod_faktura_clean, "BRAK", None


def dopasuj_wszystkie_pozycje_w_tle(
    dane: dict, uzywa_bazy: bool, sciezka_bazy: str
) -> tuple:
    baza = wczytaj_baze_pcmarket(sciezka_bazy) if uzywa_bazy else []
    indeks = None
    if baza:
        with _BLOKADA_CACHE:
            if (
                _CACHE_BAZY.get("sciezka") == sciezka_bazy
                and _CACHE_BAZY.get("indeks")
            ):
                indeks = _CACHE_BAZY["indeks"]
        if indeks is None:
            indeks = zbuduj_indeks_nazw(baza)
    indeks_bez_og = zbuduj_indeks_bez_diakrytykow(indeks) if indeks else {}
    mapowania = wczytaj_baze_mapowan()

    # FILTR POWTARZAJĄCYCH SIĘ KODÓW (np. numer partii zaciągnięty w każdym wierszu faktury)
    wszystkie_kody_raw = [
        str(p.get("kod", "")).strip()
        for p in dane.get("pozycje", [])
        if str(p.get("kod", "")).strip()
    ]
    liczniki_kodow = Counter(wszystkie_kody_raw)
    podejrzane_partie = {
        kod
        for kod, ile in liczniki_kodow.items()
        if ile >= 3 and not kod.startswith(("28", "29"))
    }

    for poz in dane.get("pozycje", []):
        nazwa = str(poz.get("nazwa", "")).strip().upper()
        kod_faktura = str(poz.get("kod", "")).strip()

        # Odrzucamy powtarzający się numer partii, CN lub PKWiU
        if kod_faktura in podejrzane_partie or czy_to_pkwiu_lub_cn(kod_faktura):
            kod_faktura = ""
            poz["kod"] = ""

        kod_dop, _, pewnosc, t_baza = dopasuj_towar_z_bazy(
            nazwa,
            kod_faktura,
            baza,
            uzywa_bazy,
            mapowania=mapowania,
            indeks=indeks,
            indeks_bez_og=indeks_bez_og,
        )
        poz["oryg_nazwa"] = nazwa
        poz["kod_dopasowany"] = kod_dop
        poz["pewnosc"] = pewnosc

        # KASKADA USTALANIA CENY NETTO
        ilosc_num = parsuj_kwote(poz.get("ilosc"))
        if ilosc_num <= 0.0:
            ilosc_num = 1.0
            poz["ilosc"] = "1.0"
            poz["ilosc_wymuszona"] = True

        cena_num = parsuj_kwote(poz.get("cena_netto"))
        wartosc_num = parsuj_kwote(poz.get("wartosc_netto"))
        typ_ceny = "OCR"

        if cena_num <= 0.0:
            # 1. Z wartości netto na dokumencie
            if wartosc_num > 0.0:
                cena_num = round(wartosc_num / ilosc_num, 4)
                typ_ceny = "OBLICZONA"
            # 2. Z ceny ewidencyjnej w kartotece PC-Market
            elif t_baza and parsuj_kwote(t_baza.get("cena_ew")) > 0.0:
                cena_num = parsuj_kwote(t_baza.get("cena_ew"))
                wartosc_num = round(cena_num * ilosc_num, 2)
                typ_ceny = "BAZA"
            # 3. Twardy bezpiecznik: 1 grosz
            else:
                cena_num = 0.01
                wartosc_num = round(cena_num * ilosc_num, 2)
                typ_ceny = "GROSZ"
        else:
            if wartosc_num <= 0.0:
                wartosc_num = round(cena_num * ilosc_num, 2)

        poz["cena_netto"] = f"{cena_num:.4f}"
        poz["wartosc_netto"] = f"{wartosc_num:.2f}"
        poz["typ_ceny"] = typ_ceny
        poz["ostrzezenia"] = ostrzezenia_pozycji(poz)

    status_sum, info_sum = weryfikuj_sumy_netto(dane)
    return baza, dane, status_sum, info_sum


# --- OPERACJE GRAFICZNE (PILLOW) ---
def konwertuj_do_rgb(img: Image.Image) -> Image.Image:
    """Bezpiecznie przekształca każdy obraz (RGBA, P, L) na RGB z białym tłem."""
    if img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    ):
        tlo = Image.new("RGB", img.size, (255, 255, 255))
        rgba_img = img.convert("RGBA")
        tlo.paste(rgba_img, mask=rgba_img.split()[3])
        return tlo
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def kompresuj_do_base64(sciezka_pliku: str, rozdzielczosc: int = 1800) -> str:
    """Przygotowuje czysty plik do wysłania do modelu AI.

    Wyrównuje orientację, skaluje do zadanej rozdzielczości i zapisuje jako JPEG.
    """
    with Image.open(sciezka_pliku) as img:
        img = ImageOps.exif_transpose(img)
        img = konwertuj_do_rgb(img)

        img.thumbnail((rozdzielczosc, rozdzielczosc), Image.Resampling.LANCZOS)

        bufor = io.BytesIO()
        img.save(bufor, format="JPEG", quality=92)
        return base64.b64encode(bufor.getvalue()).decode("utf-8")


def obroc_plik_graficzny(
    sciezka_zrodlowa: str, kat: int, prefiks: str = "rot"
) -> str:
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        obrocony = img.rotate(kat, expand=True)
        nowa_sciezka = os.path.join(
            config.KATALOG_DANYCH,
            f"{prefiks}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg",
        )
        konwertuj_do_rgb(obrocony).save(nowa_sciezka, format="JPEG", quality=95)

    if sciezka_zrodlowa and os.path.exists(sciezka_zrodlowa):
        try:
            os.remove(sciezka_zrodlowa)
        except Exception:
            pass

    return nowa_sciezka


def kadruj_plik_graficzny(
    sciezka_zrodlowa: str,
    l_proc: float,
    t_proc: float,
    r_proc: float,
    b_proc: float,
) -> str:
    nowa_sciezka = os.path.join(
        config.KATALOG_DANYCH, f"crop_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    )
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        l = int(w * (l_proc / 100.0))
        t = int(h * (t_proc / 100.0))
        r = int(w * (1.0 - (r_proc / 100.0)))
        b = int(h * (1.0 - (b_proc / 100.0)))
        c = img.crop((l, t, r, b))
        konwertuj_do_rgb(c).save(nowa_sciezka, format="JPEG", quality=95)
    return nowa_sciezka


def filtruj_plik_graficzny(sciezka_zrodlowa: str, typ: str) -> str:
    nowa_sciezka = os.path.join(
        config.KATALOG_DANYCH,
        f"flt_{typ}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
    )
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        img = konwertuj_do_rgb(img)
        if typ == "bw":
            szary = ImageOps.grayscale(img)
            szary = ImageEnhance.Contrast(szary).enhance(2.0)
            wynik = szary.point(lambda p: 255 if p > 135 else 0)
        elif typ == "szary":
            szary = ImageOps.grayscale(img)
            wynik = ImageEnhance.Contrast(szary).enhance(1.4)
        elif typ == "wyostrz":
            wynik = ImageEnhance.Sharpness(img).enhance(1.8)
            wynik = ImageEnhance.Contrast(wynik).enhance(1.2)
        else:
            wynik = img
        konwertuj_do_rgb(wynik).save(nowa_sciezka, format="JPEG", quality=95)
    return nowa_sciezka


# --- OCR I WALIDACJA DANYCH ---
def oczysc_odpowiedz_llm(surowe_dane) -> dict:
    if not isinstance(surowe_dane, dict):
        raise ValueError("Model zwrócił odpowiedź, która nie jest obiektem JSON.")

    def _d(v):
        return v if isinstance(v, dict) else {}

    def _l(v):
        return v if isinstance(v, list) else []

    def _t(v, domyslna=""):
        if v is None:
            return domyslna
        s = str(v).strip()
        return s if s else domyslna

    dane = {}
    dane["nr_dok"] = _t(
        surowe_dane.get("nr", surowe_dane.get("nr_dok")), "faktura"
    )
    dane["data"] = normalizuj_date(
        _t(
            surowe_dane.get("dt", surowe_dane.get("data")),
            datetime.now().strftime("%d.%m.%Y"),
        )
    )

    # --- WYSTAWCA ---
    wyst = _d(surowe_dane.get("w", surowe_dane.get("wystawca")))
    nip_wyst_raw = normalizuj_nip(_t(wyst.get("nip")))
    nip_wyst_poprawny = (
        nip_wyst_raw if sprawdz_poprawnosc_nip(nip_wyst_raw) else ""
    )
    dane["wystawca"] = {
        "nazwa": _t(wyst.get("n", wyst.get("nazwa"))),
        "nip": nip_wyst_poprawny,
    }

    # --- ODBIORCA ---
    odb = _d(surowe_dane.get("o", surowe_dane.get("odbiorca")))
    nip_odb_raw = normalizuj_nip(_t(odb.get("nip")))
    nip_odb_poprawny = (
        nip_odb_raw if sprawdz_poprawnosc_nip(nip_odb_raw) else ""
    )
    dane["odbiorca"] = {
        "nazwa": _t(odb.get("n", odb.get("nazwa"))),
        "nip": nip_odb_poprawny,
    }

    pozycje = []
    for p in _l(surowe_dane.get("p", surowe_dane.get("pozycje"))):
        if not isinstance(p, dict):
            continue

        jm_str = _t(p.get("j", p.get("jm")), "kg").lower()
        ilosc_odczytana = parsuj_liczbe(p.get("i", p.get("ilosc")))

        ilosc_wymuszona = False
        if ilosc_odczytana is None or ilosc_odczytana <= 0.0:
            ilosc_wymuszona = True
            ilosc_num = 1.0
            ilosc_str = "1" if jm_str in ("szt", "op", "szt.", "op.") else "1.0"
        else:
            ilosc_num = ilosc_odczytana
            if jm_str in ("szt", "op", "szt.", "op."):
                ilosc_str = str(int(round(ilosc_num)))
            else:
                ilosc_str = str(ilosc_num)

        cena_netto_str = _t(p.get("c", p.get("cena_netto")))
        wartosc_netto_str = _t(p.get("w", p.get("wartosc_netto")))

        if not wartosc_netto_str and cena_netto_str and ilosc_num > 0:
            c_netto_num = parsuj_kwote(cena_netto_str)
            if c_netto_num > 0:
                wartosc_netto_str = f"{c_netto_num * ilosc_num:.2f}"

        pozycje.append({
            "nazwa": _t(p.get("n", p.get("nazwa")), "POZYCJA BEZ NAZWY"),
            "kod": _t(p.get("k", p.get("kod"))),
            "vat": "",
            "jm": jm_str,
            "ilosc": ilosc_str,
            "ilosc_wymuszona": ilosc_wymuszona,
            "cena_netto": cena_netto_str,
            "wartosc_netto": wartosc_netto_str,
            "typ_ceny": "OCR",
        })

    if not pozycje:
        raise ValueError(
            "Model nie odnalazł żadnych pozycji towarowych na dokumencie."
        )

    dane["pozycje"] = pozycje
    dane["suma_netto_dokument"] = _t(
        surowe_dane.get("sn", surowe_dane.get("suma_netto_dokument"))
    )
    dane["stawki"] = []
    dane["do_zaplaty"] = _t(
        surowe_dane.get("dz", surowe_dane.get("do_zaplaty"))
    )
    return dane


def ostrzezenia_pozycji(poz: dict) -> list:
    ost = []
    ilosc = parsuj_liczbe(poz.get("ilosc"))
    cena = parsuj_liczbe(poz.get("cena_netto"))
    wartosc = parsuj_liczbe(poz.get("wartosc_netto"))
    typ_ceny = poz.get("typ_ceny", "OCR")

    if poz.get("ilosc_wymuszona") or ilosc is None or ilosc <= 0:
        ost.append("brak ilości na dokumencie (wstawiono domyślnie 1)")

    if typ_ceny == "BAZA":
        ost.append("brak ceny na dokumencie (pobrano cenę z bazy PC-Market)")
    elif typ_ceny == "GROSZ":
        ost.append("brak ceny na dokumencie i w bazie (wstawiono 0.01 zł)")
    elif typ_ceny == "OBLICZONA":
        ost.append("obliczono cenę jednostkową z wartości netto")
    elif cena is None or cena <= 0:
        ost.append("nieczytelna cena netto")

    if wartosc is None or wartosc <= 0:
        ost.append("nieczytelna wartość netto")

    if ilosc and ilosc > 0 and cena is not None and wartosc is not None:
        oczekiwana = ilosc * cena
        if abs(oczekiwana - wartosc) > max(0.10, 0.005 * abs(wartosc)):
            ost.append(
                f"ilość × cena = {oczekiwana:.2f}, a wartość netto ="
                f" {wartosc:.2f}"
            )
    return ost


def weryfikuj_sumy_netto(dane: dict) -> tuple[str, str]:
    pozycje = [p for p in (dane.get("pozycje") or []) if isinstance(p, dict)]
    suma_obliczona = sum(parsuj_kwote(p.get("wartosc_netto")) for p in pozycje)
    suma_odczytana = parsuj_kwote(dane.get("suma_netto_dokument"))

    if suma_odczytana <= 0.0:
        return (
            "BRAK_DANYCH",
            f"Suma pozycji: {suma_obliczona:.2f} zł (brak sumy z dokumentu do"
            " porównania)",
        )

    roznica = abs(suma_obliczona - suma_odczytana)
    if roznica > 0.15:
        return (
            "BLAD",
            "⚠️ Niezgodność sumy netto!\n"
            f"Suma pozycji: {suma_obliczona:.2f} | Z dokumentu:"
            f" {suma_odczytana:.2f}",
        )

    return "OK", f"Zgodność sumy netto: {suma_obliczona:.2f} zł"


def generuj_tekst_edi(dane: dict) -> str:
    pozycje = [p for p in (dane.get("pozycje") or []) if isinstance(p, dict)]
    wyst = dane.get("wystawca") or {}

    surowy_nip = str(wyst.get("nip") or "")
    nip_czysty = normalizuj_nip(surowy_nip)
    nip_wyst = nip_czysty[-10:] if len(nip_czysty) >= 10 else nip_czysty

    linie = [
        "TypPolskichLiter:LA",
        "TypDok:PZ",
        f"NrDok:{dane.get('nr_dok') or ''}",
        f"Data:{dane.get('data') or datetime.now().strftime('%d.%m.%Y')}",
        "Magazyn:MAGAZYN",
        f"NIPWystawcy:{nip_wyst}",
        f"IloscLinii:{len(pozycje)}",
    ]

    for poz in pozycje:
        nazwa = (
            str(poz.get("oryg_nazwa") or poz.get("nazwa") or "").strip().upper()
        )
        kod_glowny = str(
            poz.get("kod_dopasowany") or poz.get("kod") or ""
        ).strip()

        if kod_glowny.startswith(("28", "29")):
            if "?" in kod_glowny:
                prefiks = kod_glowny.split("?")[0].strip()
                if len(prefiks) == 6:
                    kod_glowny = f"{prefiks}???????"
            elif len(kod_glowny) == 6 and kod_glowny.isdigit():
                kod_glowny = f"{kod_glowny}???????"

        jm = str(poz.get("jm") or "kg").lower().strip()

        # Bezpiecznik ilości
        ilosc_kwota = parsuj_kwote(poz.get("ilosc"))
        if ilosc_kwota <= 0.0:
            ilosc_kwota = 1.0

        # Bezpiecznik ceny
        cena_kwota = parsuj_kwote(poz.get("cena_netto"))
        if cena_kwota <= 0.0:
            cena_kwota = 0.01

        # Bezpiecznik wartości
        wartosc_kwota = parsuj_kwote(poz.get("wartosc_netto"))
        if wartosc_kwota <= 0.0:
            wartosc_kwota = round(ilosc_kwota * cena_kwota, 2)

        ilosc = formatuj_liczbe(ilosc_kwota, 3, 3)
        cena = "n" + formatuj_liczbe(cena_kwota, 2, 4)
        wartosc = "n" + formatuj_liczbe(wartosc_kwota, 2, 4)

        linia = (
            f"Linia:Nazwa{{{nazwa}}}Kod{{{kod_glowny}}}Vat{{}}Jm{{{jm}}}"
            f"Ilosc{{{ilosc}}}Cena{{{cena}}}Wartosc{{{wartosc}}}"
        )
        linie.append(linia)

    return "\n".join(linie) + "\n"


def wyczysc_pliki_robocze() -> int:
    import glob

    usuniete = 0
    wzorce = [
        "img_*.jpg",
        "foto_*.jpg",
        "crop_*.jpg",
        "flt_*.jpg",
        "rot_*.jpg",
        "adj_*.jpg",
        "preview_editor*.jpg",
        "dok_*.docx",
        "dok_*.xlsx",
        "dok_*.txt",
        "edi_*.txt",
        "*.edi",
        "*.tmp",
    ]
    for wzorzec in wzorce:
        sciezka_wzorca = os.path.join(config.KATALOG_DANYCH, wzorzec)
        for sciezka in glob.glob(sciezka_wzorca):
            try:
                os.remove(sciezka)
                usuniete += 1
            except Exception:
                pass
    return usuniete
