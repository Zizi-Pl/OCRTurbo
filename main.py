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

# --- FUNKCJE POMOCNICZE / SANITYZACJA ---
def usun_diakrytyki(tekst: str) -> str:
    if not tekst:
        return ""
    nfkd = unicodedata.normalize('NFKD', tekst)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])

def normalizuj_nazwe(tekst: str) -> str:
    if not tekst:
        return ""
    t = tekst.upper().strip()
    t = re.sub(r"[.,/\\_\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def parsuj_kwote(wartosc: any) -> float:
    if wartosc is None:
        return 0.0
    s = str(wartosc).replace("\xa0", "").replace(" ", "").replace(",", ".").replace("n", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

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
    global _CACHE_BAZY
    if not sciezka:
        konf = wczytaj_konfiguracje()
        sciezka = pobierz_aktualna_sciezke_bazy(konf)

    if not os.path.exists(sciezka):
        return []

    try:
        mtime = os.path.getmtime(sciezka)
        if _CACHE_BAZY["sciezka"] == sciezka and _CACHE_BAZY["mtime"] == mtime:
            return _CACHE_BAZY["towary"]
    except OSError:
        mtime = 0.0

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
                k1 = f"{trzon} {wariant_norm}"
                if k1 not in mapa_nazw:
                    mapa_nazw[k1] = kod
                if kategoria and kategoria != trzon:
                    k2 = f"{kategoria} {wariant_norm}"
                    if k2 not in mapa_nazw:
                        mapa_nazw[k2] = kod
    return mapa_nazw

def dopasuj_towar_z_bazy(nazwa_faktura: str, kod_faktura: str, baza: list[dict], uzywaj_bazy: bool,
                         mapowania: dict = None, indeks: dict = None) -> tuple[str, str, str]:
    """Zwraca krotkę: (kod_dopasowany, kod_faktura, pewnosc)
       Pewność: 'REGULA', 'DOKLADNE', 'ROZMYTE', 'BRAK'
    """
    kod_faktura_clean = kod_faktura.strip()
    nazwa_faktura_clean = normalizuj_nazwe(nazwa_faktura)

    if not uzywaj_bazy:
        return kod_faktura_clean, kod_faktura_clean, "REGULA"

    if mapowania is None:
        mapowania = wczytaj_baze_mapowan()
    for nazwa_reguly, kod_reguly in mapowania.items():
        if normalizuj_nazwe(str(nazwa_reguly)) == nazwa_faktura_clean:
            return str(kod_reguly), kod_faktura_clean, "REGULA"

    if not baza:
        return "", kod_faktura_clean, "BRAK"

    mapa_nazw = indeks if indeks is not None else zbuduj_indeks_nazw(baza)

    if nazwa_faktura_clean in mapa_nazw:
        return mapa_nazw[nazwa_faktura_clean], kod_faktura_clean, "DOKLADNE"

    nazwa_faktura_bez_og = usun_diakrytyki(nazwa_faktura_clean)
    for wzorzec, kod in mapa_nazw.items():
        if usun_diakrytyki(wzorzec) == nazwa_faktura_bez_og:
            return kod, kod_faktura_clean, "DOKLADNE"

    if mapa_nazw:
        najlepsza_nazwa, wynik = process.extractOne(
            nazwa_faktura_clean,
            mapa_nazw.keys(),
            scorer=fuzz.token_sort_ratio
        )
        if wynik >= 75:
            return mapa_nazw[najlepsza_nazwa], kod_faktura_clean, "ROZMYTE"

    return "", kod_faktura_clean, "BRAK"

def wyslij_wol(mac_address: str, docelowe_ip: str = "255.255.255.255"):
    czysty_mac = re.sub(r'[^0-9A-Fa-f]', '', mac_address)
    if len(czysty_mac) != 12:
        raise ValueError(f"Nieprawidłowy format adresu MAC: {mac_address}")

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
        raise RuntimeError("Nie udało się wysłać pakietu WoL. Sprawdź sieć Wi-Fi.")

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

def oczysc_odpowiedz_llm(surowe_dane: any) -> dict:
    if not isinstance(surowe_dane, dict):
        raise ValueError("Model zwrócił odpowiedź, która nie jest obiektem JSON.")

    def _d(v): return v if isinstance(v, dict) else {}
    def _l(v): return v if isinstance(v, list) else []

    dane = {}
    dane["nr_dok"] = str(surowe_dane.get("nr_dok") or "faktura").strip()
    dane["data"] = str(surowe_dane.get("data") or datetime.now().strftime("%d.%m.%Y")).strip()

    wyst = _d(surowe_dane.get("wystawca"))
    dane["wystawca"] = {
        "nazwa": str(wyst.get("nazwa") or "").strip(),
        "nip": str(wyst.get("nip") or "").strip()
    }

    odb = _d(surowe_dane.get("odbiorca"))
    dane["odbiorca"] = {
        "nazwa": str(odb.get("nazwa") or "").strip(),
        "nip": str(odb.get("nip") or "").strip()
    }

    pozycje_raw = _l(surowe_dane.get("pozycje"))
    oczyszczone_pozycje = []
    for p in pozycje_raw:
        if not isinstance(p, dict):
            continue
        oczyszczone_pozycje.append({
            "nazwa": str(p.get("nazwa") or "POZYCJA BEZ NAZWY").strip(),
            "kod": str(p.get("kod") or "").strip(),
            "vat": str(p.get("vat") or "5").strip(),
            "jm": str(p.get("jm") or "kg").strip(),
            "ilosc": str(p.get("ilosc") or "1").strip(),
            "cena_netto": str(p.get("cena_netto") or "0.00").strip(),
            "wartosc_netto": str(p.get("wartosc_netto") or "0.00").strip()
        })

    if not oczyszczone_pozycje:
        raise ValueError("Model nie odnalazł żadnych pozycji towarowych na dokumencie.")

    dane["pozycje"] = oczyszczone_pozycje
    dane["suma_netto_dokument"] = str(surowe_dane.get("suma_netto_dokument") or "0.00").strip()
    dane["stawki"] = [s for s in _l(surowe_dane.get("stawki")) if isinstance(s, dict)]
    dane["do_zaplaty"] = str(surowe_dane.get("do_zaplaty") or "0.00").strip()
    return dane

def generuj_tekst_edi(dane: dict) -> str:
    pozycje = dane.get("pozycje", [])
    wyst = dane.get("wystawca", {})
    nip_wyst = re.sub(r"\D", "", str(wyst.get("nip", "")))

    linie = [
        "TypPolskichLiter:LA",
        "TypDok:PZ",
        f"NrDok:{dane.get('nr_dok', '')}",
        f"Data:{dane.get('data', datetime.now().strftime('%d.%m.%Y'))}",
        "Magazyn:MAGAZYN",
        f"NIPWystawcy:{nip_wyst}",
        f"IloscLinii:{len(pozycje)}"
    ]

    for poz in pozycje:
        nazwa = str(poz.get("oryg_nazwa", poz.get("nazwa", ""))).strip().upper()
        kod_glowny = str(poz.get("kod_dopasowany") or poz.get("kod") or "").strip()

        vat_raw = str(poz.get("vat", "5")).replace("%", "").replace(",", ".").strip()
        try:
            vat = str(int(float(vat_raw)))
        except Exception:
            vat = "5"

        jm = str(poz.get("jm", "kg")).lower().strip()
        ilosc_val = parsuj_kwote(poz.get("ilosc", "1"))
        cena_val = parsuj_kwote(poz.get("cena_netto", "0.00"))
        wartosc_val = parsuj_kwote(poz.get("wartosc_netto", "0.00"))

        ilosc = f"{ilosc_val:.3f}".rstrip('0').rstrip('.') if ilosc_val % 1 != 0 else str(int(ilosc_val))
        cena = f"n{cena_val:.2f}"
        wartosc = f"n{wartosc_val:.2f}"

        linia = (
            f"Linia:Nazwa{{{nazwa}}}Kod{{{kod_glowny}}}Vat{{{vat}}}Jm{{{jm}}}"
            f"Ilosc{{{ilosc}}}Cena{{{cena}}}Wartosc{{{wartosc}}}"
        )
        linie.append(linia)

    return "\n".join(linie) + "\n"

def weryfikuj_sumy_netto(dane: dict) -> tuple[str, str]:
    pozycje = dane.get("pozycje", [])
    suma_obliczona = sum(parsuj_kwote(p.get("wartosc_netto")) for p in pozycje)

    suma_doc_raw = dane.get("suma_netto_dokument", "")
    suma_odczytana = parsuj_kwote(suma_doc_raw)

    if suma_odczytana == 0.0:
        stawki = dane.get("stawki", [])
        suma_odczytana = sum(parsuj_kwote(s.get("suma_netto")) for s in stawki)

    if suma_odczytana <= 0.0:
        return "BRAK_DANYCH", f"Suma pozycji: {suma_obliczona:.2f} zł (brak sumy do porównania)"

    roznica = abs(suma_obliczona - suma_odczytana)
    if roznica > 0.15:
        return "BLAD", f"⚠️ Niezgodność! Pozycje: {suma_obliczona:.2f} zł | Z dokumentu: {suma_odczytana:.2f} zł"

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

def dopasuj_wszystkie_pozycje_w_tle(dane: dict, uzywa_bazy: bool, sciezka_bazy: str) -> tuple[list[dict], dict, str, str]:
    baza = wczytaj_baze_pcmarket(sciezka_bazy) if uzywa_bazy else []
    indeks = _CACHE_BAZY.get("indeks") or (zbuduj_indeks_nazw(baza) if baza else {})
    mapowania = wczytaj_baze_mapowan()

    for poz in dane.get("pozycje", []):
        nazwa = str(poz.get("nazwa", "")).strip().upper()
        kod_faktura = str(poz.get("kod", "")).strip()
        kod_dop, _, pewnosc = dopasuj_towar_z_bazy(
            nazwa, kod_faktura, baza, uzywa_bazy, mapowania=mapowania, indeks=indeks
        )
        poz["oryg_nazwa"] = nazwa
        poz["kod_dopasowany"] = kod_dop
        poz["pewnosc"] = pewnosc

    stan_sum, info_sum = weryfikuj_sumy_netto(dane)
    return baza, dane, stan_sum, info_sum

# --- GŁÓWNA APLIKACJA ---
async def main(page: ft.Page):
    page.title = "ocrLmm Mobilny"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    konfig = wczytaj_konfiguracje()
    ostatnia_sciezka_edi = {"sciezka": None}
    aktualne_zdjecie = {"sciezka": None}
    poprzedni_dialog = {"dlg": None}
    blokady = {"analiza": False, "obrot": False}

    def bezpiecznie_otworz_dialog(dlg):
        try:
            page.pop_dialog()
            page.update()
        except Exception:
            pass
        try:
            page.show_dialog(dlg)
        except RuntimeError:
            try:
                page.pop_dialog()
                page.update()
            except Exception:
                pass
            page.show_dialog(dlg)
        page.update()

    tresc_bledu = ft.Text("", size=14)
    tytul_bledu = ft.Text("Komunikat", weight=ft.FontWeight.BOLD)

    def zamknij_alert(e):
        page.pop_dialog()
        if poprzedni_dialog["dlg"]:
            odtworz = poprzedni_dialog["dlg"]
            poprzedni_dialog["dlg"] = None
            bezpiecznie_otworz_dialog(odtworz)

    dlg_alert = ft.AlertDialog(
        modal=True,
        title=tytul_bledu,
        content=tresc_bledu,
        actions=[ft.Button(content=ft.Text("Rozumiem"), on_click=zamknij_alert)]
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

    async def kopiuj_do_schowka(e):
        tekst = "\n".join([c.value for c in konsola_logow.controls])
        await page.set_clipboard_async(tekst)
        status_text.value = "Skopiowano logi do schowka telefonu."
        status_text.color = ft.Colors.GREEN_ACCENT
        page.update()

    async def udostepnij_plik_logow(e):
        tekst = "\n".join([c.value for c in konsola_logow.controls])
        sciezka_logow = os.path.join(KATALOG_DANYCH, f"logi_ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        try:
            with open(sciezka_logow, "w", encoding="utf-8") as f:
                f.write(tekst)
            if hasattr(serwis_udostepniania, "share_files"):
                try:
                    await serwis_udostepniania.share_files([ft.ShareFile.from_path(sciezka_logow)], text="Logi ocrLmm")
                except Exception:
                    await serwis_udostepniania.share_files([sciezka_logow])
            status_text.value = "Otwarto menu udostępniania logów."
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
            ft.Button("Kopiuj do schowka", on_click=kopiuj_do_schowka),
            ft.Button("Udostępnij plik", on_click=udostepnij_plik_logow),
            ft.Button("Zamknij", on_click=lambda e: page.pop_dialog())
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

        aktualne_zdjecie["sciezka"] = None
        ostatnia_sciezka_edi["sciezka"] = None
        podglad_obrazu.src = PUSTY_OBRAZ
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        wiersz_obrotu.visible = False
        btn_ponow.visible = False
        btn_udostepnij.visible = False
        ustaw_stan_przycisku_foto(False)

        status_text.value = f"Wyczyszczono katalog (usunięto {usuniete_pliki} plików). Stan zresetowany."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    dlg_potwierdz_czyszczenie = ft.AlertDialog(
        modal=True,
        title=ft.Text("⚠️ Potwierdzenie usunięcia"),
        content=ft.Text(
            "Czy na pewno chcesz usunąć wszystkie pliki robocze (EDI i zdjęcia)?\n\n"
            "Baza towarowa i konfiguracja pozostaną nienaruszone."
        ),
        actions=[
            ft.Button(content=ft.Text("Anuluj"), on_click=lambda e: page.pop_dialog()),
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
        mapa[wz] = kd
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
        actions=[ft.Button(content=ft.Text("Zamknij"), on_click=lambda e: page.pop_dialog())]
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
                if oryginalna_nazwa in mapa:
                    del mapa[oryginalna_nazwa]
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
                nazwa_dopasowana = mapa_kod_nazwa.get(kod, "Pozycja zdefiniowana ręcznie")
                if pewnosc == "ROZMYTE":
                    tekst_kodu = ft.Text(f"Towar: {nazwa_dopasowana} (Kod: {kod}) [⚠️ Sprawdź]", size=12, color=ft.Colors.AMBER_300)
                else:
                    tekst_kodu = ft.Text(f"Towar: {nazwa_dopasowana} (Kod: {kod})", size=12, color=ft.Colors.GREEN_400)
            else:
                tekst_kodu = ft.Text("BRAK DOPASOWANIA (Wybierz kod!)", size=12, color=ft.Colors.RED_400, weight=ft.FontWeight.BOLD)

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
                        tooltip="Rozparuj kod",
                        icon_color=ft.Colors.RED_400,
                        on_click=lambda e, idx=i: klik_usun_przypisanie(idx)
                    )
                )

            lista_pozycji_weryfikacji.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(nazwa, weight=ft.FontWeight.BOLD, size=13),
                            tekst_kodu
                        ], expand=True),
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
        info_sumy = stan_weryfikacji["info_sumy"]
        status_sum = stan_weryfikacji["status_sum"]
        uzywa_bazy = stan_weryfikacji["uzywa_bazy"]

        puste_kody = [p.get("oryg_nazwa") for p in dane.get("pozycje", []) if not (p.get("kod_dopasowany") or p.get("kod"))]
        if puste_kody:
            pokaz_okno_bledu(
                "Nieprzypisane towary",
                f"Wszystkie pozycje muszą posiadać przypisany kod PC-Market przed wygenerowaniem EDI. Brakuje kodów dla: {len(puste_kody)} pozycji.",
                powrot_do=dlg_weryfikacja
            )
            return

        dopisz_log("Generowanie struktury pliku EDI z potwierdzonymi kodami...")
        tresc_edi = generuj_tekst_edi(dane)

        nr_dok = "".join(c for c in dane.get("nr_dok", "faktura") if c.isalnum() or c in ("-", "_"))
        nazwa_pliku = f"edi_{nr_dok}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        sciezka_edi = os.path.join(KATALOG_DANYCH, nazwa_pliku)

        with open(sciezka_edi, "w", encoding="windows-1250", errors="replace") as f:
            f.write(tresc_edi)

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

        aktualne_zdjecie["sciezka"] = None
        podglad_obrazu.src = PUSTY_OBRAZ
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        wiersz_obrotu.visible = False
        btn_ponow.visible = False
        ustaw_stan_przycisku_foto(False)
        page.update()

    async def klik_zatwierdz_weryfikacje(e):
        page.pop_dialog()
        page.update()
        await zapisz_edi_i_zakoncz()

    def klik_anuluj_weryfikacje(e):
        page.pop_dialog()
        status_text.value = "Anulowano generowanie EDI. Możesz ponownie uruchomić weryfikację lub wybrać inne zdjęcie."
        status_text.color = ft.Colors.ORANGE_ACCENT
        btn_foto.disabled = False
        btn_aparat.disabled = False
        btn_ponow.visible = True
        page.update()

    dlg_weryfikacja = ft.AlertDialog(
        modal=True,
        title=ft.Text("Weryfikacja kodów z faktury"),
        content=ft.Container(
            content=ft.Column([
                ft.Text("Zielony: pewne | Żółty: rozmyte | Czerwony: brak", size=12, color=ft.Colors.GREY_400),
                lista_pozycji_weryfikacji
            ], tight=True),
            width=380,
            height=450
        ),
        actions=[
            ft.Button("Wróć / Anuluj", color=ft.Colors.RED_400, on_click=klik_anuluj_weryfikacje),
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
            nazwa_porownanie = usun_diakrytyki(nazwa_towaru.upper())

            czy_pasuje = True
            for frag in fragmenty:
                if frag not in nazwa_porownanie and frag not in kod_towaru:
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
                mapa[oryginalna_nazwa] = kod
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
        actions=[ft.Button("Wróć do weryfikacji", on_click=zamknij_wyszukiwarke)]
    )

    # --- USTAWIENIA SIECIOWE ---
    chk_cloud = ft.Checkbox(label="Użyj chmury (Google Gemini)", value=konfig.get("use_cloud", True))

    dd_rozdzielczosc = ft.Dropdown(
        label="Jakość skanu (Szybkość vs Tokeny)",
        options=[
            ft.dropdown.Option(key="1800", text="1800px (Najlepszy odczyt OCR)"),
            ft.dropdown.Option(key="1400", text="1400px (Kompromis)"),
            ft.dropdown.Option(key="1024", text="1024px (Szybciej, ryzyko małego druku)")
        ],
        value=str(konfig.get("image_resolution", 1800)),
        dense=True
    )

    chk_db_matching = ft.Checkbox(label="Dopasowuj do bazy PC-Market", value=konfig.get("use_db_matching", True))
    txt_gemini_key = ft.TextField(label="Klucz Google AI Studio API", value=konfig.get("gemini_api_key", ""), password=True, can_reveal_password=True, dense=True)
    txt_gemini_model = ft.TextField(label="Model Google AI (np. gemini-3.6-flash)", value=konfig.get("gemini_model", "gemini-3.6-flash"), dense=True)
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

    wiersz_wyboru_modelu = ft.Row([dd_local_model, ft.IconButton(icon=ft.Icons.DELETE, icon_color=ft.Colors.RED_400, on_click=klik_usun_model)])
    wiersz_dodawania_modelu = ft.Row([txt_dodaj_model, ft.IconButton(icon=ft.Icons.ADD_CIRCLE, icon_color=ft.Colors.GREEN_400, on_click=klik_dodaj_model)])
    txt_local_api_key = ft.TextField(label="Klucz API serwera lokalnego (opcjonalnie)", value=konfig.get("local_api_key", ""), password=True, can_reveal_password=True, dense=True)

    async def klik_budzenie_wol(e):
        target_mac = txt_mac.value.strip()
        target_ip = txt_ip.value.strip() or "192.168.1.154"
        if not target_mac:
            pokaz_okno_bledu("Błąd WoL", "Podaj adres MAC serwera w konfiguracji.", powrot_do=dlg_ustawienia)
            return

        try:
            loop = asyncio.get_running_loop()
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
            pliki = await picker_bazy.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["txt"])
            if pliki and len(pliki) > 0:
                sciezka_zrodlowa = pliki[0].path
                if sciezka_zrodlowa:
                    oryginalna_nazwa = os.path.basename(sciezka_zrodlowa)
                    if not wczytaj_baze_pcmarket(sciezka_zrodlowa):
                        pokaz_okno_bledu(
                            "Nieprawidłowy plik bazy",
                            f"W pliku {oryginalna_nazwa} nie znaleziono towarów. Wymagany układ kolumn z tabulatorem (kolumna 1: nazwa, kolumna 3: kod).",
                            powrot_do=dlg_ustawienia
                        )
                        return

                    docelowa_sciezka = os.path.join(KATALOG_DANYCH, oryginalna_nazwa)
                    try:
                        shutil.copyfile(sciezka_zrodlowa, docelowa_sciezka)
                    except Exception:
                        docelowa_sciezka = sciezka_zrodlowa

                    konfig["baza_file_path"] = docelowa_sciezka
                    odswiez_status_bazy()
                    status_text.value = f"Wczytano bazę ({oryginalna_nazwa}). Kliknij 'Zapisz', aby utrwalić."
                    status_text.color = ft.Colors.CYAN_ACCENT
                    page.update()
        except Exception as err_baza:
            pokaz_okno_bledu("Błąd wczytywania bazy", str(err_baza), powrot_do=dlg_ustawienia)

    picker_mapowan = ft.FilePicker()
    page.services.append(picker_mapowan)

    async def wybierz_plik_mapowan(e):
        try:
            pliki = await picker_mapowan.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["json"])
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
                    status_text.value = f"Wczytano reguły ({oryginalna_nazwa}): {len(nowe_reguly)} z pliku, łącznie: {len(polaczone)}."
                    status_text.color = ft.Colors.CYAN_ACCENT
                    page.update()
        except Exception as err_mapa:
            pokaz_okno_bledu("Błąd mapowań", str(err_mapa), powrot_do=dlg_ustawienia)

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
            pokaz_okno_bledu("Brak plików", "Nie znaleziono bazy TXT ani mapowań JSON.", powrot_do=dlg_ustawienia)
            return

        try:
            if hasattr(serwis_udostepniania, "share_files"):
                try:
                    await serwis_udostepniania.share_files(pliki_share, text="Baza towarowa i reguły (ocrLmm)")
                except Exception:
                    await serwis_udostepniania.share_files(pliki_sciezki)
        except Exception as err:
            dopisz_log(f"Błąd eksportu kodów: {err}", ft.Colors.RED)
            pokaz_okno_bledu("Błąd udostępniania", str(err), powrot_do=dlg_ustawienia)

    kontener_baza_pcmarket = ft.Column(
        [
            ft.Text("Baza towarowa PC-Market:", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
            chk_db_matching,
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN), ft.Text("Wybierz plik bazy (.txt)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.AMBER_900, color=ft.Colors.WHITE), on_click=wybierz_plik_bazy),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE), ft.Text("Wgraj plik mapowań (.json)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.DEEP_ORANGE_900, color=ft.Colors.WHITE), on_click=wybierz_plik_mapowan),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.EDIT_NOTE), ft.Text("Zarządzaj powiązaniami")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE), on_click=otworz_okno_bazy_recznej),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.IOS_SHARE), ft.Text("Udostępnij kody (TXT + JSON)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.DEEP_PURPLE_800, color=ft.Colors.WHITE), on_click=udostepnij_bazy_kody),
            lbl_status_bazy
        ],
        spacing=6
    )

    kontener_gemini = ft.Column([ft.Text("Konfiguracja Google Gemini:", weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300), txt_gemini_key, txt_gemini_model], spacing=8, visible=chk_cloud.value)
    kontener_lokalny = ft.Column([ft.Text("Konfiguracja serwera lokalnego:", weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_300), txt_mac, txt_ip, txt_port, ft.Text("Zarządzanie modelami LM Studio:", size=12, color=ft.Colors.GREY_400), wiersz_wyboru_modelu, wiersz_dodawania_modelu, txt_local_api_key, btn_wol_ustawienia], spacing=8, visible=not chk_cloud.value)

    def przelacz_profil(e):
        kontener_gemini.visible = chk_cloud.value
        kontener_lokalny.visible = not chk_cloud.value
        page.update()

    chk_cloud.on_change = przelacz_profil

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
        status_text.value = "Ustawienia zostały pomyślnie zapisane."
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
            ft.Button(content=ft.Text("Anuluj"), on_click=lambda e: page.pop_dialog()),
            ft.Button(content=ft.Text("Zapisz"), style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE), on_click=zapisz_i_zamknij_dialog)
        ]
    )

    def otworz_ustawienia(e):
        bezpiecznie_otworz_dialog(dlg_ustawienia)

    # --- APARAT (FLET-CAMERA Z PEŁNĄ INICJALIZACJĄ) ---
    kamera_obiektyw = fc.Camera(expand=True)
    page.services.append(kamera_obiektyw)

    def on_foto_zrobione(e):
        if e.data:
            page.pop_dialog()
            ustaw_nowy_obraz(e.data)

    if hasattr(kamera_obiektyw, "on_image_captured"):
        kamera_obiektyw.on_image_captured = on_foto_zrobione

    async def klik_migawka(e):
        try:
            wynik = kamera_obiektyw.take_picture()
            if hasattr(wynik, "__await__"):
                wynik = await wynik
            if isinstance(wynik, str):
                page.pop_dialog()
                ustaw_nowy_obraz(wynik)
        except Exception as err:
            dopisz_log(f"Błąd migawki: {err}", ft.Colors.RED)

    dlg_aparat = ft.AlertDialog(
        modal=True,
        title=ft.Text("Zrób zdjęcie faktury"),
        content=ft.Container(content=kamera_obiektyw, width=350, height=480),
        actions=[
            ft.FloatingActionButton(icon=ft.Icons.CAMERA, on_click=klik_migawka),
            ft.Button("Anuluj", on_click=lambda e: page.pop_dialog())
        ],
        actions_alignment=ft.MainAxisAlignment.CENTER
    )

    async def otworz_aparat(e):
        try:
            bezpiecznie_otworz_dialog(dlg_aparat)
            page.update()

            kamery = []
            if hasattr(fc, "get_cameras"):
                kamery = await fc.get_cameras()
            elif hasattr(kamera_obiektyw, "get_cameras"):
                res = kamera_obiektyw.get_cameras()
                kamery = await res if hasattr(res, "__await__") else res

            if not kamery:
                dopisz_log("Brak wykrytych kamer w urządzeniu.", ft.Colors.RED)
                return

            wybrana_kamera = kamery[0]
            for cam in kamery:
                kierunek = str(getattr(cam, "lens_facing", "") or getattr(cam, "lens", "")).lower()
                if "back" in kierunek:
                    wybrana_kamera = cam
                    break

            preset = getattr(fc.ResolutionPreset, "HIGH", "high") if hasattr(fc, "ResolutionPreset") else "high"
            inicjalizacja = kamera_obiektyw.initialize(wybrana_kamera, preset)
            if hasattr(inicjalizacja, "__await__"):
                await inicjalizacja

            page.update()
            dopisz_log("Kamera zainicjalizowana pomyślnie.", ft.Colors.GREEN)
        except ft.FletUnsupportedPlatformException:
            status_text.value = "Aparat działa wyłącznie na telefonie (Android)."
            status_text.color = ft.Colors.AMBER_ACCENT
            page.update()
        except Exception as err:
            dopisz_log(f"Błąd inicjalizacji kamery: {err}", ft.Colors.RED)

    # --- UI PODSTAWOWE I AKCJE ---
    status_text = ft.Text("Wybierz zdjęcie z galerii lub zrób zdjęcie aparatem.", size=13, color=ft.Colors.GREEN_ACCENT, text_align=ft.TextAlign.CENTER)
    pasek_postepu = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_ACCENT)
    podglad_obrazu = ft.Image(src=PUSTY_OBRAZ, visible=False, fit="contain", height=240)

    def ustaw_stan_przycisku_foto(czy_ma_zdjecie: bool):
        if czy_ma_zdjecie:
            ikona_btn_foto.name = ft.Icons.SEND
            tekst_btn_foto.value = "Wyślij do analizy"
            btn_foto.style.bgcolor = ft.Colors.BLUE_700
            btn_aparat.visible = False
        else:
            ikona_btn_foto.name = ft.Icons.PHOTO_LIBRARY
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
        podglad_obrazu.src = nowa_sciezka
        podglad_obrazu.visible = True
        btn_usun_zdjecie.visible = True
        wiersz_obrotu.visible = True
        ustaw_stan_przycisku_foto(True)
        status_text.value = "Zdjęcie gotowe. Sprawdź orientację i kliknij 'Wyślij do analizy'."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    def usun_wybrane_zdjecie(e):
        aktualne_zdjecie["sciezka"] = None
        podglad_obrazu.src = PUSTY_OBRAZ
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        btn_udostepnij.visible = False
        btn_ponow.visible = False
        wiersz_obrotu.visible = False
        ustaw_stan_przycisku_foto(False)
        status_text.value = "Zdjęcie usunięte."
        status_text.color = ft.Colors.GREEN_ACCENT
        page.update()

    btn_usun_zdjecie = ft.Button(content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE), ft.Text("Usuń wybrane zdjęcie")], alignment=ft.MainAxisAlignment.CENTER), visible=False, style=ft.ButtonStyle(color=ft.Colors.RED_300), on_click=usun_wybrane_zdjecie)

    async def obroc_zdjecie(kierunek: str):
        if blokady["obrot"]:
            return
        sciezka = aktualne_zdjecie["sciezka"]
        if not sciezka or not os.path.exists(sciezka):
            return

        blokady["obrot"] = True
        btn_obroc_lewo.disabled = True
        btn_obroc_prawo.disabled = True
        page.update()

        try:
            loop = asyncio.get_running_loop()
            nowa_sciezka = os.path.join(KATALOG_DANYCH, f"img_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg")

            def wykonaj_obrot():
                with Image.open(sciezka) as im:
                    im = ImageOps.exif_transpose(im)
                    obrocony = im.transpose(Image.Transpose.ROTATE_90 if kierunek == "lewo" else Image.Transpose.ROTATE_270)
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
            podglad_obrazu.src = nowa_sciezka
            status_text.value = f"Obrócono zdjęcie w {kierunek}."
            status_text.color = ft.Colors.CYAN_ACCENT
        except Exception as err_rot:
            status_text.value = f"Błąd obracania: {err_rot}"
            status_text.color = ft.Colors.RED_ACCENT
        finally:
            blokady["obrot"] = False
            btn_obroc_lewo.disabled = False
            btn_obroc_prawo.disabled = False
            page.update()

    btn_obroc_lewo = ft.Button(content=ft.Row([ft.Icon(ft.Icons.ROTATE_LEFT), ft.Text("W lewo")], alignment=ft.MainAxisAlignment.CENTER), expand=True, on_click=lambda e: obroc_zdjecie("lewo"))
    btn_obroc_prawo = ft.Button(content=ft.Row([ft.Icon(ft.Icons.ROTATE_RIGHT), ft.Text("W prawo")], alignment=ft.MainAxisAlignment.CENTER), expand=True, on_click=lambda e: obroc_zdjecie("prawo"))
    wiersz_obrotu = ft.Row([btn_obroc_lewo, btn_obroc_prawo], visible=False, spacing=10)

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
                    await serwis_udostepniania.share_files([ft.ShareFile.from_path(sciezka)], text="Plik EDI dla PC-Market")
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

    async def przetworz_plik(sciezka_obrazu):
        if blokady["analiza"]:
            return
        if not sciezka_obrazu or not os.path.exists(sciezka_obrazu):
            return

        blokady["analiza"] = True
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

            # --- SPRAWDZENIE I BUDZENIE SERWERA LOKALNEGO ---
            if not uzywa_chmury:
                ip_lokalne = aktualny_konfig.get("local_ip", "192.168.1.154").strip()
                port_str = aktualny_konfig.get("local_port", "1234").strip()
                mac_adres = aktualny_konfig.get("wol_mac", "").strip()
                port_lokalny = int(port_str) if port_str.isdigit() else 1234

                dopisz_log(f"Test połączenia z LM Studio ({ip_lokalne}:{port_lokalny})...")
                serwer_zyje = await sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0)

                if not serwer_zyje:
                    if not mac_adres:
                        raise ConnectionRefusedError(f"Serwer {ip_lokalne}:{port_lokalny} jest wyłączony, a brak adresu MAC do budzenia WoL.")

                    dopisz_log("Serwer nie odpowiada. Wysyłanie Wake-on-LAN...", ft.Colors.AMBER)
                    try:
                        await loop.run_in_executor(None, wyslij_wol, mac_adres, ip_lokalne)
                    except Exception as e_wol:
                        dopisz_log(f"Błąd wysyłania WoL: {e_wol}", ft.Colors.RED)

                    maks_czas = 150
                    krok = 10
                    uplynelo = 0
                    while uplynelo < maks_czas:
                        status_text.value = f"Oczekiwanie na uruchomienie LM Studio... ({uplynelo}/{maks_czas}s)"
                        page.update()
                        await asyncio.sleep(krok)
                        uplynelo += krok

                        if uplynelo % 30 == 0:
                            try:
                                await loop.run_in_executor(None, wyslij_wol, mac_adres, ip_lokalne)
                            except Exception:
                                pass

                        if await sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0):
                            serwer_zyje = True
                            dopisz_log(f"Serwer gotowy po {uplynelo}s!", ft.Colors.GREEN)
                            break

                    if not serwer_zyje:
                        raise TimeoutError(f"Serwer {ip_lokalne} nie uruchomił się w czasie {maks_czas}s.")

            dopisz_log("Kompresja i przygotowanie obrazu...")
            wymiar_obrazu = aktualny_konfig.get("image_resolution", 1800)
            base64_image = await loop.run_in_executor(None, kompresuj_do_base64, sciezka_obrazu, wymiar_obrazu)

            prompt = (
                "Jesteś precyzyjnym systemem OCR do faktur i dokumentów magazynowych PZ. "
                "Przepisz DOKŁADNIE dane ze zdjęcia. Zwróć TYLKO i WYŁĄCZNIE czysty obiekt JSON bez znaczników markdown:\n"
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
                dopisz_log("Wysyłanie zapytania do Google Gemini API...")
                klucz = aktualny_konfig.get("gemini_api_key", "").strip()
                pelny_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                naglowki = {"Content-Type": "application/json", "Authorization": f"Bearer {klucz}"}
                cialo_zapytania = {
                    "model": model_gemini,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
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
                        {"role": "system", "content": "Jesteś precyzyjnym systemem OCR. Zwracasz TYLKO obiekt JSON bez markdownu."},
                        {"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 8192,
                    "chat_template_kwargs": {"enable_thinking": False}
                }

            odpowiedz = None
            timeout_cfg = httpx.Timeout(10.0, read=300.0)
            async with httpx.AsyncClient(timeout=timeout_cfg, verify=True) as client:
                for proba in range(4):
                    dopisz_log(f"Odczytywanie danych przez AI (próba {proba + 1}/4)...")
                    odpowiedz = await client.post(pelny_url, headers=naglowki, json=cialo_zapytania)
                    if odpowiedz.status_code in (429, 503):
                        if proba < 3:
                            opoznienie = 2.0 * (2 ** proba)
                            dopisz_log(f"Serwer zajęty ({odpowiedz.status_code}). Ponowienie za {opoznienie:.1f}s...", ft.Colors.AMBER)
                            await asyncio.sleep(opoznienie)
                            continue
                    odpowiedz.raise_for_status()
                    break

            dane_odp = odpowiedz.json()
            wybor = dane_odp["choices"][0]
            odp_tekst = (wybor.get("message", {}).get("content") or "").strip()

            dopasowanie = re.search(r'\{.*\}', odp_tekst, re.DOTALL)
            surowy_json = json.loads(dopasowanie.group(0) if dopasowanie else odp_tekst)
            dane_zweryfikowane = oczysc_odpowiedz_llm(surowy_json)

            dopisz_log("Dopasowywanie pozycji do bazy PC-Market w osobnym wątku...")
            sciezka_bazy = pobierz_aktualna_sciezke_bazy(aktualny_konfig)
            baza_towarowa, dane_zmapowane, stan_sum, info_sum = await loop.run_in_executor(
                None, dopasuj_wszystkie_pozycje_w_tle, dane_zweryfikowane, uzywa_bazy, sciezka_bazy
            )

            stan_weryfikacji["dane"] = dane_zmapowane
            stan_weryfikacji["baza"] = baza_towarowa
            stan_weryfikacji["uzywa_bazy"] = uzywa_bazy
            stan_weryfikacji["status_sum"] = stan_sum
            stan_weryfikacji["info_sumy"] = info_sum
            stan_weryfikacji["indeks_edytowany"] = -1

            dopisz_log("Weryfikacja gotowa. Otwieranie listy kontrolnej.", ft.Colors.GREEN)
            status_text.value = "Sprawdź poprawność kodów w oknie weryfikacji."
            status_text.color = ft.Colors.CYAN_ACCENT
            pasek_postepu.visible = False
            page.update()

            odswiez_weryfikacje()
            bezpiecznie_otworz_dialog(dlg_weryfikacja)

        except httpx.HTTPStatusError as http_err:
            status = http_err.response.status_code
            tresc = http_err.response.text[:350]
            dopisz_log(f"Błąd HTTP {status}: {tresc}", ft.Colors.RED)
            if status in (400, 401, 403) and ("API_KEY" in tresc or "INVALID_ARGUMENT" in tresc):
                pokaz_okno_bledu("Błąd autoryzacji", "Klucz API jest nieprawidłowy. Sprawdź ustawienia.")
            elif status == 429:
                pokaz_okno_bledu("Limit zapytań", "Przekroczono limit zapytań API. Odczekaj chwilę.")
            elif status >= 500:
                pokaz_okno_bledu("Błąd serwera", f"Serwer AI zwrócił kod {status}. Spróbuj ponownie za chwilę.")
            else:
                pokaz_okno_bledu("Błąd zapytania HTTP", f"Status: {status}\n{tresc}")
        except httpx.TimeoutException:
            dopisz_log("Przekroczono limit czasu oczekiwania na odpowiedź serwera (Timeout).", ft.Colors.RED)
            pokaz_okno_bledu("Limit czasu", "Model nie odpowiedział w wyznaczonym czasie.")
        except Exception as err:
            nazwa = type(err).__name__
            dopisz_log(f"Wyjątek {nazwa}: {err}", ft.Colors.RED)
            pokaz_okno_bledu(f"Błąd ({nazwa})", str(err))
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

    picker_zdjecia = ft.FilePicker()
    page.services.append(picker_zdjecia)

    async def otworz_galerie():
        try:
            pliki = await picker_zdjecia.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            if pliki and len(pliki) > 0 and pliki[0].path:
                ustaw_nowy_obraz(pliki[0].path)
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
        content=ft.Row([ikona_btn_foto, tekst_btn_foto], alignment=ft.MainAxisAlignment.CENTER),
        height=55, expand=True,
        style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
        on_click=klik_glowny_przycisk
    )

    btn_aparat = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Zrób zdjęcie")], alignment=ft.MainAxisAlignment.CENTER),
        height=55, expand=True,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
        on_click=otworz_aparat
    )

    btn_ponow = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.REFRESH), ft.Text("Ponów analizę")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False, height=48,
        style=ft.ButtonStyle(bgcolor=ft.Colors.AMBER_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
        on_click=lambda e: przetworz_plik(aktualne_zdjecie["sciezka"])
    )

    btn_udostepnij = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.SHARE), ft.Text("Udostępnij plik EDI")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False, height=48,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
        on_click=lambda e: udostepnij_plik(ostatnia_sciezka_edi["sciezka"])
    )

    pasek_tytulu = ft.Row(
        [
            ft.Column([
                ft.Text("ocrLmm Mobile", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                ft.Text("Skaner PZ do EDI (PC-Market)", size=12, color=ft.Colors.GREY_400)
            ], spacing=2),
            ft.Row([
                ft.IconButton(icon=ft.Icons.STORAGE, tooltip="Baza i powiązania", on_click=otworz_okno_bazy_recznej),
                ft.IconButton(icon=ft.Icons.TERMINAL, tooltip="Logi systemowe", on_click=otworz_konsole),
                ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="Ustawienia", on_click=otworz_ustawienia)
            ], spacing=0)
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
    )

    btn_wyczysc_katalog = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.CLEANING_SERVICES, size=18), ft.Text("Wyczyść katalog roboczy", size=12)], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
        expand=True,
        on_click=lambda e: bezpiecznie_otworz_dialog(dlg_potwierdz_czyszczenie)
    )

    odswiez_status_bazy()

    page.add(
        ft.Column(
            [
                pasek_tytulu,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                ft.Row([btn_foto, btn_aparat], spacing=10),
                pasek_postepu,
                status_text,
                btn_ponow,
                btn_udostepnij,
                podglad_obrazu,
                wiersz_obrotu,
                btn_usun_zdjecie,
                ft.Divider(height=16, color=ft.Colors.GREY_800),
                ft.Row([btn_wyczysc_katalog], spacing=10)
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=10
        )
    )

if __name__ == "__main__":
    ft.run(main)
