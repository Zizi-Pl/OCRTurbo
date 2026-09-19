import flet_camera as fc
import flet_permission_handler as fph
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
import httpx
from datetime import datetime
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from thefuzz import process, fuzz

KATALOG_DANYCH = os.getenv("FLET_APP_STORAGE_DATA", os.getcwd())
os.makedirs(KATALOG_DANYCH, exist_ok=True)

CONFIG_FILE = os.path.join(KATALOG_DANYCH, "ocrlmm_mobile_config.json")
DOMYSLNA_BAZA_FILE = os.path.join(KATALOG_DANYCH, "WĘDLINA.txt")
MAPA_FILE = os.path.join(KATALOG_DANYCH, "mapowania_towarow.json")

# ROLE PLIKÓW:
#  * WĘDLINA.txt (baza PC-Market) - KATALOG towarów z kasy: "nazwa w PC-Market" -> kod wewnętrzny.
#    Tylko do odczytu; aplikacja go nie zmienia, można go podmienić nowym eksportem.
#  * mapowania_towarow.json - PAMIĘĆ użytkownika: "nazwa tak jak jest na fakturze" -> kod.
#    Powstaje z ręcznych poprawek (lupa w weryfikacji, okno "Powiązania"). Ma pierwszeństwo
#    przed dopasowaniem do katalogu i nigdy nie jest z nim mieszana.

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
    # Zapis atomowy: przerwany zapis nie zostawi uciętego pliku (który zostałby potem odczytany jako "pusty").
    tymczasowy = MAPA_FILE + ".tmp"
    try:
        with open(tymczasowy, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=4, ensure_ascii=False)
        os.replace(tymczasowy, MAPA_FILE)
    except Exception as e:
        print(f"Błąd zapisu mapowań: {e}")

def wczytaj_plik_mapowan_z_walidacja(sciezka: str) -> dict:
    """Wczytuje zewnętrzny plik reguł i sprawdza, czy ma postać {"NAZWA": "KOD"}."""
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

# --- KONFIGURACJA I BAZA ---
def wczytaj_konfiguracje() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                dane = json.load(f)
                konf = DOMYSLNA_KONFIGURACJA.copy()
                konf.update(dane)
                return konf
        except Exception:
            return DOMYSLNA_KONFIGURACJA.copy()
    return DOMYSLNA_KONFIGURACJA.copy()

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
    towary_dict = {}
    if not sciezka:
        konf = wczytaj_konfiguracje()
        sciezka = pobierz_aktualna_sciezke_bazy(konf)

    if os.path.exists(sciezka):
        # UTF-8 (z ewentualnym BOM) musi być pierwszy: cp1250 przyjmuje prawie każdy bajt,
        # więc plik UTF-8 "przeszedłby" jako cp1250 z krzaczkami zamiast polskich liter.
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

    # Tylko katalog z pliku TXT. Ręczne reguły (JSON) są obsługiwane osobno w dopasuj_towar_z_bazy.
    return [{"nazwa": k, "kod_wew": v} for k, v in towary_dict.items()]

