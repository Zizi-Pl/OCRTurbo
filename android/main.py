import flet_camera as fc
import flet as ft
import base64
import json
import os
import shutil
import socket
import asyncio
import re
import io
import glob
import copy
import threading
import unicodedata
import httpx
from datetime import datetime
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from thefuzz import process, fuzz

KATALOG_DANYCH = os.getenv("FLET_APP_STORAGE_DATA", os.getcwd())
os.makedirs(KATALOG_DANYCH, exist_ok=True)

CONFIG_FILE = os.path.join(KATALOG_DANYCH, "ocrlmm_mobile_config.json")
DOMYSLNA_BAZA_FILE = os.path.join(KATALOG_DANYCH, "WĘDLINA.txt")
MAPA_FILE = os.path.join(KATALOG_DANYCH, "mapowania_towarow.json")

DOMYSLNA_KONFIGURACJA = {
    "wol_mac": "2C:F0:5D:E4:8E:85",
    "use_cloud": True,
    "use_db_matching": True,
    "baza_file_path": DOMYSLNA_BAZA_FILE,
    "gemini_api_key": "",
    "gemini_model": "gemini-3.6-flash",
    "local_ip": "192.168.1.154",
    "local_port": "1234",
    "local_model": "qwen3.5-9b",
    "local_models_list": [
        "qwen/qwen3-vl-8b-instruct",
        "qwen3-vl-4b-instruct",
        "qwen3.5-9b"
    ],
    "local_api_key": "",
    "image_resolution": 1800
}

PUSTY_OBRAZ = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

# --- CACHE BAZY W PAMIĘCI RAM ---
_CACHE_BAZY = {
    "sciezka": None,
    "mtime": 0.0,
    "towary": [],
    "indeks": {}
}
_BLOKADA_CACHE = threading.Lock()

# Próg (0-100) podobieństwa nazw, od którego dopasowanie rozmyte jest w ogóle proponowane.
PROG_ROZMYTY = 75

# --- FUNKCJE POMOCNICZE / SANITYZACJA ---
# Litera "ł" nie rozkłada się w NFKD, więc zamieniamy ją osobno.
_TABELA_L = str.maketrans({"ł": "l", "Ł": "L"})

def usun_diakrytyki(tekst: str) -> str:
    if not tekst:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(tekst).translate(_TABELA_L))
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def parsuj_liczbe(wartosc):
    """Zamienia tekst z faktury na liczbę (float). Zwraca None, gdy nie da się odczytać.

    Obsługuje: '1 234,50', '1.234,50', '1,234.50', '12,5 kg', 'n10.00', '5%'.
    Pojedyncza kropka lub przecinek traktowane są jako separator dziesiętny.
    """
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
    """Zwraca stawkę VAT jako int albo None, gdy jej nie da się odczytać (np. 'zw', 'np')."""
    liczba = parsuj_liczbe(wartosc)
    return None if liczba is None else int(round(liczba))

