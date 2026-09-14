import flet as ft
import base64
import json
import os
import shutil
import socket
import asyncio
import re
import io
import httpx
from datetime import datetime
from PIL import Image, ImageEnhance, ImageFilter
from thefuzz import process, fuzz

KATALOG_DANYCH = os.getenv("FLET_APP_STORAGE_DATA", os.getcwd())
os.makedirs(KATALOG_DANYCH, exist_ok=True)

CONFIG_FILE = os.path.join(KATALOG_DANYCH, "ocrlmm_mobile_config.json")
DOMYSLNA_BAZA_FILE = os.path.join(KATALOG_DANYCH, "WĘDLINA.txt")

DOMYSLNA_KONFIGURACJA = {
    "wol_mac": "2C:F0:5D:E4:8E:85",
    "use_cloud": True,
    "use_db_matching": True,
    "baza_file_path": DOMYSLNA_BAZA_FILE,
    "gemini_api_key": "",
    "gemini_model": "gemini-3.6-flash",
    "local_ip": "192.168.1.154",
    "local_port": "1234",
    "local_model": "qwen3-vl-4b-instruct",
    "local_api_key": ""
}

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
    towary = []
    if not sciezka:
        konf = wczytaj_konfiguracje()
        sciezka = pobierz_aktualna_sciezke_bazy(konf)

    if os.path.exists(sciezka):
        kodowania = ["windows-1250", "utf-8", "cp852"]
        linie = None
        
        for enc in kodowania:
            try:
                with open(sciezka, "r", encoding=enc) as f:
                    linie = f.readlines()
                break
            except UnicodeDecodeError:
                continue
                
        if not linie:
            return towary

        try:
            for linia in linie:
                kolumny = linia.strip().split("\t")
                if len(kolumny) >= 3:
                    nazwa = kolumny[0].strip().upper()
                    kod = kolumny[2].strip().lstrip("'")
                    if nazwa and kod and nazwa != "NAZWA":
                        towary.append({
                            "nazwa": nazwa,
                            "kod_wew": kod
                        })
        except Exception as e:
            print(f"Błąd parsowania bazy PC-Market: {e}")
    return towary

def dopasuj_towar_z_bazy(nazwa_faktura: str, kod_faktura: str, baza: list[dict], uzywaj_bazy: bool) -> tuple[str, str]:
    kod_faktura_clean = kod_faktura.strip()
    nazwa_faktura_clean = nazwa_faktura.strip().upper()

    if not uzywaj_bazy:
        return kod_faktura_clean, ""

    if baza and nazwa_faktura_clean:
        mapa_nazw = {t["nazwa"]: t["kod_wew"] for t in baza}
        if nazwa_faktura_clean in mapa_nazw:
            return mapa_nazw[nazwa_faktura_clean], kod_faktura_clean

        najlepsza_nazwa, wynik = process.extractOne(
            nazwa_faktura_clean, 
            mapa_nazw.keys(), 
            scorer=fuzz.token_set_ratio
        )
        if wynik >= 65:
            return mapa_nazw[najlepsza_nazwa], kod_faktura_clean

    return kod_faktura_clean, ""

def wyslij_wol(mac_address: str):
    czysty_mac = mac_address.replace(":", "").replace("-", "").replace(".", "")
    if len(czysty_mac) != 12:
        raise ValueError("Nieprawidłowy format adresu MAC.")

    dane_mac = bytes.fromhex(czysty_mac)
    magic_packet = b"\xff" * 6 + dane_mac * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic_packet, ("<broadcast>", 9))

def generuj_tekst_edi(dane: dict, uzywaj_bazy: bool, sciezka_bazy: str = None) -> str:
    baza_towarowa = wczytaj_baze_pcmarket(sciezka_bazy) if uzywaj_bazy else []
    pozycje = dane.get("pozycje", [])
    wyst = dane.get("wystawca", {})
    odb = dane.get("odbiorca", {})
    stawki = dane.get("stawki", [])

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
        nazwa = str(poz.get("nazwa", "")).strip().upper()
        kod_faktura = str(poz.get("kod", "")).strip()

        kod_glowny, kod_dodatkowy = dopasuj_towar_z_bazy(nazwa, kod_faktura, baza_towarowa, uzywaj_bazy)

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