def normalizuj_nazwe(tekst: str) -> str:
    t = tekst.upper().strip()
    t = re.sub(r"[.,/\\-_]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def zbuduj_indeks_nazw(baza: list[dict]) -> dict:
    """Buduje indeks 'znormalizowana nazwa -> kod' z katalogu PC-Market (rozwija warianty po '/')."""
    mapa_nazw = {}
    for t in baza:
        kod = t["kod_wew"]
        surowa_nazwa = t["nazwa"]
        
        czesci = surowa_nazwa.split("/")
        trzon = normalizuj_nazwe(czesci[0])
        
        if trzon:
            if trzon not in mapa_nazw:
                mapa_nazw[trzon] = kod
            
        if len(czesci) > 1:
            slowa_trzonu = trzon.split()
            kategoria = slowa_trzonu[0] if slowa_trzonu else ""
            
            for wariant in czesci[1:]:
                wariant_norm = normalizuj_nazwe(wariant)
                if not wariant_norm:
                    continue
                    
                mapa_nazw[f"{trzon} {wariant_norm}"] = kod
                
                if kategoria and kategoria != trzon:
                    mapa_nazw[f"{kategoria} {wariant_norm}"] = kod

    return mapa_nazw

def dopasuj_towar_z_bazy(nazwa_faktura: str, kod_faktura: str, baza: list[dict], uzywaj_bazy: bool,
                         mapowania: dict = None, indeks: dict = None) -> tuple[str, str]:
    kod_faktura_clean = kod_faktura.strip()
    nazwa_faktura_clean = normalizuj_nazwe(nazwa_faktura)

    if not uzywaj_bazy:
        return kod_faktura_clean, ""

    # 1. Ręczne reguły użytkownika (JSON) mają bezwzględne pierwszeństwo przed katalogiem.
    if mapowania is None:
        mapowania = wczytaj_baze_mapowan()
    for nazwa_reguly, kod_reguly in mapowania.items():
        if normalizuj_nazwe(str(nazwa_reguly)) == nazwa_faktura_clean:
            return str(kod_reguly), kod_faktura_clean

    if not baza:
        return kod_faktura_clean, ""

    # 2. Dopasowanie do katalogu PC-Market (dokładne, potem przybliżone).
    mapa_nazw = indeks if indeks is not None else zbuduj_indeks_nazw(baza)

    if nazwa_faktura_clean in mapa_nazw:
        return mapa_nazw[nazwa_faktura_clean], kod_faktura_clean

    for wzorzec, kod in mapa_nazw.items():
        slowa_wzorce = wzorzec.split()
        slowa_faktura = nazwa_faktura_clean.split()
        for sf in slowa_faktura:
            if len(sf) >= 4:
                rdzen = sf.rstrip("Y").rstrip("I").rstrip("E")
                for sw in slowa_wzorce:
                    if sw.startswith(rdzen) and len(rdzen) >= 4:
                        if fuzz.token_set_ratio(nazwa_faktura_clean, wzorzec) >= 55:
                            return kod, kod_faktura_clean

    if mapa_nazw:
        najlepsza_nazwa, wynik = process.extractOne(
            nazwa_faktura_clean, 
            mapa_nazw.keys(), 
            scorer=fuzz.token_set_ratio
        )
        if wynik >= 65:
            return mapa_nazw[najlepsza_nazwa], kod_faktura_clean

    return "", kod_faktura_clean

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

def generuj_tekst_edi(dane: dict) -> str:
    pozycje = dane.get("pozycje", [])
    wyst = dane.get("wystawca", {})
    odb = dane.get("odbiorca", {})

    nip_wyst = re.sub(r"\D", "", str(wyst.get("nip", "")))
    nip_odb = re.sub(r"\D", "", str(odb.get("nip", "")))

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
        kod_glowny = str(poz.get("kod_dopasowany", poz.get("kod", ""))).strip()

        vat_raw = str(poz.get("vat", "5")).replace("%", "").replace(",", ".").strip()
        try:
            vat = str(int(float(vat_raw)))
        except Exception:
            vat = "5"

        jm = str(poz.get("jm", "kg")).lower().strip()
        
        ilosc = str(poz.get("ilosc", "1")).replace(",", ".").strip()
        cena = str(poz.get("cena_netto", "0.00")).replace(",", ".").strip()
        wartosc = str(poz.get("wartosc_netto", "0.00")).replace(",", ".").strip()

        if not cena.startswith("n"):
            cena = f"n{cena}"
        if not wartosc.startswith("n"):
            wartosc = f"n{wartosc}"

        linia = (
            f"Linia:Nazwa{{{nazwa}}}Kod{{{kod_glowny}}}Vat{{{vat}}}Jm{{{jm}}}"
            f"Ilosc{{{ilosc}}}Cena{{{cena}}}Wartosc{{{wartosc}}}"
        )
        linie.append(linia)

    return "\n".join(linie) + "\n"

def weryfikuj_sumy_netto(dane: dict) -> tuple[bool, str]:
    pozycje = dane.get("pozycje", [])
    suma_obliczona = 0.0
    
    for poz in pozycje:
        try:
            val_raw = str(poz.get("wartosc_netto", "0.00")).replace(",", ".").replace("n", "").strip()
            suma_obliczona += float(val_raw)
        except Exception:
            pass

    suma_doc_raw = str(dane.get("suma_netto_dokument", "")).replace(",", ".").strip()
    
    if not suma_doc_raw or suma_doc_raw == "0.00":
        try:
            stawki = dane.get("stawki", [])
            suma_doc_raw = str(sum(float(str(s.get("suma_netto", 0)).replace(",", ".")) for s in stawki))
        except Exception:
            suma_doc_raw = "0.00"

    try:
        suma_odczytana = float(suma_doc_raw)
    except Exception:
        suma_odczytana = 0.0

    if suma_odczytana > 0.0:
        roznica = abs(suma_obliczona - suma_odczytana)
        if roznica > 0.10:
            komunikat = (
                f"⚠️ Niezgodność sumy netto!\n"
                f"Suma pozycji: {suma_obliczona:.2f} | Z dokumentu: {suma_odczytana:.2f}"
            )
            return False, komunikat

    return True, f"Zgodność sumy netto: {suma_obliczona:.2f} zł"

def kompresuj_do_base64(sciezka_pliku: str, rozdzielczosc: int = 1800) -> str:
    with Image.open(sciezka_pliku) as img:
        # Zdjęcia z telefonu przechowują obrót w EXIF. Podgląd w aplikacji go respektuje,
        # a Pillow przy ponownym zapisie do JPEG go gubi - model dostałby obraz "na boku".
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

async def main(page: ft.Page):
    page.title = "ocrLmm Mobilny"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    konfig = wczytaj_konfiguracje()

    ostatnia_sciezka_edi = {"sciezka": None}
    aktualne_zdjecie = {"sciezka": None}

    tresc_bledu = ft.Text("", size=14)
    tytul_bledu = ft.Text("Komunikat", weight=ft.FontWeight.BOLD)

    def zamknij_alert(e):
        page.pop_dialog()

    dlg_alert = ft.AlertDialog(
        modal=True,
        title=tytul_bledu,
        content=tresc_bledu,
        actions=[
            ft.Button(content=ft.Text("Rozumiem"), on_click=zamknij_alert)
        ]
    )

    def pokaz_okno_bledu(tytul: str, wiadomosc: str):
        tytul_bledu.value = str(tytul)
        tresc_bledu.value = str(wiadomosc)
        page.show_dialog(dlg_alert)

    # --- KONSOLA LOGÓW ---
    konsola_logow = ft.ListView(expand=True, auto_scroll=True, height=300, spacing=5)

    def dopisz_log(wiadomosc: str, kolor=ft.Colors.WHITE):
        czas = datetime.now().strftime("%H:%M:%S")
        konsola_logow.controls.append(ft.Text(f"[{czas}] {wiadomosc}", size=12, color=kolor))
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
        page.show_dialog(dlg_konsola)

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

        status_text.value = f"Wyczyszczono katalog roboczy (usunięto {usuniete_pliki} plików)."
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
            pokaz_okno_bledu("Błąd", "Podaj nazwę wzorca oraz kod PC-Market.")
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
        actions=[ft.Button(content=ft.Text("Zamknij"), on_click=zamknij_alert)]
    )

    def otworz_okno_bazy_recznej(e):
        odswiez_widok_mapowan()
        page.show_dialog(dlg_baza_edycja)

    # --- WERYFIKACJA I WYSZUKIWARKA W LOCIE ---
    stan_weryfikacji = {
        "dane": None,
        "baza": [],
        "uzywa_bazy": True,
        "zgodne_sumy": True,
        "info_sumy": "",
        "indeks_edytowany": -1
    }

    lista_pozycji_weryfikacji = ft.ListView(expand=True, spacing=10, height=350)

    def klik_usun_przypisanie(idx):
        if idx >= 0 and stan_weryfikacji["dane"]:
            poz = stan_weryfikacji["dane"]["pozycje"][idx]
            poz["kod_dopasowany"] = ""
            
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
            
            if kod:
                nazwa_dopasowana = mapa_kod_nazwa.get(kod, "Nieznana nazwa towaru")
                tekst_kodu = ft.Text(f"Towar: {nazwa_dopasowana} (Kod: {kod})", size=12, color=ft.Colors.CYAN_400)
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
        zgodne_sumy = stan_weryfikacji["zgodne_sumy"]
        info_sumy = stan_weryfikacji["info_sumy"]
        uzywa_bazy = stan_weryfikacji["uzywa_bazy"]

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
        if zgodne_sumy:
            status_text.value = f"✅ Gotowe! Zapisano: {nazwa_pliku}\n({info_sumy}){tryb_info}"
            status_text.color = ft.Colors.GREEN_ACCENT
        else:
            status_text.value = f"⚠️ Zapisano: {nazwa_pliku}\n{info_sumy}{tryb_info}"
            status_text.color = ft.Colors.AMBER_ACCENT
        
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
        dlg_weryfikacja.open = False
        page.update()
        await zapisz_edi_i_zakoncz()

    def klik_anuluj_weryfikacje(e):
        dlg_weryfikacja.open = False 
        page.update()
        
        usun_wybrane_zdjecie(None)
        
        status_text.value = "Anulowano generowanie pliku EDI. Wybierz nowe zdjęcie."
        status_text.color = ft.Colors.RED_400
        btn_foto.disabled = False
        btn_aparat.disabled = False
        page.update()

    dlg_weryfikacja = ft.AlertDialog(
        modal=True,
        title=ft.Text("Weryfikacja kodów z faktury"),
        content=ft.Container(
            content=ft.Column([
                ft.Text("Sprawdź dopasowanie przed zapisem. Kliknij lupę, aby poprawić błędne.", size=12, color=ft.Colors.GREY_400),
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
        fraza = pole_szukaj_towaru.value.strip().upper()
        fragmenty = fraza.split()
        
        licznik = 0
        for towar in stan_weryfikacji["baza"]:
            nazwa_towaru = towar["nazwa"]
            kod_towaru = towar["kod_wew"]
            
            czy_pasuje = True
            for frag in fragmenty:
                if frag not in nazwa_towaru and frag not in kod_towaru:
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
        page.pop_dialog()
        page.show_dialog(dlg_wyszukiwarka)

    def klik_wybierz_z_wyszukiwarki(kod):
        idx = stan_weryfikacji["indeks_edytowany"]
        if idx >= 0 and stan_weryfikacji["dane"]:
            poz = stan_weryfikacji["dane"]["pozycje"][idx]
            poz["kod_dopasowany"] = kod
            
            oryginalna_nazwa = poz.get("oryg_nazwa", "").upper().strip()
            if oryginalna_nazwa:
                mapa = wczytaj_baze_mapowan()
                mapa[oryginalna_nazwa] = kod
                zapisz_baze_mapowan(mapa)
                odswiez_status_bazy()

        odswiez_weryfikacje()
        page.pop_dialog()
        page.show_dialog(dlg_weryfikacja)

    def zamknij_wyszukiwarke(e):
        odswiez_weryfikacje()
        page.pop_dialog()
        page.show_dialog(dlg_weryfikacja)

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
                            "Zachowano dotychczasową bazę."
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
            pokaz_okno_bledu("Błąd wczytywania bazy", str(err_baza))

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

                    # Walidacja: błędny plik zgłasza wyjątek (pokaże go okno błędu) i nic nie nadpisuje.
                    nowe_reguly = wczytaj_plik_mapowan_z_walidacja(sciezka_zrodlowa)
                    dotychczasowe = wczytaj_baze_mapowan()

                    # Kopia zapasowa i SCALENIE (reguły z pliku wygrywają przy tych samych nazwach),
                    # zamiast kasowania wszystkiego, czego nie ma w wgrywanym pliku.
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
            pokaz_okno_bledu("Błąd wczytywania mapowań", str(err_mapa))

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
            pokaz_okno_bledu("Brak plików", "Nie znaleziono aktywnej bazy TXT ani zapisanych mapowań JSON.")
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
                pokaz_okno_bledu("Błąd", "Funkcja udostępniania niedostępna na tym urządzeniu.")
        except Exception as err:
            dopisz_log(f"Błąd eksportu kodów: {err}", ft.Colors.RED)
            pokaz_okno_bledu("Błąd udostępniania", str(err))

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

    # --- APARAT (NATYWNY PODGLĄD FLET-CAMERA) ---
    try:
        kamera_obiektyw = fc.Camera(
            expand=True
        )
    except Exception as e:
        kamera_obiektyw = ft.Text(f"Aparat nie jest wspierany: {e}")

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

    btn_migawka = ft.FloatingActionButton(
        icon=ft.Icons.CAMERA,
        on_click=klik_migawka
    )

    dlg_aparat = ft.AlertDialog(
        modal=True,
        title=ft.Text("Zrób zdjęcie faktury"),
        content=ft.Container(
            content=kamera_obiektyw,
            width=400,
            height=500
        ),
        actions=[
            btn_migawka,
            ft.Button("Anuluj", on_click=lambda e: page.pop_dialog())
        ],
        actions_alignment=ft.MainAxisAlignment.CENTER
    )

    async def otworz_aparat(e):
        # Android automatycznie wyświetli systemowe okno uprawnień
        # przy pierwszej próbie zainicjalizowania fc.Camera w oknie dialogowym.
        page.show_dialog(dlg_aparat)
    # --- KONIEC APARATU ---
    

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
        status_text.value = "Zdjęcie załadowane. Sprawdź orientację i kliknij 'Wyślij do analizy'."
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
        page.show_dialog(dlg_ustawienia)

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

    async def przetworz_plik(sciezka_obrazu):
        if not sciezka_obrazu or not os.path.exists(sciezka_obrazu):
            return

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
                # content bywa None, gdy model "przemyślał" cały limit tokenów i nie zdążył odpowiedzieć
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

            dopisz_log("Wstępne mapowanie do bazy...")
            zgodne_sumy, info_sumy = weryfikuj_sumy_netto(dane)
            aktualna_baza_sciezka = pobierz_aktualna_sciezke_bazy(aktualny_konfig)
            baza_towarowa = wczytaj_baze_pcmarket(aktualna_baza_sciezka) if uzywa_bazy else []

            mapowania_reczne = wczytaj_baze_mapowan()
            indeks_nazw = zbuduj_indeks_nazw(baza_towarowa) if baza_towarowa else {}

            for poz in dane.get("pozycje", []):
                nazwa = str(poz.get("nazwa", "")).strip().upper()
                kod_faktura = str(poz.get("kod", "")).strip()
                kod_dop, _ = dopasuj_towar_z_bazy(
                    nazwa, kod_faktura, baza_towarowa, uzywa_bazy,
                    mapowania=mapowania_reczne, indeks=indeks_nazw
                )
                poz["oryg_nazwa"] = nazwa
                poz["kod_dopasowany"] = kod_dop

            stan_weryfikacji["dane"] = dane
            stan_weryfikacji["baza"] = baza_towarowa
            stan_weryfikacji["uzywa_bazy"] = uzywa_bazy
            stan_weryfikacji["zgodne_sumy"] = zgodne_sumy
            stan_weryfikacji["info_sumy"] = info_sumy
            stan_weryfikacji["indeks_edytowany"] = -1

            dopisz_log("Przygotowano okno weryfikacji.")
            status_text.value = "Oczekiwanie na potwierdzenie kodów..."
            status_text.color = ft.Colors.CYAN_ACCENT
            pasek_postepu.visible = False
            page.update()

            odswiez_weryfikacje()
            page.show_dialog(dlg_weryfikacja)

        except Exception as err:
            komunikat = str(err)
            dopisz_log(f"Wystąpił wyjątek: {komunikat}", ft.Colors.RED)
            
            if "503" in komunikat:
                pokaz_okno_bledu("⏳ Serwer przeciążony", "Odczekaj chwilę i kliknij przycisk odświeżenia/analizy ponownie.")
            elif "429" in komunikat:
                pokaz_okno_bledu("⏳ Limit zapytań wyczerpany", "Zbyt wiele zapytań w krótkim czasie. Odczekaj 30 sekund.")
            elif "401" in komunikat or "API_KEY_INVALID" in komunikat:
                pokaz_okno_bledu("🔑 Błąd autoryzacji", "Sprawdź poprawność klucza API w ustawieniach (zębatka).")
            else:
                pokaz_okno_bledu("❌ Błąd przetwarzania", komunikat)
            
            status_text.value = f"Błąd: {komunikat}"
            status_text.color = ft.Colors.RED_ACCENT
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
        page.show_dialog(dlg_potwierdz_czyszczenie)

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
