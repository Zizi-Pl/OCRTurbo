import os
import shutil
import asyncio
from datetime import datetime
import flet as ft
from PIL import Image

import config
import network
import image_processor
from image_viewer import PełnyEdytorObrazu


class ModulDocMixin:
    def _inicjalizuj_modul_dok(self):
        self.zdjecie_dok = {"sciezka": None}
        self.ostatni_wynik_dok = {"tekst": ""}

    def _inicjalizuj_modul_dokument(self):
        self._inicjalizuj_modul_dok()

        # 1. Podgląd na ekranie głównym modułu Dokument
        self.podglad_dok = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit=ft.BoxFit.CONTAIN,
            width=320,
            height=240
        )

        # 2. Pełnoekranowy edytor (pinch-to-zoom, kadrowanie, suwaki)
        self.edytor_pelny_dok = PełnyEdytorObrazu(
            page=self.page,
            on_zatwierdz=lambda sciezka: asyncio.create_task(self._zatwierdz_edycje_i_wyslij_dok(sciezka)),
            on_anuluj=self._zamknij_pelny_ekran_dok
        )

        # Kontrolki ekranu głównego modułu Dokument
        self.status_dok = ft.Text("Wybierz zdjęcie dokumentu biurowego lub zrób nowe.", size=13, color=ft.Colors.GREY_300, text_align=ft.TextAlign.CENTER)
        self.pasek_dok = ft.ProgressBar(visible=False, color=ft.Colors.LIGHT_BLUE_ACCENT)

        self.btn_foto_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("ZDJĘCIA")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_galerie_dok())
        )
        self.btn_aparat_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("APARAT")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.ui.otworz_aparat_dla("dokument"))
        )
        self.wiersz_foto_dok = ft.Row([self.btn_foto_dok, self.btn_aparat_dok], spacing=10)

        self.kontener_podgladu_dok = ft.Container(
            content=ft.GestureDetector(
                content=self.podglad_dok,
                on_tap=lambda e: self.otworz_pelny_podglad_dok()
            ),
            alignment=ft.Alignment(0, 0),
            height=250,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            visible=False
        )

        self.btn_otworz_kadr_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.TUNE, size=20), ft.Text("Dopasuj kadr / Suwaki", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: self.otworz_pelny_podglad_dok()
        )
        self.btn_start_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.DOCUMENT_SCANNER), ft.Text("Odczytaj dokument (1:1)")], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.LIGHT_BLUE_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.analizuj_dokument_dok(e))
        )
        self.btn_usun_foto_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, size=18), ft.Text("Usuń wybrane zdjęcie", size=12)], alignment=ft.MainAxisAlignment.CENTER),
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            visible=False,
            on_click=lambda e: self.usun_wybrane_zdjecie_dok()
        )
        self.btn_wroc_wynik_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.VISIBILITY), ft.Text("Pokaż ostatni odczytany tekst")], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.TEAL_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: self.ui.bezpiecznie_otworz_dialog(self.dlg_wynik_dok)
        )

        self.btn_konsola_dok = ft.IconButton(icon=ft.Icons.TERMINAL, tooltip="Konsola zdarzeń (logi)", on_click=self.ui.otworz_konsole)

        pasek_tytulu_dok = ft.Row([
            ft.Row([
                ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Menu Główne", on_click=lambda e: asyncio.create_task(self.przelacz_widok("menu"))),
                ft.Column([
                    ft.Text("ocrLmm Mobile", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.LIGHT_BLUE_400),
                    ft.Text("Skaner Dokumentów (Word/Excel/TXT)", size=11, color=ft.Colors.GREY_400)
                ], spacing=1)
            ]),
            self.btn_konsola_dok
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        self.kolumna_glowna_dok = ft.Column([
            pasek_tytulu_dok,
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self.wiersz_foto_dok,
            self.pasek_dok,
            self.status_dok,
            self.kontener_podgladu_dok,
            self.btn_otworz_kadr_dok,
            self.btn_start_dok,
            self.btn_wroc_wynik_dok,
            self.btn_usun_foto_dok
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=10)

        self.widok_dok = ft.Column([
            self.kolumna_glowna_dok,
            self.edytor_pelny_dok
        ], expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0, visible=False)

        self.edytor_pelny_dok.visible = False
        self.widok_dokument = self.widok_dok

        # Dialog edytora tekstu z eksportem
        self.txt_edytor_dok = ft.TextField(
            multiline=True,
            min_lines=14,
            max_lines=22,
            text_size=12,
            expand=True
        )
        self.dlg_wynik_dok = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Text("Odczytany dokument", size=16, weight=ft.FontWeight.BOLD),
                ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: self.page.pop_dialog())
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(
                content=self.txt_edytor_dok,
                height=420,
                expand=True
            ),
            actions=[
                ft.Row([
                    ft.Button(
                        content=ft.Text("Kopiuj", size=12),
                        expand=True,
                        style=ft.ButtonStyle(padding=0),
                        on_click=lambda e: asyncio.create_task(self._kopiuj_tekst_dok())
                    ),
                    ft.Button(
                        content=ft.Text("TXT", size=12),
                        expand=True,
                        style=ft.ButtonStyle(padding=0),
                        on_click=lambda e: asyncio.create_task(self._eksportuj_dok("txt"))
                    ),
                    ft.Button(
                        content=ft.Text("Word", size=12),
                        expand=True,
                        style=ft.ButtonStyle(padding=0),
                        on_click=lambda e: asyncio.create_task(self._eksportuj_dok("docx"))
                    ),
                    ft.Button(
                        content=ft.Text("Excel", size=12),
                        expand=True,
                        style=ft.ButtonStyle(padding=0),
                        on_click=lambda e: asyncio.create_task(self._eksportuj_dok("xlsx"))
                    ),
                ], spacing=4, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ]
        )

    def ustaw_stan_foto_dok(self, czy_ma: bool):
        self.kontener_podgladu_dok.visible = czy_ma
        self.btn_otworz_kadr_dok.visible = czy_ma
        self.btn_start_dok.visible = czy_ma
        self.btn_usun_foto_dok.visible = czy_ma
        self.page.update()

    def ustaw_nowy_obraz_dok(self, sciezka: str):
        # Normalizacja formatu przez image_processor (PNG z przezroczystością -> białe tło -> JPG)
        nowa_sciezka = image_processor.przygotuj_obraz_wejsciowy(sciezka, prefiks="img_dok")

        self.zdjecie_dok["sciezka"] = nowa_sciezka
        self.podglad_dok.src = None
        self.podglad_dok.src = nowa_sciezka

        self.ustaw_stan_foto_dok(True)
        self.status_dok.value = "Zdjęcie gotowe. Kliknij w podgląd, aby dopasować kadr lub użyć suwaków."
        self.status_dok.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    def otworz_pelny_podglad_dok(self):
        if not self.zdjecie_dok["sciezka"] or not os.path.exists(self.zdjecie_dok["sciezka"]):
            return

        # 1. NAJPIERW pokaż kontener edytora
        self.kolumna_glowna_dok.visible = False
        self.edytor_pelny_dok.visible = True
        self.page.scroll = None
        self.page.update()

        # 2. DOPIERO TERAZ wczytaj obraz
        self.edytor_pelny_dok.wczytaj_obraz(self.zdjecie_dok["sciezka"])

    def _zamknij_pelny_ekran_dok(self):
        self.edytor_pelny_dok.visible = False
        self.kolumna_glowna_dok.visible = True
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.update()

    async def _zatwierdz_edycje_i_wyslij_dok(self, sciezka_po_edycji: str):
        self.zdjecie_dok["sciezka"] = sciezka_po_edycji
        self.podglad_dok.src = None
        self.podglad_dok.src = sciezka_po_edycji

        self._zamknij_pelny_ekran_dok()
        await self.analizuj_dokument_dok(None)

    def usun_wybrane_zdjecie_dok(self):
        sciezka_pliku = self.zdjecie_dok.get("sciezka")
        if sciezka_pliku and os.path.exists(sciezka_pliku):
            try:
                os.remove(sciezka_pliku)
                self.ui.dopisz_log(f"Usunięto plik: {os.path.basename(sciezka_pliku)}")
            except Exception as err:
                self.ui.dopisz_log(f"Błąd usuwania pliku: {err}", ft.Colors.AMBER)

        self.zdjecie_dok["sciezka"] = None
        self.podglad_dok.src = None
        self.podglad_dok.src = config.PUSTY_OBRAZ
        self.ustaw_stan_foto_dok(False)
        self.status_dok.value = "Wybierz zdjęcie dokumentu biurowego lub zrób nowe."
        self.status_dok.color = ft.Colors.GREY_300
        self.page.update()

    async def otworz_galerie_dok(self):
        try:
            pliki = await self.pickery["foto"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            if pliki and len(pliki) > 0 and pliki[0].path:
                self.ustaw_nowy_obraz_dok(pliki[0].path)
        except Exception as e_pick:
            self.status_dok.value = f"Błąd wyboru pliku: {e_pick}"
            self.page.update()

    async def analizuj_dokument_dok(self, e):
        if not self.zdjecie_dok["sciezka"]:
            return

        self.btn_start_dok.disabled = True
        self.pasek_dok.visible = True
        self.status_dok.value = "Przygotowywanie dokumentu do odczytu..."
        self.status_dok.color = ft.Colors.ORANGE_ACCENT

        import time
        start_calkowity = time.perf_counter()
        self.ui.dopisz_log("=== ROZPOCZĘTO ODCZYT DOKUMENTU (1:1) ===", ft.Colors.CYAN)
        self.page.update()

        loop = asyncio.get_running_loop()
        sciezka_do_analizy = self.zdjecie_dok["sciezka"]
        waga_oryg_kb = round(os.path.getsize(sciezka_do_analizy) / 1024, 1)

        prompt_dok = (
            "Rola: Działasz jako bezbłędny system transkrypcji OCR dokumentów handlowych i magazynowych.\n"
            "Twoim zadaniem jest dokładne przepisanie widocznego tekstu z wiernym zachowaniem układu.\n\n"
            "Zasady tabelaryczne:\n"
            "1. Ścisła spójność kolumn w tabeli Markdown:\n"
            "   - Każdy wiersz tabeli MUSI mieć dokładnie samą liczbę kolumn co wiersz nagłówkowy!\n"
            "   - Jeśli pierwsza kolumna kodu jest pusta, w każdym wierszu towarowym ZACZNIJ od pustej komórki: '| | Nazwa | kg | ...'.\n"
            "   - Jednostka miary (np. 'kg', 'szt') musi ZAWSZE znajdować się w osobnej komórce '| kg |'.\n"
            "2. Tekst i nagłówki:\n"
            "   - Przepisz wiernie bloki danych sprzedawcy i nabywcy oraz podsumowania kwotowe bez zgadywania.\n"
            "3. Format wyjściowy:\n"
            "   - Zwróć wyłącznie czysty tekst i tabele. Zakaz bloków ```markdown, wstępów i komentarzy."
        )

        try:
            cfg = config.wczytaj_konfiguracje()
            uzywa_chmury = cfg.get("use_cloud", True)
            wymiar = cfg.get("image_resolution", 1800)

            # Sprawdzanie i budzenie serwera lokalnego przez network.py
            if not uzywa_chmury:
                ip_lokalne = cfg.get("local_ip", "192.168.1.154").strip()
                port_str = cfg.get("local_port", "1234").strip()
                mac_adres = cfg.get("wol_mac", "").strip()
                port_lokalny = int(port_str) if port_str.isdigit() else 1234

                def status_cb(msg):
                    self.status_dok.value = msg
                    self.status_dok.color = ft.Colors.CYAN_ACCENT
                    self.page.update()

                def log_cb(msg, kolor="WHITE"):
                    self.ui.dopisz_log(msg, getattr(ft.Colors, kolor, ft.Colors.WHITE))

                await network.upewnij_sie_ze_serwer_zyje(
                    ip=ip_lokalne,
                    port=port_lokalny,
                    mac_adres=mac_adres,
                    on_status=status_cb,
                    on_log=log_cb
                )

            try:
                with Image.open(sciezka_do_analizy) as img:
                    w_px, h_px = img.size
            except Exception:
                w_px, h_px = "?", "?"

            base64_image = await loop.run_in_executor(
                None, image_processor.kompresuj_do_wysylki, sciezka_do_analizy, wymiar
            )
            waga_b64_kb = round(len(base64_image) * 0.75 / 1024, 1)
            self.ui.dopisz_log(f"📷 Obraz wejściowy: {w_px}x{h_px}px | Waga Base64: {waga_b64_kb} KB (oryginał: {waga_oryg_kb} KB)", ft.Colors.GREY_400)

            if uzywa_chmury:
                model_nazwa = cfg.get("gemini_model", "gemini-2.5-flash")
                url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                headers = {"Authorization": f"Bearer {cfg.get('gemini_api_key', '')}", "Content-Type": "application/json"}
                payload = {
                    "model": model_nazwa,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_dok}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                    "temperature": 0.0,
                    "max_tokens": 8192
                }
                cel_logu = f"Google Cloud ({model_nazwa})"
            else:
                model_nazwa = cfg.get("local_model", "qwen3-vl-8b-instruct").strip()
                url = f"http://{cfg.get('local_ip')}:{cfg.get('local_port')}/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
                if cfg.get("local_api_key"):
                    headers["Authorization"] = f"Bearer {cfg.get('local_api_key')}"
                payload = {
                    "model": model_nazwa,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_dok}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                    "temperature": 0.0,
                    "chat_template_kwargs": {"enable_thinking": False}
                }
                cel_logu = f"LM Studio ({model_nazwa})"

            def log_http_cb(msg, kolor="WHITE"):
                self.ui.dopisz_log(msg, getattr(ft.Colors, kolor, ft.Colors.WHITE))

            def status_http_cb(msg):
                self.status_dok.value = msg
                self.status_dok.color = ft.Colors.AMBER_ACCENT
                self.page.update()

            surowy_tekst, _, _ = await network.wyslij_zadanie_ai(
                url=url,
                headers=headers,
                payload=payload,
                cel_logu=cel_logu,
                on_status=status_http_cb,
                on_log=log_http_cb
            )

            linie = surowy_tekst.splitlines()
            wiersze_tabeli = sum(1 for l in linie if l.strip().startswith('|') and l.strip().endswith('|'))
            slowa = len(surowy_tekst.split())
            znaki = len(surowy_tekst)

            self.ui.dopisz_log(
                f"📝 Odczytano: {znaki} znaków | {slowa} słów | {len(linie)} linii"
                + (f" | 📊 Wiersze tabeli: {wiersze_tabeli}" if wiersze_tabeli > 0 else ""),
                ft.Colors.GREEN
            )

            czas_calkowity = time.perf_counter() - start_calkowity
            self.ui.dopisz_log(f"✅ Sukces w czasie {czas_calkowity:.2f}s.", ft.Colors.GREEN)

            self.txt_edytor_dok.value = surowy_tekst
            self.ostatni_wynik_dok["tekst"] = surowy_tekst
            self.btn_wroc_wynik_dok.visible = True

            self.status_dok.value = "✅ Dokument został pomyślnie odczytany."
            self.status_dok.color = ft.Colors.GREEN_ACCENT
            self.ui.bezpiecznie_otworz_dialog(self.dlg_wynik_dok)

        except Exception as err:
            self.ui.dopisz_log(f"Błąd odczytu: {err}", ft.Colors.RED)
            self.status_dok.value = f"Błąd: {err}"
            self.status_dok.color = ft.Colors.RED_ACCENT
            self.ui.pokaz_okno_bledu("Błąd odczytu dokumentu", str(err))
        finally:
            self.pasek_dok.visible = False
            self.btn_start_dok.disabled = False
            self.page.update()

    async def _kopiuj_tekst_dok(self):
        tekst = self.txt_edytor_dok.value or ""
        await self.page.set_clipboard(tekst)
        self.ui.dopisz_log("Skopiowano tekst dokumentu do schowka systemowego.", ft.Colors.CYAN)

    async def _eksportuj_dok(self, format_pliku: str):
        tekst = self.txt_edytor_dok.value or ""
        if not tekst.strip():
            self.ui.pokaz_okno_bledu("Brak tekstu", "Brak treści do wyeksportowania.")
            return

        stem = f"dok_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        sciezka_wyjsciowa = os.path.join(config.KATALOG_DANYCH, f"{stem}.{format_pliku}")

        try:
            if format_pliku == "txt":
                with open(sciezka_wyjsciowa, "w", encoding="utf-8") as f:
                    f.write(tekst)

            elif format_pliku == "docx":
                import docx
                doc = docx.Document()
                for linia in tekst.splitlines():
                    doc.add_paragraph(linia)
                doc.save(sciezka_wyjsciowa)

            elif format_pliku == "xlsx":
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Dokument"
                for r_idx, linia in enumerate(tekst.splitlines(), start=1):
                    if "|" in linia:
                        czesci = [c.strip() for c in linia.split("|") if c.strip()]
                        for c_idx, val in enumerate(czesci, start=1):
                            ws.cell(row=r_idx, column=c_idx, value=val)
                    else:
                        ws.cell(row=r_idx, column=1, value=linia)
                wb.save(sciezka_wyjsciowa)

            self.ui.dopisz_log(f"Zapisano plik: {os.path.basename(sciezka_wyjsciowa)}", ft.Colors.GREEN)
            await self._bezpiecznie_udostepnij_plik(sciezka_wyjsciowa, f"Dokument {format_pliku.upper()}")
        except Exception as err:
            self.ui.dopisz_log(f"Błąd eksportu {format_pliku}: {err}", ft.Colors.RED)
            self.ui.pokaz_okno_bledu("Błąd eksportu", str(err))

    async def _bezpiecznie_udostepnij_plik(self, sciezka: str, tytul: str):
        try:
            if hasattr(self.ui.serwis_udostepniania, "share_files"):
                try:
                    await self.ui.serwis_udostepniania.share_files(
                        [ft.ShareFile.from_path(sciezka)],
                        text=tytul
                    )
                except Exception:
                    await self.ui.serwis_udostepniania.share_files([sciezka])
        except Exception as e_share:
            self.ui.dopisz_log(f"Nie udało się otworzyć systemowego okna udostępniania: {e_share}", ft.Colors.AMBER)
