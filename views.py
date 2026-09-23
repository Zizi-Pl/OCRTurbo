import os
import re
import json
import shutil
import asyncio
from datetime import datetime
import flet as ft
import httpx
from PIL import Image, ImageOps

import config
import core
from ui import UIManager


class ViewsManager:
    def __init__(self, page: ft.Page, ui_manager: UIManager, serwis_udostepniania: ft.Share, pickery: dict):
        self.page = page
        self.ui = ui_manager
        self.serwis_udostepniania = serwis_udostepniania
        self.pickery = pickery

        # Powiązanie zwrotne z ui_managerem
        self.ui.views_manager = self
        self.ui.on_foto_captured = self.przypisz_zrobione_foto

        # Stan roboczy weryfikacji pozycji
        self.stan_weryfikacji = {
            "dane": None,
            "baza": [],
            "uzywa_bazy": True,
            "status_sum": "BRAK_DANYCH",
            "info_sumy": "",
            "indeks_edytowany": -1
        }
        self.blokada_analizy = False
        self.ostatnia_sciezka_edi = {"sciezka": None}

        # Stany robocze poszczególnych modułów
        self.aktualne_zdjecie_pz = {"sciezka": None}
        self.zdjecie_dok = {"sciezka": None}
        self.zdjecie_skan = {"sciezka": None, "oryginal": None}

        # Budowa ekranów aplikacji
        self._inicjalizuj_modul_pz()
        self._inicjalizuj_modul_dokument()
        self._inicjalizuj_modul_skanera()
        self._inicjalizuj_menu_glowne()

    # =========================================================================
    # CALLBACKI APARATU I ZDJĘĆ
    # =========================================================================
    def przypisz_zrobione_foto(self, sciezka: str, modul: str):
        if modul == "pz":
            self.ustaw_nowy_obraz_pz(sciezka)
        elif modul == "dokument":
            self.ustaw_nowy_obraz_dok(sciezka)
        elif modul == "skaner":
            self.ustaw_nowy_obraz_skan(sciezka)

    # =========================================================================
    # 1. MODUŁ I: FAKTURA / PZ (DLA PC-MARKET)
    # =========================================================================
    def _inicjalizuj_modul_pz(self):
        self.podglad_obrazu_pz = ft.Image(
            src=config.PUSTY_OBRAZ,
            visible=False,
            fit="contain",
            height=240,
            border_radius=8
        )

        self.wiersz_obrotu_pz = ft.Row([
            ft.Button("Obróć w lewo (90°)", icon=ft.Icons.ROTATE_LEFT, on_click=lambda e: asyncio.create_task(self.obroc_obraz_pz(90)), expand=True),
            ft.Button("Obróć w prawo (90°)", icon=ft.Icons.ROTATE_RIGHT, on_click=lambda e: asyncio.create_task(self.obroc_obraz_pz(-90)), expand=True)
        ], spacing=10, visible=False)

        self.btn_akcja_analiza_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW), ft.Text("Rozpocznij analizę PZ")], alignment=ft.MainAxisAlignment.CENTER),
            visible=False, height=48,
            style=ft.ButtonStyle(bgcolor=ft.Colors.AMBER_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.przetworz_plik_pz(self.aktualne_zdjecie_pz["sciezka"]))
        )

        self.btn_usun_zdjecie_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, size=18), ft.Text("Usuń wybrane zdjęcie", size=12)], alignment=ft.MainAxisAlignment.CENTER),
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            visible=False,
            on_click=lambda e: self.usun_wybrane_zdjecie_pz(e)
        )

        self.pasek_postepu_pz = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_ACCENT)
        self.status_text_pz = ft.Text("Wybierz z galerii lub zrób zdjęcie dokumentu PZ.", size=13, color=ft.Colors.GREY_300, text_align=ft.TextAlign.CENTER)

        self.btn_foto_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("Wybierz z galerii")], alignment=ft.MainAxisAlignment.CENTER),
            height=55,
            expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_galerie_pz())
        )

        self.btn_aparat_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Zrób zdjęcie")]),
            height=55,
            expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.ui.otworz_aparat_dla("pz"))
        )

        self.wiersz_wyboru_zdjecia_pz = ft.Row([self.btn_foto_pz, self.btn_aparat_pz], spacing=10)

        self.btn_wroc_weryfikacja_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.FACT_CHECK), ft.Text("Wróć do weryfikacji (bez ponownej analizy)")], alignment=ft.MainAxisAlignment.CENTER),
            visible=False, height=48,
            style=ft.ButtonStyle(bgcolor=ft.Colors.TEAL_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.klik_wroc_do_weryfikacji
        )

        self.btn_udostepnij_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.SHARE), ft.Text("Udostępnij plik EDI")], alignment=ft.MainAxisAlignment.CENTER),
            visible=False, height=48,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.udostepnij_plik(self.ostatnia_sciezka_edi["sciezka"]))
        )

        self.btn_baza_ikona = ft.IconButton(icon=ft.Icons.STORAGE, tooltip="Baza i powiązania towarów", on_click=self.ui.otworz_okno_bazy_recznej)
        self.btn_konsola = ft.IconButton(icon=ft.Icons.TERMINAL, tooltip="Konsola zdarzeń (logi)", on_click=self.ui.otworz_konsole)

        pasek_tytulu_pz = ft.Row(
            [
                ft.Row([
                    ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Menu Główne", on_click=lambda e: self.przelacz_widok("menu")),
                    ft.Column([
                        ft.Text("ocrLmm Mobile", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                        ft.Text("Skaner PZ (PC-Market)", size=11, color=ft.Colors.GREY_400)
                    ], spacing=1)
                ], spacing=4, expand=True),
                ft.Row([self.btn_baza_ikona, self.btn_konsola], spacing=0)
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        self.dlg_potwierdz_czyszczenie = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠️ Potwierdzenie usunięcia"),
            content=ft.Text(
                "Czy na pewno chcesz usunąć wszystkie wygenerowane pliki EDI oraz zdjęcia tymczasowe z katalogu aplikacji?\n\n"
                "Baza towarowa i konfiguracja nie zostaną usunięte."
            ),
            actions=[
                ft.Button(content=ft.Text("Anuluj"), on_click=lambda e: self.page.pop_dialog()),
                ft.Button(
                    content=ft.Text("Tak, wyczyść"),
                    style=ft.ButtonStyle(bgcolor=ft.Colors.RED_800, color=ft.Colors.WHITE),
                    on_click=self.wykonaj_czyszczenie_katalogu
                )
            ]
        )

        btn_wyczysc_katalog = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CLEANING_SERVICES, size=18), ft.Text("Wyczyść katalog tymczasowy", size=12)], alignment=ft.MainAxisAlignment.CENTER),
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            expand=True, on_click=lambda e: self.ui.bezpiecznie_otworz_dialog(self.dlg_potwierdz_czyszczenie)
        )

        self.widok_pz = ft.Column([
            pasek_tytulu_pz,
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self.wiersz_wyboru_zdjecia_pz,
            self.pasek_postepu_pz,
            self.status_text_pz,
            self.btn_akcja_analiza_pz,
            self.btn_wroc_weryfikacja_pz,
            self.btn_udostepnij_pz,
            self.podglad_obrazu_pz,
            self.wiersz_obrotu_pz,
            self.btn_usun_zdjecie_pz,
            ft.Divider(height=16, color=ft.Colors.GREY_800),
            ft.Row([btn_wyczysc_katalog])
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=10, visible=False)

    def ustaw_stan_przycisku_foto_pz(self, czy_ma_zdjecie: bool):
        self.podglad_obrazu_pz.visible = czy_ma_zdjecie
        self.btn_usun_zdjecie_pz.visible = czy_ma_zdjecie
        self.wiersz_obrotu_pz.visible = czy_ma_zdjecie
        self.btn_akcja_analiza_pz.visible = czy_ma_zdjecie

        if czy_ma_zdjecie and not self.stan_weryfikacji["dane"]:
            self.btn_akcja_analiza_pz.content.controls[1].value = "Rozpocznij analizę PZ"
        self.page.update()

    def ustaw_nowy_obraz_pz(self, sciezka: str):
        nowa_sciezka = os.path.join(config.KATALOG_DANYCH, f"foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        try:
            shutil.copyfile(sciezka, nowa_sciezka)
        except Exception:
            nowa_sciezka = sciezka
        self.aktualne_zdjecie_pz["sciezka"] = nowa_sciezka
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = nowa_sciezka
        self.podglad_obrazu_pz.visible = True
        self.btn_usun_zdjecie_pz.visible = True
        self.wiersz_obrotu_pz.visible = True
        self.ustaw_stan_przycisku_foto_pz(True)
        self.status_text_pz.value = "Zdjęcie gotowe. Kliknij 'Rozpocznij analizę PZ'."
        self.status_text_pz.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    async def obroc_obraz_pz(self, kat: int):
        if not self.aktualne_zdjecie_pz["sciezka"] or not os.path.exists(self.aktualne_zdjecie_pz["sciezka"]):
            return
        nowa_sciezka = await asyncio.get_running_loop().run_in_executor(
            None, core.obroc_plik_graficzny, self.aktualne_zdjecie_pz["sciezka"], kat, "rot"
        )
        self.aktualne_zdjecie_pz["sciezka"] = nowa_sciezka
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = nowa_sciezka
        self.ui.dopisz_log(f"Obrócono obraz o {kat}°.")
        self.page.update()

    def usun_wybrane_zdjecie_pz(self, e=None):
        sciezka_pliku = self.aktualne_zdjecie_pz.get("sciezka")
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            try:
                os.remove(sciezka_pliku)
                self.ui.dopisz_log(f"Usunięto plik tymczasowy: {os.path.basename(sciezka_pliku)}")
            except Exception as err:
                self.ui.dopisz_log(f"Nie udało się usunąć pliku z dysku: {err}", ft.Colors.AMBER)

        self.aktualne_zdjecie_pz["sciezka"] = None
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = config.PUSTY_OBRAZ
        self.podglad_obrazu_pz.visible = False
        self.btn_usun_zdjecie_pz.visible = False
        self.wiersz_obrotu_pz.visible = False
        self.btn_akcja_analiza_pz.visible = False
        self.ustaw_stan_przycisku_foto_pz(False)
        self.status_text_pz.value = "Wybierz z galerii lub zrób zdjęcie dokumentu PZ."
        self.status_text_pz.color = ft.Colors.GREY_300
        self.page.update()

    async def otworz_galerie_pz(self):
        try:
            pliki = await self.pickery["foto"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            if pliki and len(pliki) > 0 and pliki[0].path:
                self.ustaw_nowy_obraz_pz(pliki[0].path)
        except Exception as e_pick:
            self.status_text_pz.value = f"Błąd wyboru pliku: {e_pick}"
            self.page.update()

    def wykonaj_czyszczenie_katalogu(self, e):
        self.page.pop_dialog()
        usuniete = core.wyczysc_pliki_robocze()
        self.ostatnia_sciezka_edi["sciezka"] = None
        self.usun_wybrane_zdjecie_pz(None)
        self.ui._pozycja_scrolla_pz = 0.0  # <--- RESET SCROLLA
        self.status_text_pz.value = f"Wyczyszczono katalog roboczy (usunięto {usuniete} plików). Stan zresetowany."
        self.status_text_pz.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    def klik_wroc_do_weryfikacji(self, e):
        if self.stan_weryfikacji["dane"]:
            self.ui.odswiez_weryfikacje()
            self.ui.bezpiecznie_otworz_dialog(self.ui.dlg_weryfikacja)

    def anuluj_weryfikacje(self):
        self.status_text_pz.value = "Anulowano generowanie EDI. Możesz wrócić do weryfikacji bez ponownej analizy albo wybrać inne zdjęcie."
        self.status_text_pz.color = ft.Colors.ORANGE_ACCENT
        self.btn_foto_pz.disabled = False
        self.btn_aparat_pz.disabled = False
        self.btn_wroc_weryfikacja_pz.visible = self.stan_weryfikacji["dane"] is not None
        self.page.update()

    async def zapisz_edi_i_zakoncz(self):
        dane = self.stan_weryfikacji["dane"]
        status_sum = self.stan_weryfikacji["status_sum"]
        info_sumy = self.stan_weryfikacji["info_sumy"]
        uzywa_bazy = self.stan_weryfikacji["uzywa_bazy"]

        self.ui.dopisz_log("Generowanie struktury pliku EDI z potwierdzonymi kodami...")
        tresc_edi = core.generuj_tekst_edi(dane)

        nr_dok = "".join(c for c in str(dane.get("nr_dok") or "") if c.isalnum() or c in ("-", "_")) or "faktura"
        nazwa_pliku = f"edi_{nr_dok}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        sciezka_edi = os.path.join(config.KATALOG_DANYCH, nazwa_pliku)

        try:
            with open(sciezka_edi, "w", encoding="windows-1250", errors="replace") as f:
                f.write(tresc_edi)
        except Exception as err_zapis:
            self.ui.dopisz_log(f"Błąd zapisu pliku EDI: {err_zapis}", ft.Colors.RED)
            self.ui.pokaz_okno_bledu("Błąd zapisu EDI", str(err_zapis), powrot_do=self.ui.dlg_weryfikacja)
            return

        self.ostatnia_sciezka_edi["sciezka"] = sciezka_edi
        self.ui.dopisz_log(f"Zakończono sukcesem. Zapisano: {nazwa_pliku}", ft.Colors.GREEN)

        tryb_info = " (dopasowano do PC-Market)" if uzywa_bazy else " (kody oryginalne)"
        if status_sum == "OK":
            self.status_text_pz.value = f"✅ Gotowe! Zapisano: {nazwa_pliku}\n({info_sumy}){tryb_info}"
            self.status_text_pz.color = ft.Colors.GREEN_ACCENT
        elif status_sum == "BLAD":
            self.status_text_pz.value = f"⚠️ Zapisano z ostrzeżeniem sumy: {nazwa_pliku}\n{info_sumy}{tryb_info}"
            self.status_text_pz.color = ft.Colors.AMBER_ACCENT
        else:
            self.status_text_pz.value = f"ℹ️ Zapisano: {nazwa_pliku}\n{info_sumy}{tryb_info}"
            self.status_text_pz.color = ft.Colors.CYAN_ACCENT

        self.btn_udostepnij_pz.visible = True
        await self.udostepnij_plik(sciezka_edi)

        sciezka_foto = self.aktualne_zdjecie_pz.get("sciezka")
        if sciezka_foto and os.path.exists(sciezka_foto):
            try:
                os.remove(sciezka_foto)
                self.ui.dopisz_log(f"Automatycznie usunięto przetworzone zdjęcie: {os.path.basename(sciezka_foto)}")
            except Exception as err:
                self.ui.dopisz_log(f"Nie udało się usunąć zdjęcia po EDI: {err}", ft.Colors.AMBER)

        self.stan_weryfikacji["dane"] = None
        self.btn_wroc_weryfikacja_pz.visible = False
        self.aktualne_zdjecie_pz["sciezka"] = None
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = config.PUSTY_OBRAZ
        self.ustaw_stan_przycisku_foto_pz(False)
        self.page.update()

    async def udostepnij_plik(self, sciezka: str):
        if not sciezka or not os.path.exists(sciezka):
            self.ui.pokaz_okno_bledu("Błąd", "Plik do udostępnienia nie istnieje.")
            return
        try:
            if hasattr(self.serwis_udostepniania, "share_files"):
                try:
                    await self.serwis_udostepniania.share_files([ft.ShareFile.from_path(sciezka)], text="Plik z ocrLmm")
                except Exception:
                    await self.serwis_udostepniania.share_files([sciezka])
            else:
                self.ui.pokaz_okno_bledu("Informacja", f"Plik zapisano pod ścieżką:\n{sciezka}")
        except Exception as err:
            self.ui.pokaz_okno_bledu("Błąd udostępniania", str(err))

    # --- PEŁNY SILNIK ANALIZY PZ ---
    async def przetworz_plik_pz(self, sciezka_obrazu: str):
        if self.blokada_analizy: return
        if not sciezka_obrazu or not os.path.exists(sciezka_obrazu):
            self.ui.pokaz_okno_bledu("Brak pliku", "Wskazane zdjęcie nie istnieje na dysku. Wybierz plik ponownie.")
            self.usun_wybrane_zdjecie_pz(None)
            return

        self.blokada_analizy = True
        self.stan_weryfikacji["dane"] = None
        self.btn_wroc_weryfikacja_pz.visible = False
        self.ui._pozycja_scrolla_pz = 0.0
        
        try:
            self.ui.dopisz_log("Rozpoczęto analizę dokumentu.")
            aktualny_konfig = config.wczytaj_konfiguracje()
            uzywa_chmury = aktualny_konfig.get("use_cloud", True)
            uzywa_bazy = aktualny_konfig.get("use_db_matching", True)
            model_gemini = aktualny_konfig.get("gemini_model", "gemini-2.5-flash").strip()
            nazwa_silnika = model_gemini if uzywa_chmury else aktualny_konfig.get("local_model", "LM Studio")

            self.status_text_pz.value = f"Przetwarzanie dokumentu ({nazwa_silnika})..."
            self.status_text_pz.color = ft.Colors.ORANGE_ACCENT
            self.pasek_postepu_pz.visible = True
            self.btn_foto_pz.disabled = True
            self.btn_aparat_pz.disabled = True
            self.btn_akcja_analiza_pz.visible = False
            self.btn_usun_zdjecie_pz.visible = False
            self.btn_udostepnij_pz.visible = False
            self.wiersz_obrotu_pz.visible = False
            self.page.update()

            loop = asyncio.get_running_loop()

            if not uzywa_chmury:
                ip_lokalne = aktualny_konfig.get("local_ip", "192.168.1.154").strip()
                port_str = aktualny_konfig.get("local_port", "1234").strip()
                mac_adres = aktualny_konfig.get("wol_mac", "").strip()
                port_lokalny = int(port_str) if port_str.isdigit() else 1234

                self.ui.dopisz_log(f"Sprawdzanie stanu serwera LM Studio ({ip_lokalne}:{port_lokalny})...")
                serwer_zyje = await core.sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0)
                if not serwer_zyje:
                    self.ui.dopisz_log("Serwer lokalny nie odpowiada. Wysyłanie pingu Wake-on-LAN...", ft.Colors.AMBER)
                    try:
                        await loop.run_in_executor(None, core.wyslij_wol, mac_adres, ip_lokalne)
                        self.ui.dopisz_log("Pakiet WoL wysłany. Czekam na załadowanie LM Studio...", ft.Colors.CYAN)
                    except Exception as e_wol:
                        self.ui.dopisz_log(f"Błąd wysyłania WoL: {e_wol}", ft.Colors.RED)

                    maks_czas_oczekiwania = 150
                    interwal_sprawdzania = 10
                    czas_miniony = 0

                    while czas_miniony < maks_czas_oczekiwania:
                        self.status_text_pz.value = f"Oczekiwanie na uruchomienie LM Studio... ({czas_miniony}/{maks_czas_oczekiwania}s)"
                        self.status_text_pz.color = ft.Colors.CYAN_ACCENT
                        self.page.update()

                        await asyncio.sleep(interwal_sprawdzania)
                        czas_miniony += interwal_sprawdzania

                        if czas_miniony % 30 == 0:
                            try:
                                await loop.run_in_executor(None, core.wyslij_wol, mac_adres, ip_lokalne)
                            except Exception:
                                pass

                        if await core.sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0):
                            serwer_zyje = True
                            self.ui.dopisz_log(f"Serwer LM Studio gotowy do pracy po {czas_miniony}s!", ft.Colors.GREEN)
                            break

                    if not serwer_zyje:
                        raise TimeoutError(f"Serwer pod adresem {ip_lokalne} nie uruchomił się w czasie {maks_czas_oczekiwania}s.")

            self.ui.dopisz_log("Przygotowywanie i kompresja obrazu...")
            wymiar_obrazu = aktualny_konfig.get("image_resolution", 1800)
            base64_image = await loop.run_in_executor(None, core.kompresuj_do_base64, sciezka_obrazu, wymiar_obrazu)

            prompt = (
                "Jesteś precyzyjnym systemem OCR do polskich faktur i specyfikacji spożywczych (wędliny, mięso, nabiał, pieczywo). "
                "Przepisz DOKŁADNIE dane ze zdjęcia dokumentu. Nie zmyślaj danych!\n\n"
                "Instrukcje:\n"
                "1. Nagłówek:\n"
                "   - nr: odczytaj pełny numer dokumentu (faktury / PZ)\n"
                "   - dt: data wystawienia/sprzedaży w formacie DD.MM.RRRR\n"
                "   - w, o: nazwa oraz NIP (same cyfry, bez przedrostka 'PL', spacji i myślników) wystawcy (w) i odbiorcy (o)\n\n"
                "2. Tabela towarowa (Przepisz DOKŁADNIE każdy wiersz towarowy):\n"
                "   - n: pełna nazwa towaru (dokładnie jak na dokumencie)\n"
                "   - k: kod kreskowy EAN lub indeks. Pamiętaj, że standardowe kody EAN mają zazwyczaj dokładnie 13 cyfr (EAN-13), a mniejsze opakowania lub kody skrócone 8 cyfr (EAN-8). Odczytaj je bardzo uważnie, cyfra po cyfrze, bez pomijania znaków.\n"
                "   - j: jednostka miary ('kg', 'szt', 'op')\n"
                "   - i: ilość/waga:\n"
                "        * Jeśli j='szt': ilość MUSI być liczbą całkowitą (np. 1, 10, 24)\n"
                "        * Jeśli j='kg': ilość może być ułamkiem dziesiętnym z kropką (np. 1.450)\n"
                "   - c: ostateczna cena jednostkowa netto PO RABACIE\n"
                "   - w: wartość netto pozycji (ilość × cena netto po rabacie)\n"
                "   - v: stawka VAT (oczekiwane: 0, 5, 8, 23, zw, np)\n\n"
                "3. Podsumowanie: odczytaj 'Razem netto' (sn) oraz stawki VAT (s) i do_zaplaty (dz).\n\n"
                "Ważne: Jako separatora dziesiętnego używaj kropki (nie przecinka). Nie wstawiaj kresek ani spacji w NIP-ie.\n\n"
                "Zwróć TYLKO i WYŁĄCZNIE czysty obiekt JSON (bez znaczników markdown, bez ```json):\n"
                "{\n"
                "  \"nr\": \"...\",\n"
                "  \"dt\": \"DD.MM.RRRR\",\n"
                "  \"w\": {\"n\": \"...\", \"nip\": \"...\"},\n"
                "  \"o\": {\"n\": \"...\", \"nip\": \"...\"},\n"
                "  \"p\": [\n"
                "    {\"n\": \"...\", \"k\": \"...\", \"v\": \"5\", \"j\": \"kg\", \"i\": \"0.000\", \"c\": \"0.00\", \"w\": \"0.00\"}\n"
                "  ],\n"
                "  \"sn\": \"0.00\",\n"
                "  \"s\": [{\"v\": \"5\", \"sn\": \"0.00\", \"sv\": \"0.00\"}],\n"
                "  \"dz\": \"0.00\"\n"
                "}"
            )

            if uzywa_chmury:
                self.ui.dopisz_log("Wysyłanie danych do Google Gemini API...")
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
                self.ui.dopisz_log("Wysyłanie zapytania do LM Studio...")
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
                    "chat_template_kwargs": {"enable_thinking": False}
                }

            max_prob = 4
            opoznienie_poczatkowe = 2.0
            odpowiedz = None

            timeout_cfg = httpx.Timeout(10.0, read=300.0)

            self.status_text_pz.value = f"Przetwarzanie dokumentu przez {nazwa_silnika}..."
            self.status_text_pz.color = ft.Colors.ORANGE_ACCENT
            self.page.update()

            async with httpx.AsyncClient(timeout=timeout_cfg, verify=True) as client:
                for proba in range(max_prob):
                    self.ui.dopisz_log(f"Trwa odczytywanie tekstu przez LLM (próba {proba + 1}/{max_prob})...")
                    odpowiedz = await client.post(
                        pelny_url,
                        headers=naglowki,
                        json=cialo_zapytania
                    )

                    if odpowiedz.status_code in [503, 429]:
                        if proba < max_prob - 1:
                            czas_oczekiwania = opoznienie_poczatkowe * (2 ** proba)
                            self.status_text_pz.value = f"Serwer zajęty ({odpowiedz.status_code}). Ponawianie {proba + 1}/{max_prob} za {czas_oczekiwania:.1f}s..."
                            self.status_text_pz.color = ft.Colors.AMBER_ACCENT
                            self.ui.dopisz_log(f"Kod {odpowiedz.status_code}. Ponawianie za {czas_oczekiwania:.1f}s.", ft.Colors.AMBER)
                            self.page.update()
                            await asyncio.sleep(czas_oczekiwania)
                            continue

                    odpowiedz.raise_for_status()
                    break

                self.ui.dopisz_log("Pobrano odpowiedź. Odkodowywanie JSON...")
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
                self.ui.dopisz_log(opis_tokenow, ft.Colors.CYAN if powod_konca != "length" else ft.Colors.RED)

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
                self.ui.dopisz_log(f"BŁĄD PARSOWANIA JSON: {blad_parsowania}", ft.Colors.RED)
                self.ui.dopisz_log(f"Zwrócony tekst przez model:\n{odp_tekst}", ft.Colors.ORANGE)
                if powod_konca == "length":
                    raise ValueError(
                        f"Odpowiedź modelu została ucięta po osiągnięciu limitu tokenów "
                        f"(obraz {wymiar_obrazu}px). Zobacz w konsoli, czy model nie zapętlił się."
                    )
                raise ValueError(f"Błąd parsowania JSON ({blad_parsowania}). Sprawdź konsolę logów.")

            dane = core.oczysc_odpowiedz_llm(dane)

            self.ui.dopisz_log("Dopasowywanie pozycji do bazy PC-Market (w osobnym wątku)...")
            aktualna_baza_sciezka = config.pobierz_aktualna_sciezke_bazy(aktualny_konfig)
            baza_towarowa, dane, status_sum, info_sumy = await loop.run_in_executor(
                None, core.dopasuj_wszystkie_pozycje_w_tle, dane, uzywa_bazy, aktualna_baza_sciezka
            )

            self.stan_weryfikacji["dane"] = dane
            self.stan_weryfikacji["baza"] = baza_towarowa
            self.stan_weryfikacji["uzywa_bazy"] = uzywa_bazy
            self.stan_weryfikacji["status_sum"] = status_sum
            self.stan_weryfikacji["info_sumy"] = info_sumy
            self.stan_weryfikacji["indeks_edytowany"] = -1

            self.ui.dopisz_log("Przygotowano okno weryfikacji.")
            self.status_text_pz.value = "Oczekiwanie na potwierdzenie kodów..."
            self.status_text_pz.color = ft.Colors.CYAN_ACCENT
            self.pasek_postepu_pz.visible = False
            self.btn_wroc_weryfikacja_pz.visible = True
            self.page.update()

            self.ui.odswiez_weryfikacje()
            self.ui.bezpiecznie_otworz_dialog(self.ui.dlg_weryfikacja)

        except httpx.HTTPStatusError as http_err:
            status = http_err.response.status_code
            tresc = http_err.response.text[:350]
            self.ui.dopisz_log(f"Błąd HTTP {status}: {tresc}", ft.Colors.RED)
            if status in (401, 403) or "API_KEY_INVALID" in tresc:
                self.status_text_pz.value = "Błąd autoryzacji API"
                self.ui.pokaz_okno_bledu("🔑 Błąd autoryzacji", "Klucz API jest nieprawidłowy lub brak uprawnień. Sprawdź ustawienia (zębatka).")
            elif status == 429:
                self.status_text_pz.value = "Limit zapytań wyczerpany"
                self.ui.pokaz_okno_bledu("⏳ Limit zapytań wyczerpany", "Zbyt wiele zapytań w krótkim czasie. Odczekaj 30 sekund.")
            elif status >= 500:
                self.status_text_pz.value = "Serwer AI niedostępny"
                self.ui.pokaz_okno_bledu("⏳ Serwer AI niedostępny", f"Serwer zwrócił kod {status}. Odczekaj chwilę i spróbuj ponownie.")
            else:
                self.status_text_pz.value = f"Błąd zapytania HTTP {status}"
                self.ui.pokaz_okno_bledu("❌ Błąd zapytania HTTP", f"Status: {status}\n{tresc}")
        except httpx.TimeoutException:
            self.status_text_pz.value = "Limit czasu przekroczony"
            self.ui.pokaz_okno_bledu("⏳ Limit czasu", "Model nie odpowiedział w wyznaczonym czasie.")
        except Exception as err:
            self.ui.dopisz_log(f"Błąd przetwarzania: {err}", ft.Colors.RED)
            self.status_text_pz.value = f"Błąd: {err}"
            self.status_text_pz.color = ft.Colors.RED_ACCENT
            self.ui.pokaz_okno_bledu("❌ Błąd przetwarzania", str(err))
        finally:
            self.blokada_analizy = False
            self.pasek_postepu_pz.visible = False
            self.btn_foto_pz.disabled = False
            self.btn_aparat_pz.disabled = False
            czy_ma_foto = bool(self.aktualne_zdjecie_pz["sciezka"])
            self.btn_akcja_analiza_pz.visible = czy_ma_foto
            self.btn_usun_zdjecie_pz.visible = czy_ma_foto
            self.wiersz_obrotu_pz.visible = czy_ma_foto
            self.page.update()

    # =========================================================================
    # 2. MODUŁ II: DOKUMENT (UKŁAD 1:1, NOWY STYL KAFELKOWY)
    # =========================================================================
    def _inicjalizuj_modul_dokument(self):
        self.podglad_dok = ft.Image(
            src=config.PUSTY_OBRAZ,
            visible=False,
            fit="contain",
            height=200,
            border_radius=8
        )

        self.wiersz_obrotu_dok = ft.Row([
            ft.Button(
                "Obróć w lewo", icon=ft.Icons.ROTATE_LEFT, height=48, expand=True,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=lambda e: asyncio.create_task(self.obroc_dok(90))
            ),
            ft.Button(
                "Obróć w prawo", icon=ft.Icons.ROTATE_RIGHT, height=48, expand=True,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=lambda e: asyncio.create_task(self.obroc_dok(-90))
            )
        ], spacing=10, visible=False)

        self.status_dok = ft.Text(
            "Zrób zdjęcie lub wybierz dokument do odczytu układu 1:1.",
            size=13, color=ft.Colors.BLUE_200, text_align=ft.TextAlign.CENTER
        )
        self.pasek_dok = ft.ProgressBar(visible=False, color=ft.Colors.BLUE_ACCENT)

        self.txt_edytor_dok = ft.TextField(
            multiline=True,
            min_lines=12,
            max_lines=25,
            text_size=12,
            dense=True,
            border_color=ft.Colors.BLUE_GREY_700,
            bgcolor=ft.Colors.GREY_900,
            border_radius=8,
            visible=False
        )

        self.btn_start_dok = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.PLAY_ARROW, size=24),
                ft.Text("Odczytaj tekst dokumentu", size=15, weight=ft.FontWeight.BOLD)
            ], alignment=ft.MainAxisAlignment.CENTER),
            height=54,
            disabled=True,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE_800,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=10)
            ),
            on_click=self.analizuj_dokument_dok
        )

        self.btn_kopiuj_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.COPY, size=20), ft.Text("Kopiuj tekst", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=50,
            expand=True,
            visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.kopiuj_do_schowka_dok
        )

        self.btn_zapisz_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.SHARE, size=20), ft.Text("Udostępnij .TXT", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=50,
            expand=True,
            visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.udostepnij_tekst_dok
        )

        self.widok_dokument = ft.Column([
            ft.Row([
                ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: self.przelacz_widok("menu")),
                ft.Column([
                    ft.Text("Odczyt Dokumentu", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_400),
                    ft.Text("Zachowanie oryginalnego układu (1:1)", size=12, color=ft.Colors.GREY_400)
                ], spacing=2)
            ]),
            ft.Row([
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("Galeria", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
                    height=52,
                    expand=True,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
                    on_click=self.wybierz_foto_dok
                ),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Aparat", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
                    height=52,
                    expand=True,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
                    on_click=lambda e: asyncio.create_task(self.ui.otworz_aparat_dla("dokument"))
                )
            ], spacing=10),
            self.pasek_dok,
            self.status_dok,
            self.btn_start_dok,
            self.podglad_dok,
            self.wiersz_obrotu_dok,
            ft.Row([self.btn_kopiuj_dok, self.btn_zapisz_dok], spacing=10),
            self.txt_edytor_dok,
            ft.Container(height=40)
        ], spacing=12, visible=False)

    def ustaw_nowy_obraz_dok(self, sciezka: str):
        nowa = os.path.join(config.KATALOG_DANYCH, f"img_dok_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        shutil.copyfile(sciezka, nowa)
        self.zdjecie_dok["sciezka"] = nowa
        self.podglad_dok.src = nowa
        self.podglad_dok.visible = True
        self.wiersz_obrotu_dok.visible = True
        self.btn_start_dok.disabled = False
        self.status_dok.value = "Zdjęcie załadowane. Kliknij 'Odczytaj tekst dokumentu'."
        self.page.update()

    async def obroc_dok(self, kat: int):
        if not self.zdjecie_dok["sciezka"] or not os.path.exists(self.zdjecie_dok["sciezka"]):
            return
        nowa_sciezka = await asyncio.get_running_loop().run_in_executor(
            None, core.obroc_plik_graficzny, self.zdjecie_dok["sciezka"], kat, "rot_dok"
        )
        self.zdjecie_dok["sciezka"] = nowa_sciezka
        self.podglad_dok.src = nowa_sciezka
        self.status_dok.value = f"Obrócono dokument o {kat}°."
        self.page.update()

    async def analizuj_dokument_dok(self, e):
        if not self.zdjecie_dok["sciezka"]:
            return
        self.btn_start_dok.disabled = True
        self.pasek_dok.visible = True
        self.status_dok.value = "Model AI rekonstruuje tekst z zachowaniem układu..."
        self.page.update()

        prompt_dok = (
            "Przepisz CAŁY tekst ze zdjęcia z ZACHOWANIEM DOKŁADNEGO UKŁADU PRZESTRZENNEGO: "
            "kolumn, wcięć, wierszy i tabel. Nie dodawaj komentarzy, ani znaczników markdown."
        )
        try:
            cfg = config.wczytaj_konfiguracje()
            base64_image = await asyncio.get_running_loop().run_in_executor(
                None, core.kompresuj_do_base64, self.zdjecie_dok["sciezka"], cfg.get("image_resolution", 1800)
            )
            if cfg.get("use_cloud", True):
                url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                headers = {"Authorization": f"Bearer {cfg.get('gemini_api_key', '')}", "Content-Type": "application/json"}
                payload = {
                    "model": cfg.get("gemini_model", "gemini-2.5-flash"),
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_dok}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                    "temperature": 0.0,
                    "max_tokens": 8192
                }
            else:
                url = f"http://{cfg.get('local_ip')}:{cfg.get('local_port')}/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
                if cfg.get("local_api_key"):
                    headers["Authorization"] = f"Bearer {cfg.get('local_api_key')}"
                payload = {
                    "model": cfg.get("local_model", "qwen3.5-9b"),
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_dok}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                    "temperature": 0.0,
                    "chat_template_kwargs": {"enable_thinking": False}
                }

            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=300.0)) as client:
                res = await client.post(url, headers=headers, json=payload)
                res.raise_for_status()
                dane_odp = res.json()
                self.txt_edytor_dok.value = dane_odp["choices"][0]["message"]["content"].strip()
                self.txt_edytor_dok.visible = True
                self.btn_kopiuj_dok.visible = True
                self.btn_zapisz_dok.visible = True
                self.status_dok.value = "✅ Sukces! Układ został zrekonstruowany poniżej."

                uzycie = dane_odp.get("usage") or {}
                self.ui.dopisz_log(f"Dokument OCR: wejście={uzycie.get('prompt_tokens', '?')}, wyjście={uzycie.get('completion_tokens', '?')}", ft.Colors.CYAN)
        except Exception as err:
            self.ui.pokaz_okno_bledu("Błąd odczytu dokumentu", str(err))
        finally:
            self.pasek_dok.visible = False
            self.btn_start_dok.disabled = False
            self.page.update()

    async def kopiuj_do_schowka_dok(self, e):
        await ft.Clipboard().set(self.txt_edytor_dok.value)
        self.status_dok.value = "📋 Skopiowano do schowka!"
        self.page.update()

    async def udostepnij_tekst_dok(self, e):
        sciezka_txt = os.path.join(config.KATALOG_DANYCH, f"dok_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(sciezka_txt, "w", encoding="utf-8") as f:
            f.write(self.txt_edytor_dok.value)
        await self.udostepnij_plik(sciezka_txt)

    async def wybierz_foto_dok(self, e):
        pliki = await self.pickery["foto"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
        if pliki and len(pliki) > 0 and pliki[0].path:
            self.ustaw_nowy_obraz_dok(pliki[0].path)

    # =========================================================================
    # 3. MODUŁ III: SZYBKI SKANER GRAFICZNY (DOTYK, PRZESUWANIE ŚRODKIEM, COFANIE)
    # =========================================================================
    def _inicjalizuj_modul_skanera(self):
        self.SZEROKOSC_SKAN = 320
        self.WYSOKOSC_SKAN = 420
        self.UCHWYT_ROZMIAR = 48  # Większy obszar dotykowy dla wygody palca

        # Współrzędne ramki w pikselach
        self.crop_x1 = 0.0
        self.crop_y1 = 0.0
        self.crop_x2 = float(self.SZEROKOSC_SKAN)
        self.crop_y2 = float(self.WYSOKOSC_SKAN)

        # Historia kroków do cofania
        self.historia_skan = []
        self.ostatni_aktywny_filtr = None
        
        self.podglad_skan = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit="fill",
            width=self.SZEROKOSC_SKAN,
            height=self.WYSOKOSC_SKAN
        )

        # Maski zaciemniające
        self.maska_gora = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, left=0, width=self.SZEROKOSC_SKAN, height=0)
        self.maska_dol = ft.Container(bgcolor=ft.Colors.BLACK54, bottom=0, left=0, width=self.SZEROKOSC_SKAN, height=0)
        self.maska_lewo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, left=0, width=0)
        self.maska_prawo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, right=0, width=0)

        # Środek ramki – dotyk i przesuwanie całego kadru
        self.strefa_srodka = ft.GestureDetector(
            content=ft.Container(
                border=ft.Border.all(2.0, ft.Colors.ORANGE_ACCENT),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ORANGE_ACCENT)
            ),
            drag_interval=10,
            on_pan_update=lambda e: self._przesun_caly_kadr(*self._pobierz_deltas(e)),
            top=0, left=0, width=self.SZEROKOSC_SKAN, height=self.WYSOKOSC_SKAN
        )

        # 4 narożniki dotykowe
        def stworz_uchwyt():
            return ft.Container(
                alignment=ft.Alignment(0, 0),
                content=ft.Container(
                    width=28, height=28,
                    bgcolor=ft.Colors.ORANGE_ACCENT,
                    border_radius=14,
                    border=ft.Border.all(2.5, ft.Colors.WHITE)
                ),
                width=self.UCHWYT_ROZMIAR,
                height=self.UCHWYT_ROZMIAR
            )

        self.uchwyt_lt = ft.GestureDetector(
            content=stworz_uchwyt(), drag_interval=10,
            on_pan_update=lambda e: self._przesun_uchwyt("lt", *self._pobierz_deltas(e)),
            top=0, left=0
        )
        self.uchwyt_rt = ft.GestureDetector(
            content=stworz_uchwyt(), drag_interval=10,
            on_pan_update=lambda e: self._przesun_uchwyt("rt", *self._pobierz_deltas(e)),
            top=0, left=self.SZEROKOSC_SKAN - self.UCHWYT_ROZMIAR
        )
        self.uchwyt_lb = ft.GestureDetector(
            content=stworz_uchwyt(), drag_interval=10,
            on_pan_update=lambda e: self._przesun_uchwyt("lb", *self._pobierz_deltas(e)),
            top=self.WYSOKOSC_SKAN - self.UCHWYT_ROZMIAR, left=0
        )
        self.uchwyt_rb = ft.GestureDetector(
            content=stworz_uchwyt(), drag_interval=10,
            on_pan_update=lambda e: self._przesun_uchwyt("rb", *self._pobierz_deltas(e)),
            top=self.WYSOKOSC_SKAN - self.UCHWYT_ROZMIAR, left=self.SZEROKOSC_SKAN - self.UCHWYT_ROZMIAR
        )

        self.ramka_skanera = ft.Container(
            content=ft.Stack([
                self.podglad_skan,
                self.maska_gora, self.maska_dol, self.maska_lewo, self.maska_prawo,
                self.strefa_srodka,
                self.uchwyt_lt, self.uchwyt_rt, self.uchwyt_lb, self.uchwyt_rb
            ]),
            width=self.SZEROKOSC_SKAN,
            height=self.WYSOKOSC_SKAN,
            alignment=ft.Alignment(0, 0),
            visible=False
        )

        self.status_skan = ft.Text(
            "Wczytaj skan, aby wykadrować i nałożyć filtry.",
            size=13, color=ft.Colors.ORANGE_200, text_align=ft.TextAlign.CENTER
        )

        self.wiersz_obrotu_skan = ft.Row([
            ft.Button(
                "Obróć w lewo", icon=ft.Icons.ROTATE_LEFT, height=48, expand=True,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=lambda e: asyncio.create_task(self.obroc_skan(90))
            ),
            ft.Button(
                "Obróć w prawo", icon=ft.Icons.ROTATE_RIGHT, height=48, expand=True,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=lambda e: asyncio.create_task(self.obroc_skan(-90))
            )
        ], spacing=10, visible=False)

        # Przycisk cofania ostatniego nałożonego efektu
        self.btn_cofnij_filtr = ft.Button(
            "Cofnij ostatni krok", icon=ft.Icons.UNDO, height=48, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            disabled=True,
            on_click=self.cofnij_ostatni_krok_skan
        )

        self.btn_filtr_bw = ft.Button(
            "B&W", height=48, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.przelacz_filtr_skan("bw"))
        )
        self.btn_filtr_szary = ft.Button(
            "Szary", height=48, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_800, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.przelacz_filtr_skan("szary"))
        )
        self.btn_filtr_wyostrz = ft.Button(
            "Wyostrz", height=48, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.TEAL_900, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.przelacz_filtr_skan("wyostrz"))
        )

        self.kontener_akcji_skanu = ft.Column([
            ft.Button(
                content=ft.Row([ft.Icon(ft.Icons.CROP, size=22), ft.Text("Wytnij zaznaczony kadr", size=15, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
                height=54,
                style=ft.ButtonStyle(bgcolor=ft.Colors.ORANGE_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)),
                on_click=self.przytnij_zaznaczenie
            ),
            ft.Divider(height=16),
            ft.Text("Filtry kontrastowe (kliknij ponownie ten sam, by go cofnąć):", size=12, weight=ft.FontWeight.BOLD),
            ft.Row([self.btn_filtr_bw, self.btn_filtr_szary], spacing=8),
            ft.Row([self.btn_filtr_wyostrz]),
            ft.Row([self.btn_cofnij_filtr]),
            ft.Divider(height=16),
            ft.Button(
                content=ft.Row([ft.Icon(ft.Icons.SHARE, size=24), ft.Text("Udostępnij gotowy skan", size=16, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
                height=56,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)),
                on_click=lambda e: asyncio.create_task(self.udostepnij_plik(self.zdjecie_skan["sciezka"]))
            ),
            ft.Container(height=40)
        ], visible=False, spacing=10, tight=True)  # <--- dodany tight=True

        # Przewijalny dolny panel narzędziowy dla skanera
        self.dolny_panel_skanera = ft.ListView(
            controls=[
                self.wiersz_obrotu_skan,
                self.kontener_akcji_skanu
            ],
            spacing=10,
            expand=True,
            padding=ft.Padding(0, 5, 0, 20)
        )

        self.widok_skanera = ft.Column([
            ft.Row([
                ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: self.przelacz_widok("menu")),
                ft.Column([
                    ft.Text("Szybki Skaner Graficzny", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_400),
                    ft.Text("Złap rogi lub przesuń cały kadr za środek", size=11, color=ft.Colors.GREY_400)
                ], spacing=1)
            ]),
            ft.Row([
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("Galeria", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
                    height=48, expand=True,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
                    on_click=self.wybierz_foto_skan
                ),
                ft.Button(
                    content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Aparat", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
                    height=48, expand=True,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
                    on_click=lambda e: asyncio.create_task(self.ui.otworz_aparat_dla("skaner"))
                )
            ], spacing=10),
            self.status_skan,
            self.ramka_skanera,         # Nieruchomy podgląd - gesty rogów i środka łapią natychmiast!
            self.dolny_panel_skanera    # Niezależny dolny scroll dla przycisków
        ], spacing=8, expand=True, visible=False)

    def _pobierz_deltas(self, e):
        dx = getattr(e, "delta", None)
        if dx is not None:
            return e.delta.x, e.delta.y
        loc = getattr(e, "local_delta", None)
        if loc is not None:
            return e.local_delta.x, e.local_delta.y
        return getattr(e, "delta_x", 0.0), getattr(e, "delta_y", 0.0)

    def _przesun_uchwyt(self, ktory: str, dx: float, dy: float):
        min_rozmiar = 40.0
        if ktory == "lt":
            self.crop_x1 = max(0.0, min(self.crop_x1 + dx, self.crop_x2 - min_rozmiar))
            self.crop_y1 = max(0.0, min(self.crop_y1 + dy, self.crop_y2 - min_rozmiar))
        elif ktory == "rt":
            self.crop_x2 = min(float(self.SZEROKOSC_SKAN), max(self.crop_x2 + dx, self.crop_x1 + min_rozmiar))
            self.crop_y1 = max(0.0, min(self.crop_y1 + dy, self.crop_y2 - min_rozmiar))
        elif ktory == "lb":
            self.crop_x1 = max(0.0, min(self.crop_x1 + dx, self.crop_x2 - min_rozmiar))
            self.crop_y2 = min(float(self.WYSOKOSC_SKAN), max(self.crop_y2 + dy, self.crop_y1 + min_rozmiar))
        elif ktory == "rb":
            self.crop_x2 = min(float(self.SZEROKOSC_SKAN), max(self.crop_x2 + dx, self.crop_x1 + min_rozmiar))
            self.crop_y2 = min(float(self.WYSOKOSC_SKAN), max(self.crop_y2 + dy, self.crop_y1 + min_rozmiar))

        self._odswiez_pozycje_ramki()

    def _przesun_caly_kadr(self, dx: float, dy: float):
        szerokosc = self.crop_x2 - self.crop_x1
        wysokosc = self.crop_y2 - self.crop_y1

        nowe_x1 = self.crop_x1 + dx
        nowe_y1 = self.crop_y1 + dy

        if nowe_x1 < 0:
            nowe_x1 = 0
        elif nowe_x1 + szerokosc > self.SZEROKOSC_SKAN:
            nowe_x1 = self.SZEROKOSC_SKAN - szerokosc

        if nowe_y1 < 0:
            nowe_y1 = 0
        elif nowe_y1 + wysokosc > self.WYSOKOSC_SKAN:
            nowe_y1 = self.WYSOKOSC_SKAN - wysokosc

        self.crop_x1 = nowe_x1
        self.crop_y1 = nowe_y1
        self.crop_x2 = nowe_x1 + szerokosc
        self.crop_y2 = nowe_y1 + wysokosc

        self._odswiez_pozycje_ramki()

    def _odswiez_pozycje_ramki(self):
        w = max(1.0, self.crop_x2 - self.crop_x1)
        h = max(1.0, self.crop_y2 - self.crop_y1)

        self.strefa_srodka.left = self.crop_x1
        self.strefa_srodka.top = self.crop_y1
        self.strefa_srodka.width = w
        self.strefa_srodka.height = h

        self.maska_gora.height = self.crop_y1
        self.maska_dol.top = self.crop_y2
        self.maska_dol.height = max(0.0, self.WYSOKOSC_SKAN - self.crop_y2)

        self.maska_lewo.top = self.crop_y1
        self.maska_lewo.height = h
        self.maska_lewo.width = self.crop_x1

        self.maska_prawo.top = self.crop_y1
        self.maska_prawo.height = h
        self.maska_prawo.left = self.crop_x2
        self.maska_prawo.width = max(0.0, self.SZEROKOSC_SKAN - self.crop_x2)

        pol = self.UCHWYT_ROZMIAR / 2
        self.uchwyt_lt.left = max(0.0, self.crop_x1 - pol)
        self.uchwyt_lt.top = max(0.0, self.crop_y1 - pol)

        self.uchwyt_rt.left = min(self.SZEROKOSC_SKAN - self.UCHWYT_ROZMIAR, self.crop_x2 - pol)
        self.uchwyt_rt.top = max(0.0, self.crop_y1 - pol)

        self.uchwyt_lb.left = max(0.0, self.crop_x1 - pol)
        self.uchwyt_lb.top = min(self.WYSOKOSC_SKAN - self.UCHWYT_ROZMIAR, self.crop_y2 - pol)

        self.uchwyt_rb.left = min(self.SZEROKOSC_SKAN - self.UCHWYT_ROZMIAR, self.crop_x2 - pol)
        self.uchwyt_rb.top = min(self.WYSOKOSC_SKAN - self.UCHWYT_ROZMIAR, self.crop_y2 - pol)

        self.page.update()

    def ustaw_nowy_obraz_skan(self, sciezka: str):
        nowa = os.path.join(config.KATALOG_DANYCH, f"img_skan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        shutil.copyfile(sciezka, nowa)
        self.zdjecie_skan["oryginal"] = str(nowa)
        self.zdjecie_skan["sciezka"] = str(nowa)
        self.historia_skan = []
        self.ostatni_aktywny_filtr = None
        self.btn_cofnij_filtr.disabled = True

        self.podglad_skan.src_base64 = None
        self.podglad_skan.src = str(nowa)
        self.ramka_skanera.visible = True
        self.kontener_akcji_skanu.visible = True
        self.wiersz_obrotu_skan.visible = True

        self.crop_x1 = 0.0
        self.crop_y1 = 0.0
        self.crop_x2 = float(self.SZEROKOSC_SKAN)
        self.crop_y2 = float(self.WYSOKOSC_SKAN)
        self._odswiez_pozycje_ramki()

        self.status_skan.value = "Przeciągaj punkty narożne lub złap za środek, aby przesunąć kadr."
        self.page.update()

    async def obroc_skan(self, kat: int):
        if not self.zdjecie_skan["sciezka"] or not os.path.exists(self.zdjecie_skan["sciezka"]):
            return
        nowa_sciezka = await asyncio.get_running_loop().run_in_executor(
            None, core.obroc_plik_graficzny, str(self.zdjecie_skan["sciezka"]), kat, "rot_skan"
        )
        self.zdjecie_skan["sciezka"] = str(nowa_sciezka)
        self.zdjecie_skan["oryginal"] = str(nowa_sciezka)
        self.historia_skan = []
        self.ostatni_aktywny_filtr = None
        self.btn_cofnij_filtr.disabled = True
        self.podglad_skan.src_base64 = None
        self.podglad_skan.src = str(nowa_sciezka)

        self.crop_x1 = 0.0
        self.crop_y1 = 0.0
        self.crop_x2 = float(self.SZEROKOSC_SKAN)
        self.crop_y2 = float(self.WYSOKOSC_SKAN)
        self._odswiez_pozycje_ramki()

        self.status_skan.value = f"Obrócono skan o {kat}°."
        self.page.update()

    async def przytnij_zaznaczenie(self, e):
        if not self.zdjecie_skan["oryginal"]:
            return

        proc_lewo = (self.crop_x1 / self.SZEROKOSC_SKAN) * 100.0
        proc_gora = (self.crop_y1 / self.WYSOKOSC_SKAN) * 100.0
        proc_prawo = ((self.SZEROKOSC_SKAN - self.crop_x2) / self.SZEROKOSC_SKAN) * 100.0
        proc_dol = ((self.WYSOKOSC_SKAN - self.crop_y2) / self.WYSOKOSC_SKAN) * 100.0

        # Zapisujemy stan sprzed przycięcia jako stringi w krotce
        self.historia_skan.append((str(self.zdjecie_skan["sciezka"]), str(self.zdjecie_skan["oryginal"])))
        self.btn_cofnij_filtr.disabled = False
        self.ostatni_aktywny_filtr = None

        nowa_sciezka = await asyncio.get_running_loop().run_in_executor(
            None, core.kadruj_plik_graficzny, str(self.zdjecie_skan["oryginal"]),
            proc_lewo, proc_gora, proc_prawo, proc_dol
        )

        self.zdjecie_skan["sciezka"] = str(nowa_sciezka)
        self.zdjecie_skan["oryginal"] = str(nowa_sciezka)
        self.podglad_skan.src_base64 = None
        self.podglad_skan.src = str(nowa_sciezka)

        self.crop_x1 = 0.0
        self.crop_y1 = 0.0
        self.crop_x2 = float(self.SZEROKOSC_SKAN)
        self.crop_y2 = float(self.WYSOKOSC_SKAN)
        self._odswiez_pozycje_ramki()

        self.status_skan.value = "✅ Przycięto kadr! Możesz nakładać filtry lub cofnąć cięcie."
        self.page.update()

    async def przelacz_filtr_skan(self, typ: str):
        if not self.zdjecie_skan["sciezka"]:
            return

        # 1. Jeśli kliknięto ponownie TEN SAM filtr -> bezpieczne cofnięcie
        if self.ostatni_aktywny_filtr == typ and self.historia_skan:
            self.cofnij_ostatni_krok_skan(None)
            return

        # 2. Zapisz bieżący stan na stosie
        self.historia_skan.append((str(self.zdjecie_skan["sciezka"]), str(self.zdjecie_skan["oryginal"])))
        self.btn_cofnij_filtr.disabled = False

        # 3. Nałóż filtr (pewny czysty string dla Pillow)
        sciezka_do_filtru = str(self.zdjecie_skan["sciezka"])
        nowa_sciezka = await asyncio.get_running_loop().run_in_executor(
            None, core.filtruj_plik_graficzny, sciezka_do_filtru, typ
        )

        self.zdjecie_skan["sciezka"] = str(nowa_sciezka)
        self.podglad_skan.src_base64 = None
        self.podglad_skan.src = str(nowa_sciezka)
        self.ostatni_aktywny_filtr = typ
        self.status_skan.value = f"✅ Zastosowano filtr: {typ} (kliknij ponownie ten sam, by go cofnąć)."
        self.page.update()

    def cofnij_ostatni_krok_skan(self, e=None):
        if not self.historia_skan:
            return

        # Rozpakowujemy krotkę do dwóch niezależnych stringów
        poprzednia_sciezka, poprzedni_oryginal = self.historia_skan.pop()

        czy_cofamy_przyciecie = (str(self.zdjecie_skan["oryginal"]) != str(poprzedni_oryginal))

        self.zdjecie_skan["sciezka"] = str(poprzednia_sciezka)
        self.zdjecie_skan["oryginal"] = str(poprzedni_oryginal)
        self.podglad_skan.src_base64 = None
        self.podglad_skan.src = str(poprzednia_sciezka)

        if czy_cofamy_przyciecie:
            self.crop_x1 = 0.0
            self.crop_y1 = 0.0
            self.crop_x2 = float(self.SZEROKOSC_SKAN)
            self.crop_y2 = float(self.WYSOKOSC_SKAN)
            self._odswiez_pozycje_ramki()
            self.status_skan.value = "↩️ Cofnięto przycięcie kadru."
        else:
            self.status_skan.value = "↩️ Cofnięto ostatni filtr."

        self.ostatni_aktywny_filtr = None
        self.btn_cofnij_filtr.disabled = (len(self.historia_skan) == 0)
        self.page.update()

    async def wybierz_foto_skan(self, e):
        pliki = await self.pickery["foto"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
        if pliki and len(pliki) > 0 and pliki[0].path:
            self.ustaw_nowy_obraz_skan(pliki[0].path)

    # =========================================================================
    # 4. MENU GŁÓWNE (HUB STARTOWY)
    # =========================================================================
    def _inicjalizuj_menu_glowne(self):
        def kafel_wyboru(tytul: str, podtytul: str, ikona, bg_kolor, ikona_kolor, cel):
            return ft.Container(
                content=ft.Row([
                    ft.Icon(ikona, size=36, color=ikona_kolor),
                    ft.Column([
                        ft.Text(tytul, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        ft.Text(podtytul, size=12, color=ft.Colors.GREY_300)
                    ], expand=True, spacing=2)
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=16,
                bgcolor=bg_kolor,
                border_radius=10,
                ink=True,
                on_click=lambda e: self.przelacz_widok(cel)
            )

        self.widok_menu = ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("ocrLmm Hub", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                    ft.Text("Wybierz moduł roboczy", size=13, color=ft.Colors.GREY_400)
                ], spacing=2),
                ft.IconButton(ft.Icons.SETTINGS, tooltip="Ustawienia połączenia", on_click=self.ui.otworz_ustawienia)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            kafel_wyboru("Faktura / PZ (Dla PC-Market)", "Pełna analiza towarowa, kody, sumy, baza i generowanie EDI.", ft.Icons.RECEIPT_LONG, ft.Colors.GREEN_900, ft.Colors.GREEN_300, "pz"),
            kafel_wyboru("Odczyt Dokumentu (Układ 1:1)", "Odczyt pism, umów i tabel z zachowaniem układu do edytora tekstu.", ft.Icons.ARTICLE, ft.Colors.BLUE_900, ft.Colors.BLUE_300, "dokument"),
            kafel_wyboru("Szybki Skaner Graficzny", "Kadrowanie z podglądem na żywo i filtry czarno-białe (offline).", ft.Icons.CROP_FREE, ft.Colors.DEEP_ORANGE_900, ft.Colors.ORANGE_300, "skaner")
        ], spacing=12, visible=True)

    def przelacz_widok(self, nazwa: str):
        # 1. Przełączanie widoczności modułów (właściwe nazwy zmiennych)
        self.widok_menu.visible = (nazwa == "menu")
        self.widok_pz.visible = (nazwa == "pz")
        self.widok_dokument.visible = (nazwa == "dokument")
        self.widok_skanera.visible = (nazwa == "skaner")

        # 2. Blokada scrolla dla skanera (zero kradzieży dotyku narożników!)
        if nazwa == "skaner":
            self.page.scroll = None  # Sztywny ekran pod gesty dotykowe kadrowania
        else:
            self.page.scroll = ft.ScrollMode.AUTO  # Płynny scroll dla PZ, Dokumentu i Menu

        self.page.update()