def kompresuj_do_base64(sciezka_pliku: str) -> str:
    with Image.open(sciezka_pliku) as img:
        img.thumbnail((2600, 2600))
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
        title=tytul_bledu,
        content=tresc_bledu,
        actions=[
            ft.Button(content=ft.Text("Rozumiem"), on_click=zamknij_alert)
        ]
    )

    def pokaz_okno_bledu(tytul: str, wiadomosc: str):
        tytul_bledu.value = tytul
        tresc_bledu.value = wiadomosc
        page.show_dialog(dlg_alert)

    chk_cloud = ft.Checkbox(
        label="Użyj chmury (Google Gemini)",
        value=konfig.get("use_cloud", True)
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
    txt_local_model = ft.TextField(
        label="Model LM Studio",
        value=konfig.get("local_model", "qwen3-vl-4b-instruct"),
        dense=True
    )
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
            await loop.run_in_executor(None, lambda: wyslij_wol(txt_mac.value.strip()))
            status_text.value = "Pakiet Wake-on-LAN wysłany."
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

    sciezka_biezaca_bazy = pobierz_aktualna_sciezke_bazy(konfig)
    baza_towarowa_cache = wczytaj_baze_pcmarket(sciezka_biezaca_bazy)
    liczba_towarow = len(baza_towarowa_cache)
    nazwa_bazy_wyswietlana = os.path.basename(sciezka_biezaca_bazy)

    lbl_status_bazy = ft.Text(
        f"Załadowano {liczba_towarow} poz. z: {nazwa_bazy_wyswietlana}" if liczba_towarow > 0 else f"Brak towarów w pliku: {nazwa_bazy_wyswietlana}",
        size=12,
        color=ft.Colors.GREEN_300 if liczba_towarow > 0 else ft.Colors.ORANGE_300
    )

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
                    docelowa_sciezka = os.path.join(KATALOG_DANYCH, oryginalna_nazwa)
                    try:
                        shutil.copyfile(sciezka_zrodlowa, docelowa_sciezka)
                    except Exception:
                        docelowa_sciezka = sciezka_zrodlowa

                    konfig["baza_file_path"] = docelowa_sciezka
                    zapisz_konfiguracje(konfig)

                    nowa_baza = wczytaj_baze_pcmarket(docelowa_sciezka)
                    nowa_ilosc = len(nowa_baza)
                    lbl_status_bazy.value = f"Załadowano {nowa_ilosc} poz. z: {oryginalna_nazwa}"
                    lbl_status_bazy.color = ft.Colors.GREEN_300 if nowa_ilosc > 0 else ft.Colors.ORANGE_300
                    status_text.value = f"Wczytano nową bazę ({nowa_ilosc} towarów)."
                    status_text.color = ft.Colors.CYAN_ACCENT
                    page.update()
        except Exception as err_baza:
            pokaz_okno_bledu("Błąd wczytywania bazy", str(err_baza))

    btn_wybierz_baze = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN), ft.Text("Wybierz plik bazy (.txt)")], alignment=ft.MainAxisAlignment.CENTER),
        style=ft.ButtonStyle(bgcolor=ft.Colors.AMBER_900, color=ft.Colors.WHITE),
        on_click=wybierz_plik_bazy
    )

    kontener_baza_pcmarket = ft.Column(
        [
            ft.Text("Baza towarowa PC-Market:", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
            chk_db_matching,
            btn_wybierz_baze,
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
            txt_local_model,
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
        "Wybierz zdjęcie lub zrób zdjęcie aparatem.",
        size=13,
        color=ft.Colors.GREEN_ACCENT,
        text_align=ft.TextAlign.CENTER
    )
    pasek_postepu = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_ACCENT)
    podglad_obrazu = ft.Image(src="", visible=False, fit="contain", height=240)

    def ustaw_stan_przycisku_foto(czy_ma_zdjecie: bool):
        if czy_ma_zdjecie:
            ikona_btn_foto.name = ft.Icons.SEND
            tekst_btn_foto.value = "Wyślij do analizy"
            btn_foto.style.bgcolor = ft.Colors.BLUE_700
        else:
            ikona_btn_foto.name = ft.Icons.PHOTO_LIBRARY
            tekst_btn_foto.value = "Wybierz zdjęcie z galerii"
            btn_foto.style.bgcolor = ft.Colors.GREEN_800

    def ustaw_nowy_obraz(sciezka: str):
        aktualne_zdjecie["sciezka"] = sciezka
        podglad_obrazu.src = sciezka
        podglad_obrazu.visible = True
        btn_usun_zdjecie.visible = True
        wiersz_obrotu.visible = True
        ustaw_stan_przycisku_foto(True)
        status_text.value = "Zdjęcie załadowane. Sprawdź orientację i kliknij 'Wyślij do analizy'."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    def usun_wybrane_zdjecie(e):
        aktualne_zdjecie["sciezka"] = None
        podglad_obrazu.src = ""
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        btn_udostepnij.visible = False
        btn_ponow.visible = False
        wiersz_obrotu.visible = False
        ustaw_stan_przycisku_foto(False)
        status_text.value = "Zdjęcie usunięte. Wybierz nowe zdjęcie."
        status_text.color = ft.Colors.GREEN_ACCENT
        page.update()

    btn_usun_zdjecie = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE), ft.Text("Usuń wybrane zdjęcie")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False,
        style=ft.ButtonStyle(color=ft.Colors.RED_300),
        on_click=usun_wybrane_zdjecie
    )

    def obroc_zdjecie(kat):
        sciezka = aktualne_zdjecie["sciezka"]
        if not sciezka or not os.path.exists(sciezka):
            return
        try:
            with Image.open(sciezka) as im:
                obrocony = im.rotate(kat, expand=True)
                obrocony.save(sciezka)
            
            podglad_obrazu.src = f"{sciezka}?t={datetime.now().timestamp()}"
            status_text.value = f"Obrócono zdjęcie o {abs(kat)}°. Kliknij 'Wyślij do analizy'."
            status_text.color = ft.Colors.CYAN_ACCENT
            page.update()
        except Exception as err_rot:
            status_text.value = f"Błąd obracania: {err_rot}"
            page.update()

    btn_obroc_lewo = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.ROTATE_LEFT), ft.Text("Obróć w lewo")], alignment=ft.MainAxisAlignment.CENTER),
        expand=True,
        on_click=lambda e: obroc_zdjecie(90)
    )

    btn_obroc_prawo = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.ROTATE_RIGHT), ft.Text("Obróć w prawo")], alignment=ft.MainAxisAlignment.CENTER),
        expand=True,
        on_click=lambda e: obroc_zdjecie(-90)
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
        konfig["local_model"] = txt_local_model.value.strip()
        konfig["local_api_key"] = txt_local_api_key.value.strip()
        
        zapisz_konfiguracje(konfig)
        page.pop_dialog()
        status_text.value = "Ustawienia zostały zapisane."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    dlg_ustawienia = ft.AlertDialog(
        title=ft.Text("⚙️ Ustawienia połączenia"),
        content=ft.Column(
            [
                chk_cloud,
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

            if os.name == "nt":
                os.system(f'explorer /select,"{os.path.abspath(sciezka)}"')
                status_text.value = "Otwarto folder z plikiem EDI."
            else:
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
            uzywa_chmury = konfig.get("use_cloud", True)
            uzywa_bazy = konfig.get("use_db_matching", True)
            model_gemini = konfig.get("gemini_model", "gemini-3.6-flash").strip()
            nazwa_silnika = model_gemini if uzywa_chmury else konfig.get("local_model", "LM Studio")
            
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
            base64_image = await loop.run_in_executor(None, kompresuj_do_base64, sciezka_obrazu)

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
                "Zwróć TYLKO czysty obiekt JSON zgodny ze strukturą:\n"
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
                klucz = konfig.get("gemini_api_key", "").strip()
                pelny_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_gemini}:generateContent?key={klucz}"
                naglowki = {"Content-Type": "application/json"}
                cialo_zapytania = {
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": base64_image
                                }
                            }
                        ]
                    }],
                    "generationConfig": {
                        "temperature": 0.0,
                        "maxOutputTokens": 4096,
                        "responseMimeType": "application/json"
                    }
                }
            else:
                ip = konfig.get("local_ip", "192.168.1.154").strip()
                port = konfig.get("local_port", "1234").strip()
                pelny_url = f"http://{ip}:{port}/v1/chat/completions"
                klucz = konfig.get("local_api_key", "").strip()
                wybrany_model = konfig.get("local_model", "qwen3-vl-4b-instruct").strip()

                naglowki = {"Content-Type": "application/json"}
                if klucz:
                    naglowki["Authorization"] = f"Bearer {klucz}"

                cialo_zapytania = {
                    "model": wybrany_model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }],
                    "temperature": 0.0,
                    "max_tokens": 2500
                }

            max_prob = 4
            opoznienie_poczatkowe = 2.0
            odpowiedz = None

            async with httpx.AsyncClient(timeout=90.0, verify=True) as client:
                for proba in range(max_prob):
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
                            page.update()
                            await asyncio.sleep(czas_oczekiwania)
                            continue
                    
                    odpowiedz.raise_for_status()
                    break

                dane_odp = odpowiedz.json()
                if uzywa_chmury:
                    odp_tekst = dane_odp["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    odp_tekst = dane_odp["choices"][0]["message"]["content"].strip()

            dopasowanie = re.search(r'\{.*\}', odp_tekst, re.DOTALL)
            if not dopasowanie:
                raise ValueError("Model AI nie zwrócił formatu JSON.")

            czysty_json = dopasowanie.group(0)

            try:
                dane = json.loads(czysty_json)
            except json.JSONDecodeError:
                raise ValueError("Błąd parsowania odpowiedzi JSON.")

            zgodne_sumy, info_sumy = weryfikuj_sumy_netto(dane)
            aktualna_baza_sciezka = pobierz_aktualna_sciezke_bazy(konfig)
            tresc_edi = generuj_tekst_edi(dane, uzywa_bazy, aktualna_baza_sciezka)

            nr_dok = "".join(c for c in dane.get("nr_dok", "faktura") if c.isalnum() or c in ("-", "_"))
            nazwa_pliku = f"edi_{nr_dok}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            sciezka_edi = os.path.join(KATALOG_DANYCH, nazwa_pliku)

            with open(sciezka_edi, "w", encoding="windows-1250", errors="replace") as f:
                f.write(tresc_edi)

            ostatnia_sciezka_edi["sciezka"] = sciezka_edi
            
            tryb_info = " (dopasowano do PC-Market)" if uzywa_bazy else " (kody oryginalne)"
            if zgodne_sumy:
                status_text.value = f"✅ Gotowe! Zapisano: {nazwa_pliku}\n({info_sumy}){tryb_info}"
                status_text.color = ft.Colors.GREEN_ACCENT
            else:
                status_text.value = f"⚠️ Zapisano: {nazwa_pliku}\n{info_sumy}{tryb_info}"
                status_text.color = ft.Colors.AMBER_ACCENT
            
            btn_udostepnij.visible = True
            await udostepnij_plik(sciezka_edi)

        except Exception as err:
            komunikat = str(err)
            if "503" in komunikat:
                pokaz_okno_bledu("⏳ Serwer Gemini przeciążony", "Odczekaj chwilę i kliknij przycisk odświeżenia/analizy ponownie.")
            elif "429" in komunikat:
                pokaz_okno_bledu("⏳ Limit zapytań wyczerpany", "Zbyt wiele zapytań w krótkim czasie. Odczekaj 30 sekund.")
            elif "401" in komunikat or "API_KEY_INVALID" in komunikat:
                pokaz_okno_bledu("🔑 Błąd autoryzacji", "Sprawdź poprawność klucza API w ustawieniach (zębatka).")
            else:
                pokaz_okno_bledu("❌ Błąd przetwarzania", komunikat)
            
            status_text.value = f"Błąd: {komunikat}"
            status_text.color = ft.Colors.RED_ACCENT
        finally:
            pasek_postepu.visible = False
            btn_foto.disabled = False
            btn_aparat.disabled = False
            btn_ponow.visible = True
            btn_usun_zdjecie.visible = True
            wiersz_obrotu.visible = True
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

    async def zrob_zdjecie_aparatem(e):
        try:
            if hasattr(picker, "take_photo"):
                plik = await picker.take_photo()
                if plik and getattr(plik, "path", None):
                    ustaw_nowy_obraz(plik.path)
                    return
            
            status_text.value = "Aparat bezpośredni niedostępny w tej konfiguracji silnika Flet. Użyj galerii."
            status_text.color = ft.Colors.AMBER_ACCENT
            page.update()
        except Exception as err_cam:
            status_text.value = f"Błąd aparatu: {err_cam}"
            status_text.color = ft.Colors.RED_ACCENT
            page.update()

    async def klik_glowny_przycisk(e):
        if aktualne_zdjecie["sciezka"]:
            await przetworz_plik(aktualne_zdjecie["sciezka"])
        else:
            await otworz_galerie()

    ikona_btn_foto = ft.Icon(ft.Icons.PHOTO_LIBRARY)
    tekst_btn_foto = ft.Text("Wybierz zdjęcie z galerii")

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

    btn_aparat = ft.IconButton(
        icon=ft.Icons.CAMERA_ALT,
        tooltip="Zrób zdjęcie aparatem",
        icon_size=28,
        height=55,
        width=55,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.TEAL_800,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=zrob_zdjecie_aparatem
    )

    wiersz_wyboru_foto = ft.Row(
        [btn_foto, btn_aparat],
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=8
    )

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

    btn_settings = ft.IconButton(
        icon=ft.Icons.SETTINGS,
        tooltip="Ustawienia połączenia",
        on_click=otworz_ustawienia
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
            btn_settings
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
    )

    page.add(
        ft.Column(
            [
                pasek_tytulu,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                wiersz_wyboru_foto,
                pasek_postepu,
                status_text,
                btn_ponow,
                btn_udostepnij,
                podglad_obrazu,
                wiersz_obrotu,
                btn_usun_zdjecie,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=10
        )
    )

if __name__ == "__main__":
    ft.run(main)