def normalizuj_date(tekst: str) -> str:
    s = str(tekst or "").strip()
    m = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return f"{int(m.group(3)):02d}.{int(m.group(2)):02d}.{m.group(1)}"
    m = re.fullmatch(r"(\d{1,2})[-./](\d{1,2})[-./](\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    return s

def formatuj_liczbe(wartosc: float, min_miejsc: int, max_miejsc: int) -> str:
    """Np. (12.5, 2, 4) -> '12.50'; (12.345, 2, 4) -> '12.345'; (5, 3, 3) -> '5.000'."""
    s = f"{wartosc:.{max_miejsc}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    miejsca = len(s.split(".")[1]) if "." in s else 0
    if miejsca < min_miejsc:
        s = f"{wartosc:.{min_miejsc}f}"
    return s

# --- ZARZĄDZANIE MAPOWANIAMI (WŁASNE KODY) ---
def wczytaj_baze_mapowan() -> dict:
    if os.path.exists(MAPA_FILE):
        try:
            with open(MAPA_FILE, "r", encoding="utf-8-sig") as f:
                dane = json.load(f)
            return dane if isinstance(dane, dict) else {}
        except Exception:
            return {}
    return {}

def zapisz_baze_mapowan(mapa: dict):
    tymczasowy = MAPA_FILE + ".tmp"
    try:
        with open(tymczasowy, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=4, ensure_ascii=False)
        os.replace(tymczasowy, MAPA_FILE)
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
    """Dodaje regułę i usuwa jej wcześniejsze warianty zapisu (inaczej stara wygrałaby z nową)."""
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

# --- KONFIGURACJA I BAZA ---
def wczytaj_konfiguracje() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                dane = json.load(f)
                konf = copy.deepcopy(DOMYSLNA_KONFIGURACJA)
                konf.update(dane)
                return konf
        except Exception:
            return copy.deepcopy(DOMYSLNA_KONFIGURACJA)
    return copy.deepcopy(DOMYSLNA_KONFIGURACJA)

def zapisz_konfiguracje(konf: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(konf, f, indent=2)
    except Exception as e:
        print(f"Błąd zapisu konfiguracji: {e}")

def pobierz_aktualna_sciezke_bazy(konf: dict) -> str:
    sciezka = konf.get("baza_file_path", DOMYSLNA_BAZA_FILE)
    if os.path.exists(sciezka):
        return sciezka

    sciezka_lokalna = os.path.join(os.getcwd(), "WĘDLINA.txt")
    if os.path.exists(sciezka_lokalna):
        return sciezka_lokalna

    return sciezka

def wczytaj_baze_pcmarket(sciezka: str = None) -> list[dict]:
    if not sciezka:
        konf = wczytaj_konfiguracje()
        sciezka = pobierz_aktualna_sciezke_bazy(konf)

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

def dopasuj_towar_z_bazy(nazwa_faktura: str, kod_faktura: str, baza: list[dict], uzywaj_bazy: bool,
                         mapowania: dict = None, indeks: dict = None,
                         indeks_bez_og: dict = None) -> tuple[str, str, str]:
    kod_faktura_clean = str(kod_faktura or "").strip()
    nazwa_faktura_clean = normalizuj_nazwe(nazwa_faktura)
    nazwa_bez_og = usun_diakrytyki(nazwa_faktura_clean)

    if not uzywaj_bazy:
        return kod_faktura_clean, kod_faktura_clean, "ORYGINAL"

    if mapowania is None:
        mapowania = wczytaj_baze_mapowan()
    for nazwa_reguly, kod_reguly in mapowania.items():
        if _klucz_reguly(nazwa_reguly) == nazwa_bez_og:
            return str(kod_reguly), kod_faktura_clean, "REGULA"

    if not baza:
        return "", kod_faktura_clean, "BRAK"

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

    return "", kod_faktura_clean, "BRAK"

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
    dane["nr_dok"] = _t(surowe_dane.get("nr_dok"), "faktura")
    dane["data"] = normalizuj_date(_t(surowe_dane.get("data"), datetime.now().strftime("%d.%m.%Y")))

    wyst = _d(surowe_dane.get("wystawca"))
    dane["wystawca"] = {"nazwa": _t(wyst.get("nazwa")), "nip": _t(wyst.get("nip"))}

    odb = _d(surowe_dane.get("odbiorca"))
    dane["odbiorca"] = {"nazwa": _t(odb.get("nazwa")), "nip": _t(odb.get("nip"))}

    pozycje = []
    for p in _l(surowe_dane.get("pozycje")):
        if not isinstance(p, dict):
            continue
        pozycje.append({
            "nazwa": _t(p.get("nazwa"), "POZYCJA BEZ NAZWY"),
            "kod": _t(p.get("kod")),
            "vat": _t(p.get("vat")),
            "jm": _t(p.get("jm"), "kg"),
            "ilosc": _t(p.get("ilosc")),
            "cena_netto": _t(p.get("cena_netto")),
            "wartosc_netto": _t(p.get("wartosc_netto")),
        })

    if not pozycje:
        raise ValueError("Model nie odnalazł żadnych pozycji towarowych na dokumencie.")

    dane["pozycje"] = pozycje
    dane["suma_netto_dokument"] = _t(surowe_dane.get("suma_netto_dokument"))
    dane["stawki"] = [s for s in _l(surowe_dane.get("stawki")) if isinstance(s, dict)]
    dane["do_zaplaty"] = _t(surowe_dane.get("do_zaplaty"))
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

def generuj_tekst_edi(dane: dict) -> str:
    pozycje = [p for p in (dane.get("pozycje") or []) if isinstance(p, dict)]
    wyst = dane.get("wystawca") or {}

    nip_wyst = re.sub(r"\D", "", str(wyst.get("nip") or ""))

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
        kod_glowny = str(poz.get("kod_dopasowany") or "").strip()

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

async def main(page: ft.Page):
    page.title = "ocrLmm Mobilny"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    konfig = wczytaj_konfiguracje()

    ostatnia_sciezka_edi = {"sciezka": None}
    aktualne_zdjecie = {"sciezka": None}

    poprzedni_dialog = {"dlg": None}
    blokady = {"analiza": False}

    def zamknij_kazdy_dialog(e=None):
        try:
            page.pop_dialog()
        except Exception:
            pass

    def bezpiecznie_otworz_dialog(dlg):
        if dlg in page._dialogs.controls and dlg.open:
            return

        zamknij_kazdy_dialog()

        if dlg in page._dialogs.controls:
            page._dialogs.controls.remove(dlg)

        page.show_dialog(dlg)

    tresc_bledu = ft.Text("", size=14)
    tytul_bledu = ft.Text("Komunikat", weight=ft.FontWeight.BOLD)

    def zamknij_alert(e):
        page.pop_dialog()

    def zamknij_alert_i_wroc(e):
        zamknij_kazdy_dialog()
        odtworz = poprzedni_dialog["dlg"]
        poprzedni_dialog["dlg"] = None
        if odtworz:
            bezpiecznie_otworz_dialog(odtworz)

    dlg_alert = ft.AlertDialog(
        modal=True,
        title=tytul_bledu,
        content=tresc_bledu,
        actions=[
            ft.Button(content=ft.Text("Rozumiem"), on_click=zamknij_alert_i_wroc)
        ]
    )

    def pokaz_okno_bledu(tytul: str, wiadomosc: str, powrot_do=None):
        poprzedni_dialog["dlg"] = powrot_do
        tytul_bledu.value = str(tytul)
        tresc_bledu.value = str(wiadomosc)
        bezpiecznie_otworz_dialog(dlg_alert)

    # --- KONSOLA LOGÓW ---
    konsola_logow = ft.ListView(expand=True, auto_scroll=True, height=300, spacing=5)

    def dopisz_log(wiadomosc: str, kolor=ft.Colors.WHITE):
        czas = datetime.now().strftime("%H:%M:%S")
        konsola_logow.controls.append(ft.Text(f"[{czas}] {wiadomosc}", size=12, color=kolor))
        if len(konsola_logow.controls) > 300:
            del konsola_logow.controls[:-300]
        page.update()

    async def kopiuj_logi(e):
        tekst = "\n".join([c.value for c in konsola_logow.controls])
        sciezka_logow = os.path.join(KATALOG_DANYCH, f"logi_ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

        try:
            with open(sciezka_logow, "w", encoding="utf-8") as f:
                f.write(tekst)

            if hasattr(serwis_udostepniania, "share_files"):
                try:
                    await serwis_udostepniania.share_files(
                        [ft.ShareFile.from_path(sciezka_logow)],
                        text="Logi z aplikacji ocrLmm"
                    )
                except Exception:
                    await serwis_udostepniania.share_files([sciezka_logow])
            else:
                dopisz_log("Błąd: Moduł udostępniania plików niedostępny.", ft.Colors.RED)

            status_text.value = "Otwarto menu udostępniania pliku z logami."
        except Exception as err:
            dopisz_log(f"Błąd eksportu: {err}", ft.Colors.RED)
            status_text.value = "Błąd eksportu logów."

        page.update()
        page.pop_dialog()

    dlg_konsola = ft.AlertDialog(
        modal=True,
        title=ft.Text("Konsola systemowa (Logi)"),
        content=ft.Container(content=konsola_logow, width=400, height=350),
        actions=[
            ft.Button("Udostępnij / Kopiuj", on_click=kopiuj_logi),
            ft.Button("Zamknij", on_click=zamknij_alert)
        ]
    )

    def otworz_konsole(e):
        bezpiecznie_otworz_dialog(dlg_konsola)

    def wykonaj_czyszczenie_katalogu(e):
        page.pop_dialog()
        usuniete_pliki = 0
        wzorce = ["img_*.jpg", "foto_*.jpg", "edi_*.txt"]
        for wzorzec in wzorce:
            sciezka_wzorca = os.path.join(KATALOG_DANYCH, wzorzec)
            for sciezka_pliku in glob.glob(sciezka_wzorca):
                try:
                    os.remove(sciezka_pliku)
                    usuniete_pliki += 1
                except Exception:
                    pass

        ostatnia_sciezka_edi["sciezka"] = None
        usun_wybrane_zdjecie(None)

        status_text.value = f"Wyczyszczono katalog roboczy (usunięto {usuniete_pliki} plików). Stan zresetowany."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    dlg_potwierdz_czyszczenie = ft.AlertDialog(
        modal=True,
        title=ft.Text("⚠️ Potwierdzenie usunięcia"),
        content=ft.Text(
            "Czy na pewno chcesz usunąć wszystkie wygenerowane pliki EDI oraz zdjęcia tymczasowe z katalogu aplikacji?\n\n"
            "Baza towarowa i konfiguracja nie zostaną usunięte."
        ),
        actions=[
            ft.Button(content=ft.Text("Anuluj"), on_click=zamknij_alert),
            ft.Button(
                content=ft.Text("Tak, wyczyść"),
                style=ft.ButtonStyle(bgcolor=ft.Colors.RED_800, color=ft.Colors.WHITE),
                on_click=wykonaj_czyszczenie_katalogu
            )
        ]
    )

    # --- OKNO ZARZĄDZANIA WŁASNYMI KODAMI ---
    txt_nowy_wzorzec = ft.TextField(label="Nazwa z faktury (np. BANAN)", dense=True, expand=True)
    txt_nowy_kod = ft.TextField(label="Kod PC-Market", dense=True, width=130)
    lista_mapowan_view = ft.ListView(expand=True, spacing=6, height=220)

    def odswiez_widok_mapowan(filtr: str = ""):
        lista_mapowan_view.controls.clear()
        filtr_upper = filtr.upper().strip()
        mapa = wczytaj_baze_mapowan()

        for wzorzec, kod in sorted(mapa.items()):
            if filtr_upper and filtr_upper not in wzorzec and filtr_upper not in kod:
                continue

            def stworz_callback_usun(wz=wzorzec):
                def usun_klik(e):
                    m = wczytaj_baze_mapowan()
                    if wz in m:
                        del m[wz]
                        zapisz_baze_mapowan(m)
                        odswiez_widok_mapowan(txt_filtr_bazy.value)
                        odswiez_status_bazy()
                return usun_klik

            lista_mapowan_view.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column([
                                ft.Text(wzorzec, weight=ft.FontWeight.BOLD, size=13),
                                ft.Text(f"Kod: {kod}", size=11, color=ft.Colors.GREEN_400)
                            ], expand=True),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=ft.Colors.RED_400,
                                on_click=stworz_callback_usun(wzorzec)
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    padding=8,
                    bgcolor=ft.Colors.GREY_900,
                    border_radius=6
                )
            )
        page.update()

    def dodaj_nowe_mapowanie(e):
        wz = txt_nowy_wzorzec.value.strip().upper()
        kd = txt_nowy_kod.value.strip()
        if not wz or not kd:
            pokaz_okno_bledu("Błąd", "Podaj nazwę wzorca oraz kod PC-Market.", powrot_do=dlg_baza_edycja)
            return

        mapa = wczytaj_baze_mapowan()
        dodaj_regule(mapa, wz, kd)
        zapisz_baze_mapowan(mapa)

        txt_nowy_wzorzec.value = ""
        txt_nowy_kod.value = ""
        odswiez_widok_mapowan(txt_filtr_bazy.value)
        odswiez_status_bazy()
        status_text.value = f"Dodano powiązanie: {wz} -> {kd}"
        status_text.color = ft.Colors.GREEN_ACCENT
        page.update()

    txt_filtr_bazy = ft.TextField(
        label="🔍 Filtruj zapisane reguły...",
        dense=True,
        on_change=lambda e: odswiez_widok_mapowan(txt_filtr_bazy.value)
    )

    dlg_baza_edycja = ft.AlertDialog(
        modal=True,
        title=ft.Text("📦 Baza i Edycja Powiązań"),
        content=ft.Column(
            [
                ft.Text("Dodaj wzorzec towaru (np. BANAN -> 4001):", size=12, color=ft.Colors.GREY_400),
                ft.Row([txt_nowy_wzorzec, txt_nowy_kod]),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.ADD), ft.Text("Zapisz powiązanie")], alignment=ft.MainAxisAlignment.CENTER),
                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE),
                    on_click=dodaj_nowe_mapowanie
                ),
                ft.Divider(),
                txt_filtr_bazy,
                lista_mapowan_view
            ],
            tight=True,
            width=360,
            spacing=10
        ),
        actions=[ft.Button(content=ft.Text("Zamknij"), on_click=zamknij_alert)]
    )

    def otworz_okno_bazy_recznej(e):
        odswiez_widok_mapowan()
        bezpiecznie_otworz_dialog(dlg_baza_edycja)

    # --- WERYFIKACJA I WYSZUKIWARKA W LOCIE ---
    stan_weryfikacji = {
        "dane": None,
        "baza": [],
        "uzywa_bazy": True,
        "status_sum": "BRAK_DANYCH",
        "info_sumy": "",
        "indeks_edytowany": -1
    }

    lista_pozycji_weryfikacji = ft.ListView(expand=True, spacing=10, height=350)

    def klik_usun_przypisanie(idx):
        if idx >= 0 and stan_weryfikacji["dane"]:
            poz = stan_weryfikacji["dane"]["pozycje"][idx]
            poz["kod_dopasowany"] = ""
            poz["pewnosc"] = "BRAK"

            oryginalna_nazwa = poz.get("oryg_nazwa", "").upper().strip()
            if oryginalna_nazwa:
                mapa = wczytaj_baze_mapowan()
                if usun_regule(mapa, oryginalna_nazwa):
                    zapisz_baze_mapowan(mapa)
                    odswiez_status_bazy()

            odswiez_weryfikacje()

    def odswiez_weryfikacje():
        lista_pozycji_weryfikacji.controls.clear()
        if not stan_weryfikacji["dane"]:
            return

        mapa_kod_nazwa = {t["kod_wew"]: t["nazwa"] for t in stan_weryfikacji["baza"]}

        for i, poz in enumerate(stan_weryfikacji["dane"].get("pozycje", [])):
            nazwa = poz.get("oryg_nazwa", "")
            kod = poz.get("kod_dopasowany", "")
            pewnosc = poz.get("pewnosc", "BRAK")

            if kod:
                if pewnosc == "ORYGINAL":
                    tekst_kodu = ft.Text(f"Kod z faktury: {kod}", size=12, color=ft.Colors.CYAN_400)
                else:
                    nazwa_dopasowana = mapa_kod_nazwa.get(kod, "Pozycja zdefiniowana ręcznie")
                    if pewnosc == "ROZMYTE":
                        tekst_kodu = ft.Text(
                            f"Towar: {nazwa_dopasowana} (Kod: {kod}) [⚠️ Sprawdź]",
                            size=12, color=ft.Colors.AMBER_300
                        )
                    else:
                        tekst_kodu = ft.Text(
                            f"Towar: {nazwa_dopasowana} (Kod: {kod})",
                            size=12, color=ft.Colors.GREEN_400
                        )
            else:
                tekst_kodu = ft.Text("BRAK DOPASOWANIA (Wybierz ręcznie!)", size=12, color=ft.Colors.RED_400, weight=ft.FontWeight.BOLD)

            przyciski_akcji = [
                ft.IconButton(
                    icon=ft.Icons.SEARCH,
                    tooltip="Wyszukaj i zmień",
                    icon_color=ft.Colors.BLUE_400,
                    on_click=lambda e, idx=i: otworz_wyszukiwarke(idx)
                )
            ]

            if kod:
                przyciski_akcji.append(
                    ft.IconButton(
                        icon=ft.Icons.LINK_OFF,
                        tooltip="Rozparuj i zapomnij kod",
                        icon_color=ft.Colors.RED_400,
                        on_click=lambda e, idx=i: klik_usun_przypisanie(idx)
                    )
                )

            kolumna_tekstow = [
                ft.Text(nazwa, weight=ft.FontWeight.BOLD, size=13),
                tekst_kodu
            ]
            for ostrzezenie in poz.get("ostrzezenia", []):
                kolumna_tekstow.append(ft.Text(f"⚠️ {ostrzezenie}", size=11, color=ft.Colors.AMBER_300))

            lista_pozycji_weryfikacji.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Column(kolumna_tekstow, expand=True),
                        ft.Row(przyciski_akcji, spacing=0)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=8,
                    bgcolor=ft.Colors.GREY_900,
                    border_radius=8
                )
            )
        page.update()

    async def zapisz_edi_i_zakoncz():
        dane = stan_weryfikacji["dane"]
        status_sum = stan_weryfikacji["status_sum"]
        info_sumy = stan_weryfikacji["info_sumy"]
        uzywa_bazy = stan_weryfikacji["uzywa_bazy"]

        if uzywa_bazy:
            puste = [p for p in dane.get("pozycje", []) if not p.get("kod_dopasowany")]
            if puste:
                wskazowka = ""
                if not stan_weryfikacji["baza"]:
                    wskazowka = "\n\nBaza towarów jest pusta: wczytaj plik bazy w ustawieniach albo wyłącz dopasowywanie do bazy."
                pokaz_okno_bledu(
                    "Nieprzypisane towary",
                    f"Przed wygenerowaniem EDI każda pozycja musi mieć kod PC-Market. "
                    f"Brakuje kodów dla {len(puste)} pozycji (czerwone na liście).{wskazowka}",
                    powrot_do=dlg_weryfikacja
                )
                return

        dopisz_log("Generowanie struktury pliku EDI z potwierdzonymi kodami...")
        tresc_edi = generuj_tekst_edi(dane)

        nr_dok = "".join(c for c in str(dane.get("nr_dok") or "") if c.isalnum() or c in ("-", "_")) or "faktura"
        nazwa_pliku = f"edi_{nr_dok}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        sciezka_edi = os.path.join(KATALOG_DANYCH, nazwa_pliku)

        try:
            with open(sciezka_edi, "w", encoding="windows-1250", errors="replace") as f:
                f.write(tresc_edi)
        except Exception as err_zapis:
            dopisz_log(f"Błąd zapisu pliku EDI: {err_zapis}", ft.Colors.RED)
            pokaz_okno_bledu("Błąd zapisu EDI", str(err_zapis), powrot_do=dlg_weryfikacja)
            return

        ostatnia_sciezka_edi["sciezka"] = sciezka_edi
        dopisz_log(f"Zakończono sukcesem. Zapisano: {nazwa_pliku}", ft.Colors.GREEN)

        tryb_info = " (dopasowano do PC-Market)" if uzywa_bazy else " (kody oryginalne)"
        if status_sum == "OK":
            status_text.value = f"✅ Gotowe! Zapisano: {nazwa_pliku}\n({info_sumy}){tryb_info}"
            status_text.color = ft.Colors.GREEN_ACCENT
        elif status_sum == "BLAD":
            status_text.value = f"⚠️ Zapisano z ostrzeżeniem sumy: {nazwa_pliku}\n{info_sumy}{tryb_info}"
            status_text.color = ft.Colors.AMBER_ACCENT
        else:
            status_text.value = f"ℹ️ Zapisano: {nazwa_pliku}\n{info_sumy}{tryb_info}"
            status_text.color = ft.Colors.CYAN_ACCENT

        btn_udostepnij.visible = True
        await udostepnij_plik(sciezka_edi)

        stan_weryfikacji["dane"] = None
        btn_wroc_weryfikacja.visible = False
        aktualne_zdjecie["sciezka"] = None
        podglad_obrazu.src = PUSTY_OBRAZ
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        wiersz_obrotu.visible = False
        btn_ponow.visible = False
        ustaw_stan_przycisku_foto(False)
        page.update()

    async def klik_zatwierdz_weryfikacje(e):
        zamknij_kazdy_dialog()
        await zapisz_edi_i_zakoncz()

    def klik_anuluj_weryfikacje(e):
        zamknij_kazdy_dialog()
        status_text.value = (
            "Anulowano generowanie EDI. Możesz wrócić do weryfikacji bez ponownej analizy "
            "albo wybrać inne zdjęcie."
        )
        status_text.color = ft.Colors.ORANGE_ACCENT
        btn_foto.disabled = False
        btn_aparat.disabled = False
        btn_wroc_weryfikacja.visible = stan_weryfikacji["dane"] is not None
        page.update()

    def klik_wroc_do_weryfikacji(e):
        if stan_weryfikacji["dane"]:
            odswiez_weryfikacje()
            bezpiecznie_otworz_dialog(dlg_weryfikacja)

    dlg_weryfikacja = ft.AlertDialog(
        modal=True,
        title=ft.Text("Weryfikacja kodów z faktury"),
        content=ft.Container(
            content=ft.Column([
                ft.Text("Zielony: pewne | Żółty: rozmyte (sprawdź) | Czerwony: brak. Kliknij lupę, aby poprawić.", size=12, color=ft.Colors.GREY_400),
                lista_pozycji_weryfikacji
            ], tight=True),
            width=380,
            height=450
        ),
        actions=[
            ft.Button("Anuluj", color=ft.Colors.RED_400, on_click=klik_anuluj_weryfikacje),
            ft.Button("Zatwierdź i Generuj", style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE), on_click=klik_zatwierdz_weryfikacje)
        ]
    )

    lista_wyszukiwarki = ft.ListView(expand=True, spacing=5, height=350)
    pole_szukaj_towaru = ft.TextField(label="Wpisz nazwę lub kod z PC-Market...", dense=True, on_change=lambda e: filtruj_wyszukiwarke())

    def filtruj_wyszukiwarke():
        lista_wyszukiwarki.controls.clear()
        fraza = usun_diakrytyki(pole_szukaj_towaru.value.strip().upper())
        fragmenty = fraza.split()

        licznik = 0
        for towar in stan_weryfikacji["baza"]:
            nazwa_towaru = towar["nazwa"]
            kod_towaru = towar["kod_wew"]

            czy_pasuje = True
            for frag in fragmenty:
                if frag not in usun_diakrytyki(nazwa_towaru) and frag not in kod_towaru:
                    czy_pasuje = False
                    break

            if czy_pasuje:
                lista_wyszukiwarki.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(nazwa_towaru, size=12, weight=ft.FontWeight.BOLD),
                                ft.Text(f"Kod: {kod_towaru}", size=11, color=ft.Colors.GREY_400)
                            ], expand=True),
                            ft.Button("Wybierz", style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900), on_click=lambda e, k=kod_towaru: klik_wybierz_z_wyszukiwarki(k))
                        ]),
                        padding=4,
                        border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.GREY_800))
                    )
                )
                licznik += 1
                if licznik >= 40:
                    break
        page.update()

    def otworz_wyszukiwarke(idx):
        stan_weryfikacji["indeks_edytowany"] = idx
        pole_szukaj_towaru.value = ""
        filtruj_wyszukiwarke()
        bezpiecznie_otworz_dialog(dlg_wyszukiwarka)

    def klik_wybierz_z_wyszukiwarki(kod):
        idx = stan_weryfikacji["indeks_edytowany"]
        if idx >= 0 and stan_weryfikacji["dane"]:
            poz = stan_weryfikacji["dane"]["pozycje"][idx]
            poz["kod_dopasowany"] = kod
            poz["pewnosc"] = "REGULA"

            oryginalna_nazwa = poz.get("oryg_nazwa", "").upper().strip()
            if oryginalna_nazwa:
                mapa = wczytaj_baze_mapowan()
                dodaj_regule(mapa, oryginalna_nazwa, kod)
                zapisz_baze_mapowan(mapa)
                odswiez_status_bazy()

        odswiez_weryfikacje()
        bezpiecznie_otworz_dialog(dlg_weryfikacja)

    def zamknij_wyszukiwarke(e):
        odswiez_weryfikacje()
        bezpiecznie_otworz_dialog(dlg_weryfikacja)

    dlg_wyszukiwarka = ft.AlertDialog(
        modal=True,
        title=ft.Text("Baza PC-Market"),
        content=ft.Container(
            content=ft.Column([
                pole_szukaj_towaru,
                lista_wyszukiwarki
            ], tight=True),
            width=380,
            height=450
        ),
        actions=[
            ft.Button("Wróć do weryfikacji", on_click=zamknij_wyszukiwarke)
        ]
    )

    # --- USTAWIENIA SIECIOWE ---
    chk_cloud = ft.Checkbox(
        label="Użyj chmury (Google Gemini)",
        value=konfig.get("use_cloud", True)
    )

    dd_rozdzielczosc = ft.Dropdown(
        label="Jakość skanu (Szybkość vs Tokeny)",
        options=[
            ft.dropdown.Option(key="1800", text="1800px (Najlepszy odczyt OCR)"),
            ft.dropdown.Option(key="1400", text="1400px (Kompromis)"),
            ft.dropdown.Option(key="1024", text="1024px (Szybciej, ale może gubić drobny druk)")
        ],
        value=str(konfig.get("image_resolution", 1800)),
        dense=True
    )

    chk_db_matching = ft.Checkbox(
        label="Dopasowuj do bazy PC-Market",
        value=konfig.get("use_db_matching", True)
    )

    txt_gemini_key = ft.TextField(
        label="Klucz Google AI Studio API",
        value=konfig.get("gemini_api_key", ""),
        password=True,
        can_reveal_password=True,
        dense=True
    )

    txt_gemini_model = ft.TextField(
        label="Model Google AI (np. gemini-3.6-flash)",
        value=konfig.get("gemini_model", "gemini-3.6-flash"),
        dense=True
    )

    txt_mac = ft.TextField(label="Adres MAC (Wake-on-LAN)", value=konfig.get("wol_mac", ""), dense=True)
    txt_ip = ft.TextField(label="IP Serwera LM Studio", value=konfig.get("local_ip", "192.168.1.154"), dense=True)
    txt_port = ft.TextField(label="Port LM Studio", value=konfig.get("local_port", "1234"), dense=True)

    lista_zapisanych_modeli = konfig.get("local_models_list", ["qwen/qwen3-vl-8b-instruct", "qwen3-vl-4b-instruct", "qwen3.5-9b"])
    aktualny_model = konfig.get("local_model", "qwen3.5-9b")

    if aktualny_model and aktualny_model not in lista_zapisanych_modeli:
        lista_zapisanych_modeli.append(aktualny_model)

    dd_local_model = ft.Dropdown(
        label="Wybierz model LM Studio",
        options=[ft.dropdown.Option(m) for m in lista_zapisanych_modeli],
        value=aktualny_model if lista_zapisanych_modeli else None,
        dense=True,
        expand=True
    )

    txt_dodaj_model = ft.TextField(label="Nazwa nowego modelu...", dense=True, expand=True)

    def klik_dodaj_model(e):
        nowy_model = txt_dodaj_model.value.strip()
        if nowy_model:
            istniejace = [opt.key for opt in dd_local_model.options]
            if nowy_model not in istniejace:
                dd_local_model.options.append(ft.dropdown.Option(nowy_model))
            dd_local_model.value = nowy_model
            txt_dodaj_model.value = ""
            page.update()

    def klik_usun_model(e):
        model_do_usuniecia = dd_local_model.value
        if model_do_usuniecia:
            dd_local_model.options = [opt for opt in dd_local_model.options if opt.key != model_do_usuniecia]
            dd_local_model.value = dd_local_model.options[0].key if dd_local_model.options else None
            page.update()

    btn_dodaj_model = ft.IconButton(
        icon=ft.Icons.ADD_CIRCLE,
        icon_color=ft.Colors.GREEN_400,
        tooltip="Dodaj do listy",
        on_click=klik_dodaj_model
    )

    btn_usun_model = ft.IconButton(
        icon=ft.Icons.DELETE,
        icon_color=ft.Colors.RED_400,
        tooltip="Usuń wybrany model",
        on_click=klik_usun_model
    )

    wiersz_wyboru_modelu = ft.Row([dd_local_model, btn_usun_model])
    wiersz_dodawania_modelu = ft.Row([txt_dodaj_model, btn_dodaj_model])

    txt_local_api_key = ft.TextField(
        label="Klucz API serwera lokalnego (opcjonalnie)",
        value=konfig.get("local_api_key", ""),
        password=True,
        can_reveal_password=True,
        dense=True
    )

    async def klik_budzenie_wol(e):
        try:
            loop = asyncio.get_running_loop()
            target_ip = txt_ip.value.strip() or "192.168.1.154"
            target_mac = txt_mac.value.strip()

            await loop.run_in_executor(None, wyslij_wol, target_mac, target_ip)
            status_text.value = "Pakiet Wake-on-LAN wysłany pomyślnie."
            status_text.color = ft.Colors.CYAN_ACCENT
        except Exception as err_wol:
            status_text.value = f"Błąd WoL: {err_wol}"
            status_text.color = ft.Colors.RED_ACCENT
        page.update()

    btn_wol_ustawienia = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.POWER_SETTINGS_NEW), ft.Text("Obudź serwer lokalny (WoL)")]),
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_900, color=ft.Colors.BLUE_200),
        on_click=klik_budzenie_wol
    )

    lbl_status_bazy = ft.Text("", size=12)

    def odswiez_status_bazy():
        sciezka = pobierz_aktualna_sciezke_bazy(konfig)
        baza = wczytaj_baze_pcmarket(sciezka)
        mapa = wczytaj_baze_mapowan()
        nazwa = os.path.basename(sciezka)
        if baza:
            lbl_status_bazy.value = f"Katalog: {len(baza)} towarów ({nazwa}) | Własne reguły: {len(mapa)}"
            lbl_status_bazy.color = ft.Colors.GREEN_300
        else:
            lbl_status_bazy.value = f"⚠️ Brak towarów w pliku bazy ({nazwa}) | Własne reguły: {len(mapa)}"
            lbl_status_bazy.color = ft.Colors.ORANGE_300
        page.update()

    picker_bazy = ft.FilePicker()
    page.services.append(picker_bazy)

    async def wybierz_plik_bazy(e):
        try:
            pliki = await picker_bazy.pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["txt"]
            )
            if pliki and len(pliki) > 0:
                sciezka_zrodlowa = pliki[0].path
                if sciezka_zrodlowa:
                    oryginalna_nazwa = os.path.basename(sciezka_zrodlowa)

                    if not wczytaj_baze_pcmarket(sciezka_zrodlowa):
                        pokaz_okno_bledu(
                            "Nieprawidłowy plik bazy",
                            f"W pliku {oryginalna_nazwa} nie znaleziono żadnych towarów. Oczekiwany układ: "
                            "kolumny rozdzielone tabulatorem, nazwa w 1. kolumnie, kod w 3. "
                            "Zachowano dotychczasową bazę.",
                            powrot_do=dlg_ustawienia
                        )
                        return

                    docelowa_sciezka = os.path.join(KATALOG_DANYCH, oryginalna_nazwa)
                    try:
                        shutil.copyfile(sciezka_zrodlowa, docelowa_sciezka)
                    except Exception:
                        docelowa_sciezka = sciezka_zrodlowa

                    konfig["baza_file_path"] = docelowa_sciezka
                    zapisz_konfiguracje(konfig)

                    odswiez_status_bazy()
                    status_text.value = f"Wczytano nową bazę ({oryginalna_nazwa})."
                    status_text.color = ft.Colors.CYAN_ACCENT
                    page.update()
        except Exception as err_baza:
            pokaz_okno_bledu("Błąd wczytywania bazy", str(err_baza), powrot_do=dlg_ustawienia)

    btn_wybierz_baze = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN), ft.Text("Wybierz plik bazy (.txt)")], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(bgcolor=ft.Colors.AMBER_900, color=ft.Colors.WHITE),
        on_click=wybierz_plik_bazy
    )

    picker_mapowan = ft.FilePicker()
    page.services.append(picker_mapowan)

    async def wybierz_plik_mapowan(e):
        try:
            pliki = await picker_mapowan.pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"]
            )
            if pliki and len(pliki) > 0:
                sciezka_zrodlowa = pliki[0].path
                if sciezka_zrodlowa:
                    oryginalna_nazwa = os.path.basename(sciezka_zrodlowa)
                    nowe_reguly = wczytaj_plik_mapowan_z_walidacja(sciezka_zrodlowa)
                    dotychczasowe = wczytaj_baze_mapowan()

                    if dotychczasowe and os.path.exists(MAPA_FILE):
                        shutil.copyfile(MAPA_FILE, MAPA_FILE + ".bak")
                    polaczone = {**dotychczasowe, **nowe_reguly}
                    zapisz_baze_mapowan(polaczone)

                    odswiez_widok_mapowan()
                    odswiez_status_bazy()

                    status_text.value = (
                        f"Wczytano mapowania ({oryginalna_nazwa}): {len(nowe_reguly)} reguł z pliku, "
                        f"łącznie {len(polaczone)}."
                    )
                    status_text.color = ft.Colors.CYAN_ACCENT
                    page.update()
        except Exception as err_mapa:
            pokaz_okno_bledu("Błąd wczytywania mapowań", str(err_mapa), powrot_do=dlg_ustawienia)

    btn_wybierz_mapowania = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE), ft.Text("Wgraj plik mapowań (.json)")], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(bgcolor=ft.Colors.DEEP_ORANGE_900, color=ft.Colors.WHITE),
        on_click=wybierz_plik_mapowan
    )

    btn_otworz_baze_w_ustawieniach = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.EDIT_NOTE), ft.Text("Zarządzaj powiązaniami")], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE),
        on_click=otworz_okno_bazy_recznej
    )

    async def udostepnij_bazy_kody(e):
        sciezka_bazy = pobierz_aktualna_sciezke_bazy(konfig)
        pliki_sciezki = []
        pliki_share = []

        if os.path.exists(sciezka_bazy):
            pliki_sciezki.append(sciezka_bazy)
            pliki_share.append(ft.ShareFile.from_path(sciezka_bazy))

        if os.path.exists(MAPA_FILE):
            pliki_sciezki.append(MAPA_FILE)
            pliki_share.append(ft.ShareFile.from_path(MAPA_FILE))

        if not pliki_sciezki:
            pokaz_okno_bledu("Brak plików", "Nie znaleziono aktywnej bazy TXT ani zapisanych mapowań JSON.", powrot_do=dlg_ustawienia)
            return

        try:
            if hasattr(serwis_udostepniania, "share_files"):
                try:
                    await serwis_udostepniania.share_files(
                        pliki_share,
                        text="Aktualna baza towarowa i mapowania (ocrLmm)"
                    )
                except Exception:
                    await serwis_udostepniania.share_files(pliki_sciezki)
            else:
                pokaz_okno_bledu("Błąd", "Funkcja udostępniania niedostępna na tym urządzeniu.", powrot_do=dlg_ustawienia)
        except Exception as err:
            dopisz_log(f"Błąd eksportu kodów: {err}", ft.Colors.RED)
            pokaz_okno_bledu("Błąd udostępniania", str(err), powrot_do=dlg_ustawienia)

    btn_udostepnij_kody = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.IOS_SHARE), ft.Text("Udostępnij kody (TXT + JSON)")], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(bgcolor=ft.Colors.DEEP_PURPLE_800, color=ft.Colors.WHITE),
        on_click=udostepnij_bazy_kody
    )

    kontener_baza_pcmarket = ft.Column(
        [
            ft.Text("Baza towarowa PC-Market:", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
            chk_db_matching,
            btn_wybierz_baze,
            btn_wybierz_mapowania,
            btn_otworz_baze_w_ustawieniach,
            btn_udostepnij_kody,
            lbl_status_bazy
        ],
        spacing=6
    )

    kontener_gemini = ft.Column(
        [
            ft.Text("Konfiguracja Google Gemini:", weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
            txt_gemini_key,
            txt_gemini_model
        ],
        spacing=8,
        visible=chk_cloud.value
    )

    kontener_lokalny = ft.Column(
        [
            ft.Text("Konfiguracja serwera lokalnego:", weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_300),
            txt_mac,
            txt_ip,
            txt_port,
            ft.Text("Zarządzanie modelami LM Studio:", size=12, color=ft.Colors.GREY_400),
            wiersz_wyboru_modelu,
            wiersz_dodawania_modelu,
            txt_local_api_key,
            btn_wol_ustawienia
        ],
        spacing=8,
        visible=not chk_cloud.value
    )

    def przelacz_profil(e):
        kontener_gemini.visible = chk_cloud.value
        kontener_lokalny.visible = not chk_cloud.value
        page.update()

    chk_cloud.on_change = przelacz_profil

    status_text = ft.Text(
        "Wybierz zdjęcie faktury z galerii lub zrób zdjęcie aparatem.",
        size=13,
        color=ft.Colors.GREEN_ACCENT,
        text_align=ft.TextAlign.CENTER
    )
    pasek_postepu = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_ACCENT)
    podglad_obrazu = ft.Image(src=PUSTY_OBRAZ, visible=False, fit="contain", height=240)

    # --- APARAT (flet-camera: tylko Android / iOS / Web) ---
    kamera_obiektyw = fc.Camera(expand=True)
    

    def aparat_obslugiwany() -> bool:
        return bool(page.web) or page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)

    async def zamknij_pelny_ekran_aparatu(e=None):
        try:
            # Zwolnij sensor aparatu przed zamknięciem widoku
            await kamera_obiektyw.dispose()
        except Exception:
            pass
        
        if len(page.views) > 1:
            page.views.pop()
            page.update()

    # Obsługa gestu/przycisku „Wstecz” na telefonie
    page.on_view_pop = lambda e: asyncio.create_task(zamknij_pelny_ekran_aparatu())

    async def klik_migawka(e):
        try:
            dane_zdjecia = await kamera_obiektyw.take_picture()
            if not isinstance(dane_zdjecia, (bytes, bytearray)):
                raise ValueError(f"Aparat zwrócił nieoczekiwany typ: {type(dane_zdjecia).__name__}")
            sciezka = os.path.join(KATALOG_DANYCH, f"foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
            with open(sciezka, "wb") as f:
                f.write(dane_zdjecia)

            await zamknij_pelny_ekran_aparatu()
            ustaw_nowy_obraz(sciezka)
        except Exception as err:
            dopisz_log(f"Błąd migawki: {err}", ft.Colors.RED)
            pokaz_okno_bledu("Błąd aparatu", f"Nie udało się zrobić zdjęcia: {err}")

    async def otworz_aparat(e):
        if not aparat_obslugiwany():
            status_text.value = "Aparat działa tylko na telefonie (Android/iOS). Użyj wyboru z galerii."
            status_text.color = ft.Colors.AMBER_ACCENT
            page.update()
            return

        try:
            widok_aparatu = ft.View(
                route="/aparat",
                controls=[
                    ft.Stack([
                        ft.GestureDetector(
                            content=kamera_obiektyw,
                            on_tap=lambda ev: asyncio.create_task(klik_migawka(ev)),
                            expand=True
                        ),
                        ft.Container(
                            content=ft.Button(
                                "Anuluj",
                                style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE),
                                on_click=lambda ev: asyncio.create_task(zamknij_pelny_ekran_aparatu(ev))
                            ),
                            top=40,
                            right=20
                        ),
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Text(
                                        "Stuknij w dowolne miejsce, aby zrobić zdjęcie",
                                        color=ft.Colors.WHITE70,
                                        size=14,
                                        text_align=ft.TextAlign.CENTER
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.CENTER
                            ),
                            bottom=30,
                            left=0,
                            right=0
                        )
                    ], expand=True)
                ],
                padding=0,
                bgcolor=ft.Colors.BLACK
            )

            page.views.append(widok_aparatu)
            page.update()

            kamery = await asyncio.wait_for(kamera_obiektyw.get_available_cameras(), timeout=10)
            if not kamery:
                await zamknij_pelny_ekran_aparatu()
                pokaz_okno_bledu("Brak aparatu", "Nie wykryto żadnego sensora kamery w urządzeniu.")
                return

            wybrana = next(
                (c for c in kamery if c.lens_direction == fc.CameraLensDirection.BACK),
                kamery[0],
            )
            await asyncio.wait_for(
                kamera_obiektyw.initialize(wybrana, fc.ResolutionPreset.HIGH, enable_audio=False),
                timeout=30,
            )
            dopisz_log("Kamera pełnoekranowa zainicjalizowana.", ft.Colors.GREEN)

        except Exception as err:
            await zamknij_pelny_ekran_aparatu()
            dopisz_log(f"Błąd aparatu: {err}", ft.Colors.RED)
            pokaz_okno_bledu("Błąd aparatu", f"Nie udało się uruchomić aparatu: {err}")
    # --- KONIEC APARATU ---

    def ustaw_stan_przycisku_foto(czy_ma_zdjecie: bool):
        if czy_ma_zdjecie:
            ikona_btn_foto.icon = ft.Icons.SEND
            tekst_btn_foto.value = "Wyślij do analizy"
            btn_foto.style.bgcolor = ft.Colors.BLUE_700
            btn_aparat.visible = False
        else:
            ikona_btn_foto.icon = ft.Icons.PHOTO_LIBRARY
            tekst_btn_foto.value = "Wybierz z galerii"
            btn_foto.style.bgcolor = ft.Colors.GREEN_800
            btn_aparat.visible = True

        btn_foto.disabled = False
        btn_aparat.disabled = False

    def ustaw_nowy_obraz(sciezka: str):
        nowa_sciezka = os.path.join(KATALOG_DANYCH, f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        try:
            shutil.copyfile(sciezka, nowa_sciezka)
        except Exception:
            nowa_sciezka = sciezka

        aktualne_zdjecie["sciezka"] = nowa_sciezka
        stan_weryfikacji["dane"] = None
        btn_wroc_weryfikacja.visible = False
        podglad_obrazu.src = nowa_sciezka
        podglad_obrazu.visible = True
        btn_usun_zdjecie.visible = True
        wiersz_obrotu.visible = True
        ustaw_stan_przycisku_foto(True)
        status_text.value = "Zdjęcie załadowane. Sprawdź orientację i kliknij 'Wyślij do analizy'."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    def usun_wybrane_zdjecie(e):
        aktualne_zdjecie["sciezka"] = None
        stan_weryfikacji["dane"] = None
        btn_wroc_weryfikacja.visible = False
        podglad_obrazu.src = PUSTY_OBRAZ
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        btn_udostepnij.visible = False
        btn_ponow.visible = False
        wiersz_obrotu.visible = False
        ustaw_stan_przycisku_foto(False)
        btn_foto.disabled = False
        btn_aparat.disabled = False
        status_text.value = "Zdjęcie usunięte. Wybierz z galerii lub zrób nowe zdjęcie aparatem."
        status_text.color = ft.Colors.GREEN_ACCENT
        page.update()

    btn_usun_zdjecie = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE), ft.Text("Usuń wybrane zdjęcie")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False,
        style=ft.ButtonStyle(color=ft.Colors.RED_300),
        on_click=usun_wybrane_zdjecie
    )

    trwa_obracanie = False

    async def obroc_zdjecie(kierunek: str):
        nonlocal trwa_obracanie
        sciezka = aktualne_zdjecie["sciezka"]
        if not sciezka or not os.path.exists(sciezka) or trwa_obracanie:
            return

        trwa_obracanie = True
        btn_obroc_lewo.disabled = True
        btn_obroc_prawo.disabled = True
        page.update()

        try:
            loop = asyncio.get_running_loop()
            nowa_sciezka = os.path.join(KATALOG_DANYCH, f"img_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg")

            def wykonaj_obrot():
                with Image.open(sciezka) as im:
                    im = ImageOps.exif_transpose(im)
                    if kierunek == "lewo":
                        obrocony = im.transpose(Image.Transpose.ROTATE_90)
                    else:
                        obrocony = im.transpose(Image.Transpose.ROTATE_270)

                    if obrocony.mode in ("RGBA", "P"):
                        obrocony = obrocony.convert("RGB")
                    obrocony.save(nowa_sciezka, format="JPEG", quality=95)

            await loop.run_in_executor(None, wykonaj_obrot)

            try:
                if sciezka != nowa_sciezka and sciezka.startswith(KATALOG_DANYCH):
                    os.remove(sciezka)
            except Exception:
                pass

            aktualne_zdjecie["sciezka"] = nowa_sciezka
            stan_weryfikacji["dane"] = None
            btn_wroc_weryfikacja.visible = False
            podglad_obrazu.src = nowa_sciezka
            status_text.value = f"Obrócono zdjęcie w {kierunek}. Kliknij 'Wyślij do analizy'."
            status_text.color = ft.Colors.CYAN_ACCENT
        except Exception as err_rot:
            status_text.value = f"Błąd obracania: {err_rot}"
            status_text.color = ft.Colors.RED_ACCENT
        finally:
            trwa_obracanie = False
            btn_obroc_lewo.disabled = False
            btn_obroc_prawo.disabled = False
            page.update()

    async def klik_obroc_lewo(e):
        await obroc_zdjecie("lewo")

    async def klik_obroc_prawo(e):
        await obroc_zdjecie("prawo")

    btn_obroc_lewo = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.ROTATE_LEFT), ft.Text("W lewo")], alignment=ft.MainAxisAlignment.CENTER),
        expand=True,
        on_click=klik_obroc_lewo
    )

    btn_obroc_prawo = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.ROTATE_RIGHT), ft.Text("W prawo")], alignment=ft.MainAxisAlignment.CENTER),
        expand=True,
        on_click=klik_obroc_prawo
    )

    wiersz_obrotu = ft.Row([btn_obroc_lewo, btn_obroc_prawo], visible=False, spacing=10)

    def zamknij_dialog(e):
        page.pop_dialog()

    def zapisz_i_zamknij_dialog(e):
        konfig["use_cloud"] = chk_cloud.value
        konfig["use_db_matching"] = chk_db_matching.value
        konfig["gemini_api_key"] = txt_gemini_key.value.strip()
        konfig["gemini_model"] = txt_gemini_model.value.strip() or "gemini-3.6-flash"
        konfig["wol_mac"] = txt_mac.value.strip()
        konfig["local_ip"] = txt_ip.value.strip()
        konfig["local_port"] = txt_port.value.strip()

        konfig["local_model"] = dd_local_model.value or ""
        konfig["local_models_list"] = [opt.key for opt in dd_local_model.options]
        konfig["local_api_key"] = txt_local_api_key.value.strip()

        konfig["image_resolution"] = int(dd_rozdzielczosc.value)

        zapisz_konfiguracje(konfig)
        page.pop_dialog()
        status_text.value = "Ustawienia zostały zapisane."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    dlg_ustawienia = ft.AlertDialog(
        modal=True,
        title=ft.Text("⚙️ Ustawienia połączenia"),
        content=ft.Column(
            [
                chk_cloud,
                dd_rozdzielczosc,
                ft.Divider(),
                kontener_gemini,
                kontener_lokalny,
                ft.Divider(),
                kontener_baza_pcmarket
            ],
            tight=True, scroll=ft.ScrollMode.AUTO, spacing=10
        ),
        actions=[
            ft.Button(content=ft.Text("Anuluj"), on_click=zamknij_dialog),
            ft.Button(
                content=ft.Text("Zapisz"),
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE),
                on_click=zapisz_i_zamknij_dialog
            )
        ]
    )

    def otworz_ustawienia(e):
        bezpiecznie_otworz_dialog(dlg_ustawienia)

    serwis_udostepniania = ft.Share()
    page.services.append(serwis_udostepniania)

    async def udostepnij_plik(sciezka):
        if not sciezka or not os.path.exists(sciezka):
            status_text.value = "Brak pliku EDI do udostępnienia."
            status_text.color = ft.Colors.RED_ACCENT
            page.update()
            return

        try:
            if hasattr(serwis_udostepniania, "share_files"):
                try:
                    await serwis_udostepniania.share_files(
                        [ft.ShareFile.from_path(sciezka)],
                        text="Plik EDI dla PC-Market"
                    )
                    return
                except Exception:
                    await serwis_udostepniania.share_files([sciezka])
                    return

            status_text.value = f"Plik EDI zapisano w: {sciezka}"
            status_text.color = ft.Colors.CYAN_ACCENT
            page.update()

        except Exception as e_share:
            status_text.value = f"Błąd udostępniania: {e_share}"
            status_text.color = ft.Colors.RED_ACCENT
            page.update()

    def zglos_blad_analizy(tytul: str, komunikat: str):
        komunikat = komunikat or tytul
        dopisz_log(f"{tytul}: {komunikat}", ft.Colors.RED)
        pokaz_okno_bledu(tytul, komunikat)
        status_text.value = f"Błąd: {komunikat[:200]}"
        status_text.color = ft.Colors.RED_ACCENT

    async def przetworz_plik(sciezka_obrazu):
        if blokady["analiza"]:
            return
        if not sciezka_obrazu or not os.path.exists(sciezka_obrazu):
            pokaz_okno_bledu("Brak pliku", "Wskazane zdjęcie nie istnieje na dysku. Wybierz plik ponownie.")
            usun_wybrane_zdjecie(None)
            return

        blokady["analiza"] = True
        stan_weryfikacji["dane"] = None
        btn_wroc_weryfikacja.visible = False

        try:
            dopisz_log("Rozpoczęto analizę dokumentu.")
            aktualny_konfig = wczytaj_konfiguracje()
            uzywa_chmury = aktualny_konfig.get("use_cloud", True)
            uzywa_bazy = aktualny_konfig.get("use_db_matching", True)
            model_gemini = aktualny_konfig.get("gemini_model", "gemini-3.6-flash").strip()
            nazwa_silnika = model_gemini if uzywa_chmury else aktualny_konfig.get("local_model", "LM Studio")

            status_text.value = f"Przetwarzanie dokumentu ({nazwa_silnika})..."
            status_text.color = ft.Colors.ORANGE_ACCENT
            pasek_postepu.visible = True
            btn_foto.disabled = True
            btn_aparat.disabled = True
            btn_ponow.visible = False
            btn_usun_zdjecie.visible = False
            btn_udostepnij.visible = False
            wiersz_obrotu.visible = False
            page.update()

            loop = asyncio.get_running_loop()

            # --- PROAKTYWNE WYBUDZANIE (TYLKO DLA SERWERA LOKALNEGO) ---
            if not uzywa_chmury:
                ip_lokalne = aktualny_konfig.get("local_ip", "192.168.1.154").strip()
                port_str = aktualny_konfig.get("local_port", "1234").strip()
                mac_adres = aktualny_konfig.get("wol_mac", "").strip()
                port_lokalny = int(port_str) if port_str.isdigit() else 1234

                dopisz_log(f"Sprawdzanie stanu serwera LM Studio ({ip_lokalne}:{port_lokalny})...")

                serwer_zyje = await sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0)
                if not serwer_zyje:
                    dopisz_log("Serwer lokalny nie odpowiada. Wysyłanie pingu Wake-on-LAN...", ft.Colors.AMBER)
                    try:
                        await loop.run_in_executor(None, wyslij_wol, mac_adres, ip_lokalne)
                        dopisz_log("Pakiet WoL wysłany. Czekam na załadowanie LM Studio...", ft.Colors.CYAN)
                    except Exception as e_wol:
                        dopisz_log(f"Błąd wysyłania WoL: {e_wol}", ft.Colors.RED)

                    maks_czas_oczekiwania = 150
                    interwal_sprawdzania = 10
                    czas_miniony = 0

                    while czas_miniony < maks_czas_oczekiwania:
                        status_text.value = f"Oczekiwanie na uruchomienie LM Studio... ({czas_miniony}/{maks_czas_oczekiwania}s)"
                        status_text.color = ft.Colors.CYAN_ACCENT
                        page.update()

                        await asyncio.sleep(interwal_sprawdzania)
                        czas_miniony += interwal_sprawdzania

                        if czas_miniony % 30 == 0:
                            try:
                                await loop.run_in_executor(None, wyslij_wol, mac_adres, ip_lokalne)
                            except Exception:
                                pass

                        if await sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0):
                            serwer_zyje = True
                            dopisz_log(f"Serwer LM Studio gotowy do pracy po {czas_miniony}s!", ft.Colors.GREEN)
                            break

                    if not serwer_zyje:
                        raise TimeoutError(f"Serwer pod adresem {ip_lokalne} nie uruchomił się w czasie {maks_czas_oczekiwania}s.")
            # --- KONIEC PROCEDURY WYBUDZANIA ---

            dopisz_log("Przygotowywanie i kompresja obrazu...")
            wymiar_obrazu = aktualny_konfig.get("image_resolution", 1800)
            base64_image = await loop.run_in_executor(None, kompresuj_do_base64, sciezka_obrazu, wymiar_obrazu)

            prompt = (
                "Jesteś precyzyjnym systemem OCR do faktur, specyfikacji mięsnych i dokumentów PZ. "
                "Przepisz DOKŁADNIE dane ze zdjęcia dokumentu. Nie zmyślaj żadnych danych ani towarów!\n\n"
                "Instrukcje:\n"
                "1. Nagłówek: odczytaj numer dokumentu (nr_dok), datę oraz dane wystawcy i odbiorcy (NIP).\n"
                "2. Tabela towarowa: Przepisz DOKŁADNIE każdy wiersz z tabeli:\n"
                "   - nazwa: pełna nazwa towaru\n"
                "   - kod: kod towaru / CN / Nr D-t\n"
                "   - ilosc: waga / ilość\n"
                "   - jm: jednostka miary (np. kg)\n"
                "   - cena_netto: cena netto po rabacie\n"
                "   - wartosc_netto: wartość netto pozycji\n"
                "   - vat: stawka VAT (np. 5 lub 23)\n"
                "3. Podsumowanie: odczytaj 'Razem netto' (suma_netto_dokument) oraz stawki VAT i do_zaplaty.\n\n"
                "Zwróć TYLKO i WYŁĄCZNIE czysty obiekt JSON zgodny ze strukturą (bez żadnych dodatkowych znaczników, bez markdownu):\n"
                "{\n"
                "  \"nr_dok\": \"...\",\n"
                "  \"data\": \"DD.MM.RRRR\",\n"
                "  \"wystawca\": {\"nazwa\": \"...\", \"nip\": \"...\"},\n"
                "  \"odbiorca\": {\"nazwa\": \"...\", \"nip\": \"...\"},\n"
                "  \"pozycje\": [\n"
                "    {\"nazwa\": \"...\", \"kod\": \"...\", \"vat\": \"5\", \"jm\": \"kg\", \"ilosc\": \"0.000\", \"cena_netto\": \"0.00\", \"wartosc_netto\": \"0.00\"}\n"
                "  ],\n"
                "  \"suma_netto_dokument\": \"0.00\",\n"
                "  \"stawki\": [{\"vat\": \"5\", \"suma_netto\": \"0.00\", \"suma_vat\": \"0.00\"}],\n"
                "  \"do_zaplaty\": \"0.00\"\n"
                "}"
            )

            if uzywa_chmury:
                dopisz_log("Wysyłanie danych do Google Gemini API...")
                klucz = aktualny_konfig.get("gemini_api_key", "").strip()
                pelny_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                naglowki = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {klucz}"
                }
                cialo_zapytania = {
                    "model": model_gemini,
                    "response_format": {"type": "json_object"},
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }],
                    "temperature": 0.0,
                    "max_tokens": 8192
                }
            else:
                dopisz_log("Wysyłanie zapytania do LM Studio...")
                ip = aktualny_konfig.get("local_ip", "192.168.1.154").strip()
                port = aktualny_konfig.get("local_port", "1234").strip()
                pelny_url = f"http://{ip}:{port}/v1/chat/completions"
                klucz = aktualny_konfig.get("local_api_key", "").strip()
                wybrany_model = aktualny_konfig.get("local_model", "qwen3.5-9b").strip()

                naglowki = {"Content-Type": "application/json"}
                if klucz:
                    naglowki["Authorization"] = f"Bearer {klucz}"

                cialo_zapytania = {
                    "model": wybrany_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Jesteś precyzyjnym systemem OCR. Zwracasz TYLKO i WYŁĄCZNIE surowy obiekt JSON. Nie używaj znaczników markdown (jak ```json) ani żadnego tekstu pobocznego."
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                            ]
                        }
                    ],
                    "temperature": 0.0,
                    "max_tokens": 8192,
                    "chat_template_kwargs": {"enable_thinking": False}
                }

            max_prob = 4
            opoznienie_poczatkowe = 2.0
            odpowiedz = None

            timeout_cfg = httpx.Timeout(10.0, read=300.0)

            status_text.value = f"Przetwarzanie dokumentu przez {nazwa_silnika}..."
            status_text.color = ft.Colors.ORANGE_ACCENT
            page.update()

            async with httpx.AsyncClient(timeout=timeout_cfg, verify=True) as client:
                for proba in range(max_prob):
                    dopisz_log(f"Trwa odczytywanie tekstu przez LLM (próba {proba + 1}/{max_prob})...")
                    odpowiedz = await client.post(
                        pelny_url,
                        headers=naglowki,
                        json=cialo_zapytania
                    )

                    if odpowiedz.status_code in [503, 429]:
                        if proba < max_prob - 1:
                            czas_oczekiwania = opoznienie_poczatkowe * (2 ** proba)
                            status_text.value = f"Serwer zajęty ({odpowiedz.status_code}). Ponawianie {proba + 1}/{max_prob} za {czas_oczekiwania:.1f}s..."
                            status_text.color = ft.Colors.AMBER_ACCENT
                            dopisz_log(f"Kod {odpowiedz.status_code}. Ponawianie za {czas_oczekiwania:.1f}s.", ft.Colors.AMBER)
                            page.update()
                            await asyncio.sleep(czas_oczekiwania)
                            continue

                    odpowiedz.raise_for_status()
                    break

                dopisz_log("Pobrano odpowiedź. Odkodowywanie JSON...")
                dane_odp = odpowiedz.json()
                wybor = dane_odp["choices"][0]
                odp_tekst = (wybor.get("message", {}).get("content") or "").strip()
                powod_konca = wybor.get("finish_reason")

                uzycie = dane_odp.get("usage") or {}
                tokeny_rozumowania = (uzycie.get("completion_tokens_details") or {}).get("reasoning_tokens")
                opis_tokenow = (
                    f"Tokeny: wejście={uzycie.get('prompt_tokens', '?')}, "
                    f"wyjście={uzycie.get('completion_tokens', '?')}"
                )
                if tokeny_rozumowania is not None:
                    opis_tokenow += f" (w tym rozumowanie={tokeny_rozumowania})"
                opis_tokenow += f", powód zakończenia={powod_konca}, obraz={wymiar_obrazu}px"
                dopisz_log(opis_tokenow, ft.Colors.CYAN if powod_konca != "length" else ft.Colors.RED)

            dane = None
            blad_parsowania = ""

            try:
                dane = json.loads(odp_tekst)
            except json.JSONDecodeError:
                dopasowanie = re.search(r'\{.*\}', odp_tekst, re.DOTALL)
                if dopasowanie:
                    try:
                        dane = json.loads(dopasowanie.group(0))
                    except json.JSONDecodeError as err:
                        blad_parsowania = str(err)
                else:
                    blad_parsowania = "Brak klamrowej struktury JSON w odpowiedzi."

            if dane is None:
                dopisz_log(f"BŁĄD PARSOWANIA JSON: {blad_parsowania}", ft.Colors.RED)
                dopisz_log(f"Zwrócony tekst przez model:\n{odp_tekst}", ft.Colors.ORANGE)
                if powod_konca == "length":
                    raise ValueError(
                        f"Odpowiedź modelu została ucięta po osiągnięciu limitu {cialo_zapytania['max_tokens']} tokenów "
                        f"(obraz {wymiar_obrazu}px). Zobacz w konsoli, czy model nie zapętlił się lub nie "
                        f"zużył limitu na rozumowanie, i spróbuj większej rozdzielczości."
                    )
                raise ValueError(f"Błąd parsowania JSON ({blad_parsowania}). Sprawdź konsolę logów.")

            dane = oczysc_odpowiedz_llm(dane)

            dopisz_log("Dopasowywanie pozycji do bazy PC-Market (w osobnym wątku)...")
            aktualna_baza_sciezka = pobierz_aktualna_sciezke_bazy(aktualny_konfig)
            baza_towarowa, dane, status_sum, info_sumy = await loop.run_in_executor(
                None, dopasuj_wszystkie_pozycje_w_tle, dane, uzywa_bazy, aktualna_baza_sciezka
            )

            stan_weryfikacji["dane"] = dane
            stan_weryfikacji["baza"] = baza_towarowa
            stan_weryfikacji["uzywa_bazy"] = uzywa_bazy
            stan_weryfikacji["status_sum"] = status_sum
            stan_weryfikacji["info_sumy"] = info_sumy
            stan_weryfikacji["indeks_edytowany"] = -1

            dopisz_log("Przygotowano okno weryfikacji.")
            status_text.value = "Oczekiwanie na potwierdzenie kodów..."
            status_text.color = ft.Colors.CYAN_ACCENT
            pasek_postepu.visible = False
            page.update()

            odswiez_weryfikacje()
            bezpiecznie_otworz_dialog(dlg_weryfikacja)

        except httpx.HTTPStatusError as http_err:
            status = http_err.response.status_code
            tresc = http_err.response.text[:350]
            dopisz_log(f"Błąd HTTP {status}: {tresc}", ft.Colors.RED)
            if status in (401, 403) or "API_KEY_INVALID" in tresc:
                zglos_blad_analizy("🔑 Błąd autoryzacji", "Klucz API jest nieprawidłowy lub brak uprawnień. Sprawdź ustawienia (zębatka).")
            elif status == 429:
                zglos_blad_analizy("⏳ Limit zapytań wyczerpany", "Zbyt wiele zapytań w krótkim czasie. Odczekaj 30 sekund.")
            elif status >= 500:
                zglos_blad_analizy("⏳ Serwer AI niedostępny", f"Serwer zwrócił kod {status}. Odczekaj chwilę i spróbuj ponownie.")
            else:
                zglos_blad_analizy("❌ Błąd zapytania HTTP", f"Status: {status}\n{tresc}")
        except httpx.TimeoutException:
            zglos_blad_analizy("⏳ Limit czasu", "Model nie odpowiedział w wyznaczonym czasie.")
        except httpx.RequestError as req_err:
            zglos_blad_analizy("🌐 Błąd połączenia", f"{type(req_err).__name__}: {req_err}")
        except Exception as err:
            nazwa_bledu = type(err).__name__
            zglos_blad_analizy(f"❌ Błąd przetwarzania ({nazwa_bledu})", str(err))
        finally:
            blokady["analiza"] = False
            pasek_postepu.visible = False
            btn_foto.disabled = False
            btn_aparat.disabled = False
            czy_ma_foto = bool(aktualne_zdjecie["sciezka"])
            btn_ponow.visible = czy_ma_foto
            btn_usun_zdjecie.visible = czy_ma_foto
            wiersz_obrotu.visible = czy_ma_foto
            page.update()

    picker = ft.FilePicker()
    page.services.append(picker)

    async def otworz_galerie():
        try:
            pliki = await picker.pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.IMAGE
            )
            if pliki and len(pliki) > 0:
                wybrany = pliki[0].path
                if wybrany:
                    ustaw_nowy_obraz(wybrany)
        except Exception as e_pick:
            status_text.value = f"Błąd wyboru pliku: {e_pick}"
            page.update()

    async def klik_glowny_przycisk(e):
        if aktualne_zdjecie["sciezka"]:
            await przetworz_plik(aktualne_zdjecie["sciezka"])
        else:
            await otworz_galerie()

    ikona_btn_foto = ft.Icon(ft.Icons.PHOTO_LIBRARY)
    tekst_btn_foto = ft.Text("Wybierz z galerii")

    btn_foto = ft.Button(
        content=ft.Row(
            [ikona_btn_foto, tekst_btn_foto],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        height=55,
        expand=True,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.GREEN_800,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=klik_glowny_przycisk
    )

    btn_aparat = ft.Button(
        content=ft.Row(
            [ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Zrób zdjęcie")],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        height=55,
        expand=True,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.BLUE_900,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=otworz_aparat
    )

    wiersz_wyboru_zdjecia = ft.Row([btn_foto, btn_aparat], spacing=10)

    async def klik_ponow(e):
        if aktualne_zdjecie["sciezka"]:
            await przetworz_plik(aktualne_zdjecie["sciezka"])

    btn_ponow = ft.Button(
        content=ft.Row(
            [ft.Icon(ft.Icons.REFRESH), ft.Text("Ponów analizę")],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        visible=False,
        height=48,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.AMBER_900,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=klik_ponow
    )

    btn_wroc_weryfikacja = ft.Button(
        content=ft.Row(
            [ft.Icon(ft.Icons.FACT_CHECK), ft.Text("Wróć do weryfikacji (bez ponownej analizy)")],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        visible=False,
        height=48,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.TEAL_800,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=klik_wroc_do_weryfikacji
    )

    async def klik_udostepnij(e):
        await udostepnij_plik(ostatnia_sciezka_edi["sciezka"])

    btn_udostepnij = ft.Button(
        content=ft.Row(
            [ft.Icon(ft.Icons.SHARE), ft.Text("Udostępnij plik EDI")],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        visible=False,
        height=48,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.BLUE_GREY_800,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=klik_udostepnij
    )

    btn_baza_ikona = ft.IconButton(
        icon=ft.Icons.STORAGE,
        tooltip="Baza i powiązania towarów",
        on_click=otworz_okno_bazy_recznej
    )

    btn_settings = ft.IconButton(
        icon=ft.Icons.SETTINGS,
        tooltip="Ustawienia połączenia",
        on_click=otworz_ustawienia
    )

    btn_konsola = ft.IconButton(
        icon=ft.Icons.TERMINAL,
        tooltip="Konsola zdarzeń (logi)",
        on_click=otworz_konsole
    )

    pasek_tytulu = ft.Row(
        [
            ft.Column(
                [
                    ft.Text("ocrLmm Mobile", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                    ft.Text("Skaner PZ do EDI (PC-Market)", size=12, color=ft.Colors.GREY_400)
                ],
                spacing=2
            ),
            ft.Row([btn_baza_ikona, btn_konsola, btn_settings], spacing=0)
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
    )

    def klik_wyczysc_katalog(e):
        bezpiecznie_otworz_dialog(dlg_potwierdz_czyszczenie)

    btn_wyczysc_katalog = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.CLEANING_SERVICES, size=18), ft.Text("Wyczyść katalog tymczasowy", size=12)], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.RED_900,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        expand=True,
        on_click=klik_wyczysc_katalog
    )

    wiersz_zarzadzania_katalogiem = ft.Row(
        [btn_wyczysc_katalog],
        spacing=10
    )

    odswiez_status_bazy()

    page.add(
        ft.Column(
            [
                pasek_tytulu,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                wiersz_wyboru_zdjecia,
                pasek_postepu,
                status_text,
                btn_ponow,
                btn_wroc_weryfikacja,
                btn_udostepnij,
                podglad_obrazu,
                wiersz_obrotu,
                btn_usun_zdjecie,
                ft.Divider(height=16, color=ft.Colors.GREY_800),
                wiersz_zarzadzania_katalogiem
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=10
        )
    )

if __name__ == "__main__":
    ft.run(main)
