import os
import json
import socket
import asyncio
import re
import io
import base64
import threading
import unicodedata
import httpx
from datetime import datetime
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from thefuzz import process, fuzz

import config

# --- CACHE BAZY W PAMIĘCI RAM ---
_CACHE_BAZY = {
    "sciezka": None,
    "mtime": 0.0,
    "towary": [],
    "indeks": {}
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


# --- ZARZĄDZANIE MAPOWANIAMI (WŁASNE KODY) ---
def wczytaj_baze_mapowan() -> dict:
    if os.path.exists(config.MAPA_FILE):
        try:
            with open(config.MAPA_FILE, "r", encoding="utf-8-sig") as f:
                dane = json.load(f)
            return dane if isinstance(dane, dict) else {}
        except Exception:
            return {}
    return {}


def zapisz_baze_mapowan(mapa: dict) -> None:
    tymczasowy = config.MAPA_FILE + ".tmp"
    try:
        with open(tymczasowy, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=4, ensure_ascii=False)
        os.replace(tymczasowy, config.MAPA_FILE)
    except Exception as e:
        print(f"Błąd zapisu mapowań: {e}")


def wczytaj_plik_mapowan_z_walidacja(sciezka: str) -> dict:
    with open(sciezka, "r", encoding="utf-8-sig") as f:
        dane = json.load(f)
    if not isinstance(dane, dict):
        raise ValueError('Plik JSON musi zawierać słownik w postaci {"NAZWA": "KOD"}.')
    wynik = {}
    for k, v in dane.items():
        nazwa = str(k).strip().upper()
        kod = str(v).strip()
        if nazwa and kod:
            wynik[nazwa] = kod
    if not wynik:
        raise ValueError("Plik nie zawiera żadnych poprawnych reguł.")
    return wynik


def _klucz_reguly(nazwa) -> str:
    return usun_diakrytyki(normalizuj_nazwe(str(nazwa)))


def dodaj_regule(mapa: dict, nazwa: str, kod: str) -> None:
    klucz = _klucz_reguly(nazwa)
    for k in [k for k in mapa if _klucz_reguly(k) == klucz]:
        del mapa[k]
    mapa[nazwa] = kod


def usun_regule(mapa: dict, nazwa: str) -> bool:
    klucz = _klucz_reguly(nazwa)
    do_usuniecia = [k for k in mapa if _klucz_reguly(k) == klucz]
    for k in do_usuniecia:
        del mapa[k]
    return bool(do_usuniecia)


# --- BAZA TOWAROWA PC-MARKET ---
def normalizuj_nazwe(tekst: str) -> str:
    if not tekst:
        return ""
    t = str(tekst).upper().strip()
    t = re.sub(r"[.,/\\_\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def zbuduj_indeks_nazw(baza: list[dict]) -> dict:
    mapa_nazw = {}
    for t in baza:
        kod = t["kod_wew"]
        surowa_nazwa = t["nazwa"]
        czesci = surowa_nazwa.split("/")
        trzon = normalizuj_nazwe(czesci[0])

        if trzon and trzon not in mapa_nazw:
            mapa_nazw[trzon] = kod

        if len(czesci) > 1:
            slowa_trzonu = trzon.split()
            kategoria = slowa_trzonu[0] if slowa_trzonu else ""
            for wariant in czesci[1:]:
                wariant_norm = normalizuj_nazwe(wariant)
                if not wariant_norm:
                    continue
                klucz1 = f"{trzon} {wariant_norm}"
                if klucz1 not in mapa_nazw:
                    mapa_nazw[klucz1] = kod
                if kategoria and kategoria != trzon:
                    klucz2 = f"{kategoria} {wariant_norm}"
                    if klucz2 not in mapa_nazw:
                        mapa_nazw[klucz2] = kod
    return mapa_nazw


def zbuduj_indeks_bez_diakrytykow(indeks: dict) -> dict:
    wynik = {}
    for nazwa, kod in indeks.items():
        wynik.setdefault(usun_diakrytyki(nazwa), kod)
    return wynik


def wczytaj_baze_pcmarket(sciezka: str = None) -> list[dict]:
    if not sciezka:
        konf = config.wczytaj_konfiguracje()
        sciezka = config.pobierz_aktualna_sciezke_bazy(konf)

    if not os.path.exists(sciezka):
        return []

    with _BLOKADA_CACHE:
        try:
            mtime = os.path.getmtime(sciezka)
        except OSError:
            mtime = 0.0
        if _CACHE_BAZY["sciezka"] == sciezka and _CACHE_BAZY["mtime"] == mtime:
            return _CACHE_BAZY["towary"]

        towary_dict = {}
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
                            towary_dict[nazwa] = kod
            except Exception as e:
                print(f"Błąd parsowania bazy PC-Market: {e}")

        towary = [{"nazwa": k, "kod_wew": v} for k, v in towary_dict.items()]
        _CACHE_BAZY["sciezka"] = sciezka
        _CACHE_BAZY["mtime"] = mtime
        _CACHE_BAZY["towary"] = towary
        _CACHE_BAZY["indeks"] = zbuduj_indeks_nazw(towary)
        return towary


def wyodrebnij_kod_wazony(kod_raw: str) -> str:
    """Wycina 4 cyfry indeksu PC-Market z kodu wagowego (np. 29XXXX... lub 28XXXX...)."""
    if not kod_raw:
        return ""
    czysty = re.sub(r"[^\dA-Za-z?]", "", str(kod_raw).strip())
    if len(czysty) >= 6 and czysty[:2] in ("28", "29"):
        kandydat = czysty[2:6]
        if kandydat.isdigit():
            return kandydat
    return ""


def czy_poprawny_ean(kod_raw: str) -> bool:
    """Sprawdza, czy kod jest poprawnym EAN-13 lub EAN-8 (same cyfry, bez znaków zapytania)."""
    if not kod_raw:
        return False
    s = str(kod_raw).strip()
    return s.isdigit() and len(s) in (8, 13)


def dopasuj_towar_z_bazy(nazwa_faktura: str, kod_faktura: str, baza: list[dict], uzywaj_bazy: bool,
                         mapowania: dict = None, indeks: dict = None,
                         indeks_bez_og: dict = None) -> tuple[str, str, str]:
    kod_faktura_clean = str(kod_faktura or "").strip()
    nazwa_faktura_clean = normalizuj_nazwe(nazwa_faktura)
    nazwa_bez_og = usun_diakrytyki(nazwa_faktura_clean)

    # 1. Bezwzględne wycięcie 4 cyfr z kodów wagowych (usuwa znaki ?)
    kod_z_wagi = wyodrebnij_kod_wazony(kod_faktura_clean)
    if kod_z_wagi:
        return kod_z_wagi, kod_faktura_clean, "WAGA_KOD"

    # Jeśli dopasowanie do bazy jest wyłączone w opcjach
    if not uzywaj_bazy:
        kod_do_zwrotu = "" if "?" in kod_faktura_clean else kod_faktura_clean
        return kod_do_zwrotu, kod_faktura_clean, "ORYGINAL"

    # 2. Własne reguły synonimów z pliku JSON (po nazwie z faktury)
    if mapowania is None:
        mapowania = wczytaj_baze_mapowan()
    for nazwa_reguly, kod_reguly in mapowania.items():
        if _klucz_reguly(nazwa_reguly) == nazwa_bez_og:
            return str(kod_reguly), kod_faktura_clean, "REGULA"

    # 3. Dopasowanie po nazwie w bazie PC-Market (dokładne i rozmyte)
    if baza:
        if indeks_bez_og is None:
            mapa_nazw = indeks if indeks is not None else zbuduj_indeks_nazw(baza)
            indeks_bez_og = zbuduj_indeks_bez_diakrytykow(mapa_nazw)

        if nazwa_bez_og in indeks_bez_og:
            return indeks_bez_og[nazwa_bez_og], kod_faktura_clean, "DOKLADNE"

        if nazwa_bez_og and indeks_bez_og:
            wynik = process.extractOne(
                nazwa_bez_og,
                list(indeks_bez_og.keys()),
                scorer=fuzz.token_sort_ratio
            )
            if wynik and wynik[1] >= PROG_ROZMYTY:
                return indeks_bez_og[wynik[0]], kod_faktura_clean, "ROZMYTE"

    # 4. Sprawdzamy, czy kod z faktury to poprawny EAN towaru paczkowanego
    if czy_poprawny_ean(kod_faktura_clean):
        return kod_faktura_clean, kod_faktura_clean, "EAN"

    # 5. Indeks dostawcy / kod CN bez znaków zapytania
    if kod_faktura_clean and "?" not in kod_faktura_clean:
        return kod_faktura_clean, kod_faktura_clean, "INDEKS_DOSTAWCY"

    # Brak dopasowania lub kod z błędami/znakami zapytania
    return "", kod_faktura_clean, "BRAK"


def dopasuj_wszystkie_pozycje_w_tle(dane: dict, uzywa_bazy: bool, sciezka_bazy: str) -> tuple:
    baza = wczytaj_baze_pcmarket(sciezka_bazy) if uzywa_bazy else []
    indeks = None
    if baza:
        with _BLOKADA_CACHE:
            if _CACHE_BAZY.get("sciezka") == sciezka_bazy and _CACHE_BAZY.get("indeks"):
                indeks = _CACHE_BAZY["indeks"]
        if indeks is None:
            indeks = zbuduj_indeks_nazw(baza)
    indeks_bez_og = zbuduj_indeks_bez_diakrytykow(indeks) if indeks else {}
    mapowania = wczytaj_baze_mapowan()

    for poz in dane.get("pozycje", []):
        nazwa = str(poz.get("nazwa", "")).strip().upper()
        kod_faktura = str(poz.get("kod", "")).strip()
        kod_dop, _, pewnosc = dopasuj_towar_z_bazy(
            nazwa, kod_faktura, baza, uzywa_bazy,
            mapowania=mapowania, indeks=indeks, indeks_bez_og=indeks_bez_og
        )
        poz["oryg_nazwa"] = nazwa
        poz["kod_dopasowany"] = kod_dop
        poz["pewnosc"] = pewnosc
        poz["ostrzezenia"] = ostrzezenia_pozycji(poz)

    status_sum, info_sum = weryfikuj_sumy_netto(dane)
    return baza, dane, status_sum, info_sum


# --- SIECIOWE (WoL i TCP) ---
def wyslij_wol(mac_address: str, docelowe_ip: str = "255.255.255.255"):
    czysty_mac = re.sub(r'[^0-9A-Fa-f]', '', mac_address)
    if len(czysty_mac) != 12:
        raise ValueError("Nieprawidłowy format adresu MAC.")

    dane_mac = bytes.fromhex(czysty_mac)
    magic_packet = b"\xff" * 6 + dane_mac * 16

    wyslano = False
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.sendto(magic_packet, ("255.255.255.255", 9))
            wyslano = True
        except Exception:
            pass
        try:
            czesci = docelowe_ip.split(".")
            if len(czesci) == 4:
                subnet_broadcast = f"{czesci[0]}.{czesci[1]}.{czesci[2]}.255"
                s.sendto(magic_packet, (subnet_broadcast, 9))
                s.sendto(magic_packet, (docelowe_ip, 9))
                wyslano = True
        except Exception:
            pass

    if not wyslano:
        raise RuntimeError("Nie udało się wysłać pakietu WoL. Sprawdź połączenie z siecią Wi-Fi.")


async def sprawdz_port_tcp(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


# --- OPERACJE GRAFICZNE (PILLOW) ---
def kompresuj_do_base64(sciezka_pliku: str, rozdzielczosc: int = 1800) -> str:
    with Image.open(sciezka_pliku) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((rozdzielczosc, rozdzielczosc), Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)
        img = img.filter(ImageFilter.SHARPEN)

        bufor = io.BytesIO()
        img.save(bufor, format="JPEG", quality=92)
        return base64.b64encode(bufor.getvalue()).decode("utf-8")


def obroc_plik_graficzny(sciezka_zrodlowa: str, kat: int, prefiks: str = "rot") -> str:
    """Obraca obraz, zapisuje nową wersję i usuwa poprzedni plik."""
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        obrocony = img.rotate(kat, expand=True)
        nowa_sciezka = os.path.join(
            config.KATALOG_DANYCH,
            f"{prefiks}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        )
        obrocony.convert("RGB").save(nowa_sciezka, format="JPEG", quality=95)

    if sciezka_zrodlowa and os.path.exists(sciezka_zrodlowa):
        try:
            os.remove(sciezka_zrodlowa)
        except Exception:
            pass

    return nowa_sciezka


def kadruj_plik_graficzny(sciezka_zrodlowa: str, l_proc: float, t_proc: float,
                          r_proc: float, b_proc: float) -> str:
    nowa_sciezka = os.path.join(
        config.KATALOG_DANYCH,
        f"crop_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    )
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        l = int(w * (l_proc / 100.0))
        t = int(h * (t_proc / 100.0))
        r = int(w * (1.0 - (r_proc / 100.0)))
        b = int(h * (1.0 - (b_proc / 100.0)))
        c = img.crop((l, t, r, b))
        c.save(nowa_sciezka, format="JPEG", quality=95)
    return nowa_sciezka


def filtruj_plik_graficzny(sciezka_zrodlowa: str, typ: str) -> str:
    nowa_sciezka = os.path.join(
        config.KATALOG_DANYCH,
        f"flt_{typ}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    )
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        if typ == "bw":
            szary = ImageOps.grayscale(img)
            szary = ImageEnhance.Contrast(szary).enhance(2.2)
            wynik = szary.point(lambda p: 255 if p > 135 else 0)
        elif typ == "szary":
            wynik = ImageOps.grayscale(img)
            wynik = ImageEnhance.Contrast(wynik).enhance(1.8)
        elif typ == "wyostrz":
            wynik = img.filter(ImageFilter.SHARPEN)
            wynik = ImageEnhance.Contrast(wynik).enhance(1.4)
        else:
            wynik = img
        wynik.convert("RGB").save(nowa_sciezka, format="JPEG", quality=95)
    return nowa_sciezka


# --- OCR I WALIDACJA DANYCH ---
def oczysc_odpowiedz_llm(surowe_dane) -> dict:
    if not isinstance(surowe_dane, dict):
        raise ValueError("Model zwrócił odpowiedź, która nie jest obiektem JSON.")

    def _d(v): return v if isinstance(v, dict) else {}
    def _l(v): return v if isinstance(v, list) else []
    def _t(v, domyslna=""):
        if v is None: return domyslna
        s = str(v).strip()
        return s if s else domyslna

    dane = {}
    dane["nr_dok"] = _t(surowe_dane.get("nr", surowe_dane.get("nr_dok")), "faktura")
    dane["data"] = normalizuj_date(_t(surowe_dane.get("dt", surowe_dane.get("data")), datetime.now().strftime("%d.%m.%Y")))

    wyst = _d(surowe_dane.get("w", surowe_dane.get("wystawca")))
    dane["wystawca"] = {"nazwa": _t(wyst.get("n", wyst.get("nazwa"))), "nip": _t(wyst.get("nip"))}

    odb = _d(surowe_dane.get("o", surowe_dane.get("odbiorca")))
    dane["odbiorca"] = {"nazwa": _t(odb.get("n", odb.get("nazwa"))), "nip": _t(odb.get("nip"))}

    pozycje = []
    for p in _l(surowe_dane.get("p", surowe_dane.get("pozycje"))):
        if not isinstance(p, dict):
            continue
        pozycje.append({
            "nazwa": _t(p.get("n", p.get("nazwa")), "POZYCJA BEZ NAZWY"),
            "kod": _t(p.get("k", p.get("kod"))),
            "vat": _t(p.get("v", p.get("vat"))),
            "jm": _t(p.get("j", p.get("jm")), "kg"),
            "ilosc": _t(p.get("i", p.get("ilosc"))),
            "cena_netto": _t(p.get("c", p.get("cena_netto"))),
            "wartosc_netto": _t(p.get("w", p.get("wartosc_netto"))),
        })

    if not pozycje:
        raise ValueError("Model nie odnalazł żadnych pozycji towarowych na dokumencie.")

    dane["pozycje"] = pozycje
    dane["suma_netto_dokument"] = _t(surowe_dane.get("sn", surowe_dane.get("suma_netto_dokument")))

    stawki = []
    for s in _l(surowe_dane.get("s", surowe_dane.get("stawki"))):
        if isinstance(s, dict):
            stawki.append({
                "vat": _t(s.get("v", s.get("vat"))),
                "suma_netto": _t(s.get("sn", s.get("suma_netto"))),
                "suma_vat": _t(s.get("sv", s.get("suma_vat")))
            })
    dane["stawki"] = stawki
    dane["do_zaplaty"] = _t(surowe_dane.get("dz", surowe_dane.get("do_zaplaty")))
    return dane


def ostrzezenia_pozycji(poz: dict) -> list:
    ost = []
    if parsuj_vat(poz.get("vat")) is None:
        ost.append(f"VAT nierozpoznany ({poz.get('vat') or 'brak'}), do EDI trafi 5%")

    ilosc = parsuj_liczbe(poz.get("ilosc"))
    cena = parsuj_liczbe(poz.get("cena_netto"))
    wartosc = parsuj_liczbe(poz.get("wartosc_netto"))

    if ilosc is None or ilosc <= 0:
        ost.append("brak lub nieczytelna ilość")
    if cena is None:
        ost.append("nieczytelna cena netto")
    if wartosc is None:
        ost.append("nieczytelna wartość netto")

    if ilosc and ilosc > 0 and cena is not None and wartosc is not None:
        oczekiwana = ilosc * cena
        if abs(oczekiwana - wartosc) > max(0.10, 0.005 * abs(wartosc)):
            ost.append(f"ilość × cena = {oczekiwana:.2f}, a wartość netto = {wartosc:.2f}")
    return ost


def weryfikuj_sumy_netto(dane: dict) -> tuple[str, str]:
    pozycje = [p for p in (dane.get("pozycje") or []) if isinstance(p, dict)]
    suma_obliczona = sum(parsuj_kwote(p.get("wartosc_netto")) for p in pozycje)
    suma_odczytana = parsuj_kwote(dane.get("suma_netto_dokument"))

    if suma_odczytana <= 0.0:
        stawki = [s for s in (dane.get("stawki") or []) if isinstance(s, dict)]
        suma_odczytana = sum(parsuj_kwote(s.get("suma_netto")) for s in stawki)

    if suma_odczytana <= 0.0:
        return "BRAK_DANYCH", f"Suma pozycji: {suma_obliczona:.2f} zł (brak sumy z dokumentu do porównania)"

    roznica = abs(suma_obliczona - suma_odczytana)
    if roznica > 0.15:
        return "BLAD", (
            f"⚠️ Niezgodność sumy netto!\n"
            f"Suma pozycji: {suma_obliczona:.2f} | Z dokumentu: {suma_odczytana:.2f}"
        )

    return "OK", f"Zgodność sumy netto: {suma_obliczona:.2f} zł"


def generuj_tekst_edi(dane: dict) -> str:
    pozycje = [p for p in (dane.get("pozycje") or []) if isinstance(p, dict)]
    wyst = dane.get("wystawca") or {}

    surowy_nip = str(wyst.get("nip") or "")
    nip_czysty = re.sub(r"[^\d]", "", surowy_nip)
    nip_wyst = nip_czysty[-10:] if len(nip_czysty) >= 10 else nip_czysty

    linie = [
        "TypPolskichLiter:LA",
        "TypDok:PZ",
        f"NrDok:{dane.get('nr_dok') or ''}",
        f"Data:{dane.get('data') or datetime.now().strftime('%d.%m.%Y')}",
        "Magazyn:MAGAZYN",
        f"NIPWystawcy:{nip_wyst}",
        f"IloscLinii:{len(pozycje)}"
    ]

    for poz in pozycje:
        nazwa = str(poz.get("oryg_nazwa") or poz.get("nazwa") or "").strip().upper()
        
        # Pobieramy kod i bezwzględnie czyścimy znaki zapytania
        kod_glowny = str(poz.get("kod_dopasowany") or poz.get("kod") or "").strip()
        if "?" in kod_glowny:
            kod_wazony = wyodrebnij_kod_wazony(kod_glowny)
            kod_glowny = kod_wazony if kod_wazony else ""

        vat_val = parsuj_vat(poz.get("vat"))
        vat = str(vat_val if vat_val is not None else 5)
        jm = str(poz.get("jm") or "kg").lower().strip()
        ilosc = formatuj_liczbe(parsuj_kwote(poz.get("ilosc")), 3, 3)
        cena = "n" + formatuj_liczbe(parsuj_kwote(poz.get("cena_netto")), 2, 4)
        wartosc = "n" + formatuj_liczbe(parsuj_kwote(poz.get("wartosc_netto")), 2, 4)

        linia = (
            f"Linia:Nazwa{{{nazwa}}}Kod{{{kod_glowny}}}Vat{{{vat}}}Jm{{{jm}}}"
            f"Ilosc{{{ilosc}}}Cena{{{cena}}}Wartosc{{{wartosc}}}"
        )
        linie.append(linia)

    return "\n".join(linie) + "\n"


def wyczysc_pliki_robocze() -> int:
    """Usuwa wszystkie tymczasowe zdjęcia i pliki robocze z katalogu."""
    import glob
    usuniete = 0
    wzorce = [
        "img_*.jpg", "foto_*.jpg", "crop_*.jpg", 
        "flt_*.jpg", "rot_*.jpg", "rot_dok_*.jpg", 
        "rot_skan_*.jpg", "img_dok_*.jpg", "img_skan_*.jpg",
        "edi_*.txt", "*.edi", "dok_*.txt"
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
