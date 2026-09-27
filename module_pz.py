import os
import re
import json
import asyncio
from datetime import datetime
import flet as ft
from PIL import Image

import config
import core
import network
import image_processor
import converter
from image_viewer import PełnyEdytorObrazu


class ModulPZMixin:
    def _inicjalizuj_modul_pz(self):
        # 1. Podgląd na ekranie głównym PZ
        self.podglad_obrazu_pz = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit=ft.BoxFit.CONTAIN,
            width=320,
            height=240
        )

        # 2. Pełnoekranowy edytor
        self.edytor_pelny_pz = PełnyEdytorObrazu(
            page=self.page,
            on_zatwierdz=lambda sciezka: asyncio.create_task(self._zatwierdz_edycje_i_wyslij_pz(sciezka)),
            on_anuluj=self._zamknij_pelny_ekran_pz
        )

        # 3. Kontrolki głównego ekranu PZ (nowoczesny ft.Button bez DeprecationWarning)
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

        self.btn_otworz_kadrowanie = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.TUNE, size=20), ft.Text("Podgląd / Dopasuj kadr / Suwaki", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: self.otworz_pelny_podglad_pz()
        )

        self.pasek_postepu_pz = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_ACCENT)
        self.status_text_pz = ft.Text("Wybierz z galerii lub zrób zdjęcie dokumentu PZ.", size=13, color=ft.Colors.GREY_300, text_align=ft.TextAlign.CENTER)

        self.btn_foto_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("ZDJĘCIA / PLIKI")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_galerie_pz())
        )

        self.btn_aparat_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("APARAT")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
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
                    ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Menu Główne", on_click=lambda e: asyncio.create_task(self.przelacz_widok("menu"))),
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

        self.kontener_podgladu_pz = ft.Container(
            content=ft.GestureDetector(
                content=self.podglad_obrazu_pz,
                on_tap=lambda e: self.otworz_pelny_podglad_pz()
            ),
            alignment=ft.Alignment(0, 0),
            height=250,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            visible=False
        )

        self.kolumna_glowna_pz = ft.Column([
            pasek_tytulu_pz,
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self.wiersz_wyboru_zdjecia_pz,
            self.pasek_postepu_pz,
            self.status_text_pz,
            self.kontener_podgladu_pz,
            self.btn_otworz_kadrowanie,
            self.btn_akcja_analiza_pz,
            self.btn_wroc_weryfikacja_pz,
            self.btn_udostepnij_pz,
            self.btn_usun_zdjecie_pz,
            ft.Divider(height=16, color=ft.Colors.GREY_800),
            ft.Row([btn_wyczysc_katalog])
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=10)

        self.widok_pz = ft.Column([
            self.kolumna_glowna_pz,
            self.edytor_pelny_pz
        ], expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0, visible=False)

        self.edytor_pelny_pz.visible = False

    def ustaw_stan_przycisku_foto_pz(self, czy_ma_zdjecie: bool):
        self.kontener_podgladu_pz.visible = czy_ma_zdjecie
        self.btn_otworz_kadrowanie.visible = czy_ma_zdjecie
        self.btn_usun_zdjecie_pz.visible = czy_ma_zdjecie
        self.btn_akcja_analiza_pz.visible = czy_ma_zdjecie

        if czy_ma_zdjecie and not self.stan_weryfikacji["dane"]:
            self.btn_akcja_analiza_pz.content.controls[1].value = "Rozpocznij analizę PZ"
        self.page.update()

    def ustaw_nowy_obraz_pz(self, sciezka: str):
        try:
            # Standaryzacja: PNG -> RGB JPEG z białym tłem, PDF -> render do JPEG
            nowa_sciezka = converter.standaryzuj_plik_wejsciowy(sciezka)
        except Exception as e_conv:
            self.ui.pokaz_okno_bledu("Błąd konwersji pliku", f"Nie udało się przetworzyć pliku: {e_conv}")
            return

        self.aktualne_zdjecie_pz["sciezka"] = nowa_sciezka
        self.podglad_obrazu_pz.src = None
        self.podglad_obrazu_pz.src = nowa_sciezka

        self.ustaw_stan_przycisku_foto_pz(True)
        self.status_text_pz.value = "Plik gotowy. Kliknij w podgląd, aby dopasować kadr lub użyć suwaków."
        self.status_text_pz.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    def otworz_pelny_podglad_pz(self):
        if not self.aktualne_zdjecie_pz["sciezka"] or not os.path.exists(self.aktualne_zdjecie_pz["sciezka"]):
            return

        # 1. NAJPIERW pokaż kontener edytora
        self.kolumna_glowna_pz.visible = False
        self.edytor_pelny_pz.visible = True
        self.page.scroll = None
        self.page.update()

        # 2. DOPIERO TERAZ wczytaj obraz
        self.edytor_pelny_pz.wczytaj_obraz(self.aktualne_zdjecie_pz["sciezka"])

    def _zamknij_pelny_ekran_pz(self):
        self.edytor_pelny_pz.visible = False
        self.kolumna_glowna_pz.visible = True
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.update()

    async def _zatwierdz_edycje_i_wyslij_pz(self, sciezka_po_edycji: str):
        self.aktualne_zdjecie_pz["sciezka"] = sciezka_po_edycji
        self.podglad_obrazu_pz.src = None
        self.podglad_obrazu_pz.src = sciezka_po_edycji

        self._zamknij_pelny_ekran_pz()
        await self.przetworz_plik_pz(sciezka_po_edycji)

    def usun_wybrane_zdjecie_pz(self, e=None):
        sciezka_pliku = self.aktualne_zdjecie_pz.get("sciezka")
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            try:
                os.remove(sciezka_pliku)
                self.ui.dopisz_log(f"Usunięto plik roboczy: {os.path.basename(sciezka_pliku)}")
            except Exception as err:
                self.ui.dopisz_log(f"Nie udało się usunąć pliku: {err}", ft.Colors.AMBER)

        self.aktualne_zdjecie_pz["sciezka"] = None
        self.podglad_obrazu_pz.src = None
        self.podglad_obrazu_pz.src = config.PUSTY_OBRAZ
        self.ustaw_stan_przycisku_foto_pz(False)
        self.status_text_pz.value = "Wybierz z galerii lub zrób zdjęcie dokumentu PZ."
        self.status_text_pz.color = ft.Colors.GREY_300
        self.page.update()

    async def otworz_galerie_pz(self):
        try:
            pliki = await self.pickery["foto"].pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp", "pdf", "bmp", "tif", "tiff"]
            )
            if pliki and len(pliki) > 0:
                wybrany = pliki[0]
                sciezka = getattr(wybrany, "path", None)
                if sciezka:
                    self.ustaw_nowy_obraz_pz(sciezka)
                else:
                    self.status_text_pz.value = "Nie uzyskano ścieżki do pliku (przeglądarka zablokowała bezpośredni dostęp)."
                    self.page.update()
        except Exception as e_pick:
            self.status_text_pz.value = f"Błąd wyboru pliku: {e_pick}"
            self.page.update()

    def wykonaj_czyszczenie_katalogu(self, e):
        self.page.pop_dialog()
        usuniete = core.wyczysc_pliki_robocze()
        self.ostatnia_sciezka_edi["sciezka"] = None
        self.usun_wybrane_zdjecie_pz(None)
        self.ui._pozycja_scrolla_pz = 0.0
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

    async def udostepnij_plik(self, sciezka_pliku: str, tytul: str = "Dokument EDI"):
        if not sciezka_pliku or not os.path.exists(sciezka_pliku):
            self.ui.pokaz_okno_bledu("Brak pliku", "Wskazany plik nie istnieje na dysku.")
            return

        try:
            if hasattr(self.ui.serwis_udostepniania, "share_files"):
                try:
                    await self.ui.serwis_udostepniania.share_files(
                        [ft.ShareFile.from_path(sciezka_pliku)],
                        text=tytul
                    )
                except Exception:
                    await self.ui.serwis_udostepniania.share_files([sciezka_pliku])
            else:
                self.ui.dopisz_log("Błąd: Serwis udostępniania niedostępny.", ft.Colors.RED)
        except Exception as err_s:
            self.ui.dopisz_log(f"Błąd udostępniania: {err_s}", ft.Colors.RED)
            self.ui.pokaz_okno_bledu("Błąd udostępniania", str(err_s))

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
        try:
            if hasattr(self.ui.serwis_udostepniania, "share_files"):
                try:
                    await self.ui.serwis_udostepniania.share_files(
                        [ft.ShareFile.from_path(sciezka_edi)],
                        text=f"Dokument EDI: {nazwa_pliku}"
                    )
                except Exception:
                    await self.ui.serwis_udostepniania.share_files([sciezka_edi])
        except Exception as err_share:
            self.ui.dopisz_log(f"Nie udało się otworzyć okna udostępniania: {err_share}", ft.Colors.AMBER)

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
        self.podglad_obrazu_pz.src = None
        self.podglad_obrazu_pz.src = config.PUSTY_OBRAZ
        self.ustaw_stan_przycisku_foto_pz(False)
        self.page.update()

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
            import time
            start_calkowity = time.perf_counter()
            self.ui.dopisz_log("=== ROZPOCZĘTO ANALIZĘ PZ ===", ft.Colors.CYAN)
            
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
            self.btn_otworz_kadrowanie.visible = False
            self.btn_usun_zdjecie_pz.visible = False
            self.btn_udostepnij_pz.visible = False
            self.page.update()

            loop = asyncio.get_running_loop()
            waga_oryg_kb = round(os.path.getsize(sciezka_obrazu) / 1024, 1)

            if not uzywa_chmury:
                ip_lokalne = aktualny_konfig.get("local_ip", "192.168.1.154").strip()
                port_str = aktualny_konfig.get("local_port", "1234").strip()
                mac_adres = aktualny_konfig.get("wol_mac", "").strip()
                port_lokalny = int(port_str) if port_str.isdigit() else 1234

                def status_cb(msg):
                    self.status_text_pz.value = msg
                    self.status_text_pz.color = ft.Colors.CYAN_ACCENT
                    self.page.update()

                def log_cb(msg, kolor=ft.Colors.WHITE):
                    self.ui.dopisz_log(msg, getattr(ft.Colors, kolor, ft.Colors.WHITE))

                await network.upewnij_sie_ze_serwer_zyje(
                    ip=ip_lokalne,
                    port=port_lokalny,
                    mac_adres=mac_adres,
                    on_status=status_cb,
                    on_log=log_cb
                )

            wymiar_obrazu = aktualny_konfig.get("image_resolution", 1800)
            base64_image = await loop.run_in_executor(
                None, image_processor.kompresuj_do_wysylki, sciezka_obrazu, wymiar_obrazu
            )
            
            try:
                with Image.open(sciezka_obrazu) as img:
                    w_px, h_px = img.size
            except Exception:
                w_px, h_px = "?", "?"

            waga_b64_kb = round(len(base64_image) * 0.75 / 1024, 1)
            self.ui.dopisz_log(f"📷 Obraz wejściowy: {w_px}x{h_px}px | Waga Base64: {waga_b64_kb} KB (oryginał: {waga_oryg_kb} KB)", ft.Colors.GREY_400)

            prompt = (
                "Rola: Działasz jako precyzyjny, deterministyczny system OCR wyspecjalizowany w polskich dokumentach "
                "magazynowo-handlowych (faktury VAT, WZ, PZ). Ekstrahuj dane WYŁĄCZNIE na podstawie tego, co widoczne "
                "na obrazie. Zakaz zgadywania i konfabulacji: jeśli dana wartość jest nieczytelna, zamazana albo nie "
                "występuje na dokumencie, zwróć dla niej pusty ciąg znaków \"\" zamiast zgadywać.\n\n"
                "1. Nagłówek i kontrahenci:\n"
                "   - nr: pełny numer dokumentu z nagłówka. Ignoruj puste pola powiązane, np. niewypełnione 'Realizacja faktury nr:'.\n"
                "   - dt: data wystawienia/sprzedaży w formacie DD.MM.RRRR.\n"
                "   - w, o: nazwa oraz 10-cyfrowy NIP (same cyfry, bez 'PL', spacji i myślników) odpowiednio dla "
                "sprzedawcy/wystawcy (w) i nabywcy/odbiorcy (o). NIP pobieraj WYŁĄCZNIE z bloku danych adresowych firmy. "
                "Nigdy nie myl NIP-u z numerem konta, BDO ani numerem faktury. Jeśli NIP jednej ze stron jest nieczytelny, "
                "NIE kopiuj tam NIP-u drugiej strony — wstaw pusty ciąg \"\".\n\n"
                "2. Pozycje towarowe (tabela główna, klucz \"p\") – ZWRACAJ ŚCISŁĄ UWAGĘ NA NAGŁÓWKI KOLUMN:\n"
                "   - n: pełna nazwa towaru z kolumny 'Towar' / 'Nazwa'.\n"
                "   - k: kod towaru. POBIERAJ WYŁĄCZNIE z kolumn oznaczonych jako 'EAN', 'Kod', 'CN', 'PKWiU', 'Indeks'. "
                "Jeśli brak kodu lub kolumna jest pusta, wstaw \"\". "
                "BEZWZGLĘDNY ZAKAZ: NIGDY nie pobieraj wartości z kolumn 'Partia', 'Nr partii', 'Seria', 'Batch', 'Lot', 'L/N'!\n"
                "   - j: jednostka miary DOKŁADNIE z kolumny 'JM' ('kg', 'szt', 'op').\n"
                "   - i: ilość z kolumny 'Ilość' (dla 'szt' i 'op' liczba całkowita, dla 'kg' waga z kropką dziesiętną).\n"
                "   - c: ostateczna CENA JEDNOSTKOWA NETTO po rabacie. ZAWSZE z kolumny 'Cena netto'.\n"
                "   - w: WARTOŚĆ NETTO TEJ POZYCJI z kolumny 'Wartość netto'.\n"
                "   ⚠️ KATEGORYCZNY ZAKAZ POBIERANIA WARTOŚCI BRUTTO:\n"
                "       * W polach 'c' i 'w' mają znaleźć się WYŁĄCZNIE kwoty NETTO.\n"
                "       * NIE WOLNO pobierać wartości z kolumn 'Wartość brutto' ani 'Cena brutto'!\n"
                "       * Zwróć uwagę: kolumna 'Wartość brutto' często znajduje się na samym końcu po prawej stronie tabeli — nie myl jej z wcześniejszą kolumną 'Wartość netto'!\n"
                "       * Równość matematyczna w pozycji musi się zgadzać: ilość 'i' pomnożona przez cenę netto 'c' musi równać się wartości netto 'w' (i * c = w).\n\n"
                "3. Podsumowanie:\n"
                "   - sn: całkowita wartość NETTO całego dokumentu, z wiersza sumarycznego 'Razem' pod tabelą rozliczenia podatku.\n"
                "   - dz: ostateczna kwota do zapłaty / suma brutto (jeśli występuje na dokumencie, w przeciwnym razie \"\").\n\n"
                "Formatowanie: liczby z kropką jako separatorem. Zwróć WYŁĄCZNIE czysty obiekt JSON bez znaczników markdown:\n"
                "{\n"
                "  \"nr\": \"\",\n"
                "  \"dt\": \"\",\n"
                "  \"w\": {\"n\": \"\", \"nip\": \"\"},\n"
                "  \"o\": {\"n\": \"\", \"nip\": \"\"},\n"
                "  \"p\": [\n"
                "    {\"n\": \"\", \"k\": \"\", \"j\": \"\", \"i\": \"\", \"c\": \"\", \"w\": \"\"}\n"
                "  ],\n"
                "  \"sn\": \"\",\n"
                "  \"dz\": \"\"\n"
                "}"
            )

            if uzywa_chmury:
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
                cel_logu = f"Google Cloud ({model_gemini})"
            else:
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
                            "content": "Jesteś precyzyjnym systemem OCR. Zwracasz TYLKO i WYŁĄCZNIE surowy obiekt JSON. Nie używaj znaczników markdown ani żadnego tekstu pobocznego."
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
                cel_logu = f"LM Studio ({wybrany_model} @ {ip}:{port})"

            def log_http_cb(msg, kolor="WHITE"):
                self.ui.dopisz_log(msg, getattr(ft.Colors, kolor, ft.Colors.WHITE))

            def status_http_cb(msg):
                self.status_text_pz.value = msg
                self.status_text_pz.color = ft.Colors.AMBER_ACCENT
                self.page.update()

            odp_tekst, _, staty = await network.wyslij_zadanie_ai(
                url=pelny_url,
                headers=naglowki,
                payload=cialo_zapytania,
                cel_logu=cel_logu,
                on_status=status_http_cb,
                on_log=log_http_cb
            )

            dane = None
            try:
                dane = json.loads(odp_tekst)
            except json.JSONDecodeError:
                dopasowanie = re.search(r'\{.*\}', odp_tekst, re.DOTALL)
                if dopasowanie:
                    try:
                        dane = json.loads(dopasowanie.group(0))
                    except Exception:
                        pass

            if dane is None:
                self.ui.dopisz_log(f"Błąd parsowania JSON. Odpowiedź surowa:\n{odp_tekst[:250]}...", ft.Colors.RED)
                raise ValueError("Model nie zwrócił poprawnego formatu JSON.")

            dane = core.oczysc_odpowiedz_llm(dane)

            wystawca_nazwa = (dane.get("w") or {}).get("n") or "Nieznany"
            wystawca_nip = (dane.get("w") or {}).get("nip") or "Brak"
            nr_dok = dane.get("nr") or "Brak numeru"
            pozycje_ocr = dane.get("p") or []

            self.ui.dopisz_log(f"📄 Faktura: {nr_dok} | Kontrahent: {wystawca_nazwa} (NIP: {wystawca_nip})", ft.Colors.GREEN)
            self.ui.dopisz_log(f"📦 Liczba odczytanych pozycji: {len(pozycje_ocr)}", ft.Colors.WHITE)

            self.ui.dopisz_log("Dopasowywanie pozycji do bazy PC-Market...")
            aktualna_baza_sciezka = config.pobierz_aktualna_sciezke_bazy(aktualny_konfig)
            baza_towarowa, dane, status_sum, info_sumy = await loop.run_in_executor(
                None, core.dopasuj_wszystkie_pozycje_w_tle, dane, uzywa_bazy, aktualna_baza_sciezka
            )

            pozycje_koncowe = dane.get("p") or []
            dopasowane_z_bazy = sum(1 for p in pozycje_koncowe if p.get("z_bazy"))
            skutecznosc_proc = round((dopasowane_z_bazy / len(pozycje_koncowe) * 100), 1) if pozycje_koncowe else 0
            kody_wagowe = sum(1 for p in pozycje_koncowe if str(p.get("k", "")).startswith("29"))

            self.ui.dopisz_log(
                f"🎯 Baza PC-Market: {dopasowane_z_bazy}/{len(pozycje_koncowe)} dopasowanych ({skutecznosc_proc}%) | Kody wagowe: {kody_wagowe}",
                ft.Colors.GREEN if skutecznosc_proc > 50 else ft.Colors.AMBER
            )
            self.ui.dopisz_log(f"💰 Weryfikacja sum: {info_sumy} (Status: {status_sum})", ft.Colors.CYAN if status_sum == "OK" else ft.Colors.AMBER)

            czas_calkowity = time.perf_counter() - start_calkowity
            self.ui.dopisz_log(f"✅ Całkowity czas operacji: {czas_calkowity:.2f}s", ft.Colors.GREEN)

            self.stan_weryfikacji["dane"] = dane
            self.stan_weryfikacji["baza"] = baza_towarowa
            self.stan_weryfikacji["uzywa_bazy"] = uzywa_bazy
            self.stan_weryfikacji["status_sum"] = status_sum
            self.stan_weryfikacji["info_sumy"] = info_sumy
            self.stan_weryfikacji["indeks_edytowany"] = -1

            self.status_text_pz.value = "Oczekiwanie na potwierdzenie kodów..."
            self.status_text_pz.color = ft.Colors.CYAN_ACCENT
            self.pasek_postepu_pz.visible = False
            self.btn_wroc_weryfikacja_pz.visible = True
            self.page.update()

            self.ui.odswiez_weryfikacje()
            self.ui.bezpiecznie_otworz_dialog(self.ui.dlg_weryfikacja)

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
            self.btn_otworz_kadrowanie.visible = czy_ma_foto
            self.btn_usun_zdjecie_pz.visible = czy_ma_foto
            self.page.update()
