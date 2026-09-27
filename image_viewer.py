import os
import time
import shutil
import asyncio
import flet as ft

import config
import image_processor


class PełnyEdytorObrazu(ft.Container):
    def __init__(self, page: ft.Page, on_zatwierdz=None, on_anuluj=None):
        super().__init__(expand=True, bgcolor=ft.Colors.BLACK)
        self.app_page = page
        self.on_zatwierdz = on_zatwierdz
        self.on_anuluj = on_anuluj

        self.sciezka_pelna_bazowa = None
        self.sciezka_pelna_aktualna = None
        self.sciezka_preview_baza = None
        self.sciezka_preview_akt = None
        self.historia_pelna = []
        
        self.tryb_kadrowania = False
        self._zadanie_suwakow = None

        self.SZER_KADRU = 330.0
        self.WYS_KADRU = 460.0
        self.skala_zoom = 1.0
        self.UCHWYT_ROZMIAR = 38.0
        self.crop_x1 = 0.0
        self.crop_y1 = 0.0
        self.crop_x2 = self.SZER_KADRU
        self.crop_y2 = self.WYS_KADRU

        self.akt_kontrast = 1.0
        self.akt_jasnosc = 1.0
        self.akt_ostrosc = 1.0
        self.akt_kolor = "kolor"

        self._zbuduj_interfejs()

    @property
    def sciezka_aktualna(self):
        """Zgodność z wywołaniem zdarzenia on_resized w main.py."""
        return self.sciezka_pelna_aktualna

    def _zbuduj_interfejs(self):
        # 1. Kontrolka podglądu powiększenia
        self.img_view_zoom = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit=ft.BoxFit.CONTAIN,
            repeat=ft.ImageRepeat.NO_REPEAT
        )

        # Kontener ze scrollem pionowym i poziomym (natywny gest na telefonie)
        self.kontener_scroll_wewnetrzny = ft.Row(
            controls=[self.img_view_zoom],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO
        )

        self.obszar_podgladu_scroll = ft.Column(
            controls=[self.kontener_scroll_wewnetrzny],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
            expand=True
        )

        # 2. Kontrolka podglądu kadrowania
        self.img_view_crop = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit=ft.BoxFit.CONTAIN,
            repeat=ft.ImageRepeat.NO_REPEAT
        )

        self.maska_gora = ft.Container(bgcolor=ft.Colors.BLACK_54, top=0, left=0, width=self.SZER_KADRU, height=0)
        self.maska_dol = ft.Container(bgcolor=ft.Colors.BLACK_54, bottom=0, left=0, width=self.SZER_KADRU, height=0)
        self.maska_lewo = ft.Container(bgcolor=ft.Colors.BLACK_54, top=0, bottom=0, left=0, width=0)
        self.maska_prawo = ft.Container(bgcolor=ft.Colors.BLACK_54, top=0, bottom=0, right=0, width=0)

        self.strefa_srodka = ft.GestureDetector(
            content=ft.Container(
                border=ft.Border.all(2.0, ft.Colors.BLUE_ACCENT),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLUE_ACCENT)
            ),
            drag_interval=10,
            on_pan_update=self._pan_calego_kadru
        )

        def stworz_uchwyt():
            return ft.Container(
                alignment=ft.Alignment(0, 0),
                content=ft.Container(
                    width=24, height=24,
                    bgcolor=ft.Colors.BLUE_ACCENT,
                    border_radius=12,
                    border=ft.Border.all(2.0, ft.Colors.WHITE)
                ),
                width=self.UCHWYT_ROZMIAR,
                height=self.UCHWYT_ROZMIAR
            )

        self.u_lt = ft.GestureDetector(content=stworz_uchwyt(), drag_interval=10, on_pan_update=lambda e: self._pan_uchwytu("lt", e))
        self.u_rt = ft.GestureDetector(content=stworz_uchwyt(), drag_interval=10, on_pan_update=lambda e: self._pan_uchwytu("rt", e))
        self.u_lb = ft.GestureDetector(content=stworz_uchwyt(), drag_interval=10, on_pan_update=lambda e: self._pan_uchwytu("lb", e))
        self.u_rb = ft.GestureDetector(content=stworz_uchwyt(), drag_interval=10, on_pan_update=lambda e: self._pan_uchwytu("rb", e))

        self.warstwa_kadrowania = ft.Container(
            content=ft.Stack([
                self.img_view_crop,
                self.maska_gora, self.maska_dol, self.maska_lewo, self.maska_prawo,
                self.strefa_srodka,
                self.u_lt, self.u_rt, self.u_lb, self.u_rb
            ]),
            alignment=ft.Alignment(0, 0),
            visible=False
        )

        # 3. Przyciski górnej belki
        self.btn_obrot_l = ft.IconButton(
            icon=ft.Icons.ROTATE_LEFT,
            icon_size=20,
            icon_color=ft.Colors.WHITE,
            bgcolor=ft.Colors.GREY_900,
            tooltip="Obróć w lewo",
            on_click=lambda e: asyncio.create_task(self.obroc(-90))
        )
        self.btn_obrot_r = ft.IconButton(
            icon=ft.Icons.ROTATE_RIGHT,
            icon_size=20,
            icon_color=ft.Colors.WHITE,
            bgcolor=ft.Colors.GREY_900,
            tooltip="Obróć w prawo",
            on_click=lambda e: asyncio.create_task(self.obroc(90))
        )
        self.btn_auto = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.AUTO_FIX_HIGH, size=15),
                ft.Text("Auto", size=12, weight=ft.FontWeight.BOLD)
            ], spacing=2),
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE_900,
                color=ft.Colors.WHITE,
                padding=ft.Padding(8, 4, 8, 4)
            ),
            on_click=lambda e: asyncio.create_task(self.zastosuj_profil_auto())
        )
        self.btn_trybik = ft.IconButton(
            icon=ft.Icons.TUNE,
            icon_size=20,
            icon_color=ft.Colors.WHITE,
            bgcolor=ft.Colors.GREY_900,
            tooltip="Suwaki obrazu",
            on_click=self.otworz_panel_suwakow
        )
        
        # Pasek kontroli powiększenia (Zoom) z klikalnym resetem
        self.lbl_zoom = ft.Text("1.0x", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300)
        self.btn_reset_zoom = ft.Container(
            content=self.lbl_zoom,
            padding=ft.Padding(4, 4, 4, 4),
            tooltip="Kliknij, aby zresetować do 1.0x",
            on_click=self._resetuj_zoom
        )
        self.btn_zoom_out = ft.IconButton(
            icon=ft.Icons.ZOOM_OUT,
            icon_size=16,
            icon_color=ft.Colors.WHITE,
            on_click=lambda e: self._zmien_zoom(-0.25)
        )
        self.btn_zoom_in = ft.IconButton(
            icon=ft.Icons.ZOOM_IN,
            icon_size=16,
            icon_color=ft.Colors.WHITE,
            on_click=lambda e: self._zmien_zoom(0.25)
        )
        self.pasek_zoom = ft.Row(
            [self.btn_zoom_out, self.btn_reset_zoom, self.btn_zoom_in],
            spacing=0,
            alignment=ft.MainAxisAlignment.CENTER
        )

        self.belka_gorna = ft.Row([
            self.btn_obrot_l,
            self.pasek_zoom,
            self.btn_auto,
            self.btn_trybik,
            self.btn_obrot_r
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=2)

        # 4. Przyciski dolnej belki (ikony z dużym polem dotyku)
        self.btn_anuluj = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=22,
            icon_color=ft.Colors.WHITE,
            bgcolor=ft.Colors.GREY_900,
            tooltip="Anuluj",
            on_click=self._klik_anuluj
        )
        self.btn_cofnij = ft.IconButton(
            icon=ft.Icons.UNDO,
            icon_size=22,
            icon_color=ft.Colors.WHITE38,
            bgcolor=ft.Colors.GREY_900,
            disabled=True,
            tooltip="Cofnij zmianę",
            on_click=lambda e: self._cofnij_krok()
        )
        self.btn_kadruj = ft.IconButton(
            icon=ft.Icons.CROP,
            icon_size=22,
            icon_color=ft.Colors.WHITE,
            bgcolor=ft.Colors.BLUE_GREY_800,
            tooltip="Kadruj / Zatwierdź",
            on_click=self._przepnij_tryb_kadrowania
        )
        self.btn_wyslij = ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            icon_size=24,
            icon_color=ft.Colors.WHITE,
            bgcolor=ft.Colors.GREEN_800,
            tooltip="Wyślij do OCR",
            on_click=lambda e: asyncio.create_task(self._klik_wyslij_async())
        )
        
        self.belka_dolna = ft.Row(
            [self.btn_anuluj, self.btn_cofnij, self.btn_kadruj, self.btn_wyslij],
            alignment=ft.MainAxisAlignment.SPACE_EVENLY
        )

        self._zbuduj_okno_suwakow()

        self.obszar_roboczy = ft.Container(
            content=self.obszar_podgladu_scroll,
            alignment=ft.Alignment(0, 0),
            expand=True
        )

        # Górny margines 38 px (schodzi pod pasek stanu Androida) i dolny 48 px (nad przyciski nawigacji)
        self.content = ft.Column([
            ft.Container(content=self.belka_gorna, padding=ft.Padding(4, 38, 4, 4)),
            self.obszar_roboczy,
            ft.Container(content=self.belka_dolna, padding=ft.Padding(8, 4, 8, 48))
        ], spacing=0)

    def _zbuduj_okno_suwakow(self):
        self.lbl_val_kontrast = ft.Text("1.0", size=11, color=ft.Colors.CYAN_300)
        self.slider_kontrast = ft.Slider(min=0.5, max=2.2, round=2, value=1.0, on_change=self._suwak_on_change)
        self.lbl_val_jasnosc = ft.Text("1.0", size=11, color=ft.Colors.CYAN_300)
        self.slider_jasnosc = ft.Slider(min=0.5, max=1.6, round=2, value=1.0, on_change=self._suwak_on_change)
        self.lbl_val_ostrosc = ft.Text("1.0", size=11, color=ft.Colors.CYAN_300)
        self.slider_ostrosc = ft.Slider(min=1.0, max=5.0, round=1, value=1.0, on_change=self._suwak_on_change)
        self.seg_kolor = ft.SegmentedButton(
            selected=["kolor"], allow_multiple_selection=False,
            segments=[ft.Segment(value="kolor", label=ft.Text("Kolor", size=11)), ft.Segment(value="szary", label=ft.Text("Szary", size=11)), ft.Segment(value="bw", label=ft.Text("B&W", size=11))],
            on_change=self._suwak_on_change
        )
        self.dlg_suwaki = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.TUNE, color=ft.Colors.BLUE_400), ft.Text("Korekcja obrazu", size=16, weight=ft.FontWeight.BOLD)], spacing=8),
            content=ft.Container(
                content=ft.Column([
                    ft.Row([ft.Text("Kontrast:", size=12, weight=ft.FontWeight.BOLD), self.lbl_val_kontrast], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), self.slider_kontrast,
                    ft.Row([ft.Text("Jasność:", size=12, weight=ft.FontWeight.BOLD), self.lbl_val_jasnosc], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), self.slider_jasnosc,
                    ft.Row([ft.Text("Ostrość:", size=12, weight=ft.FontWeight.BOLD), self.lbl_val_ostrosc], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), self.slider_ostrosc,
                    ft.Text("Tryb kolorów:", size=12, weight=ft.FontWeight.BOLD), self.seg_kolor
                ], tight=True, spacing=4), width=340
            ),
            actions=[
                ft.Button("Resetuj", on_click=self._resetuj_suwaki),
                ft.Button("Zapisz Auto", style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE), on_click=self._zapisz_profil_jako_domyslny),
                ft.Button("Gotowe", style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE), on_click=lambda e: self.app_page.pop_dialog())
            ]
        )

    def otworz_panel_suwakow(self, e=None):
        if hasattr(self.app_page, "open"): self.app_page.open(self.dlg_suwaki)
        elif hasattr(self.app_page, "show_dialog"): self.app_page.show_dialog(self.dlg_suwaki)
        else:
            self.app_page.dialog = self.dlg_suwaki
            self.dlg_suwaki.open = True
            self.app_page.update()

    def _resetuj_zoom(self, e=None):
        """Wymusza powrót powiększenia do 1.0x po kliknięciu etykiety między lupkami."""
        if self.skala_zoom != 1.0:
            self.skala_zoom = 1.0
            self.lbl_zoom.value = "1.0x"
            self.img_view_zoom.width = round(self.SZER_KADRU)
            self.img_view_zoom.height = round(self.WYS_KADRU)
            self.app_page.update()

    def _zmien_zoom(self, delta: float):
        nowa_skala = round(max(1.0, min(4.0, self.skala_zoom + delta)), 2)
        if nowa_skala != self.skala_zoom:
            self.skala_zoom = nowa_skala
            self.lbl_zoom.value = f"{self.skala_zoom:.1f}x"
            self.img_view_zoom.width = round(self.SZER_KADRU * self.skala_zoom)
            self.img_view_zoom.height = round(self.WYS_KADRU * self.skala_zoom)
            self.app_page.update()

    def dostosuj_do_wymiarow_ekranu(self):
        if not self.sciezka_pelna_aktualna: return
        w_orig, h_orig = image_processor.pobierz_wymiary_obrazu(self.sciezka_pelna_aktualna)
        if w_orig == 0 or h_orig == 0: w_orig, h_orig = 1000, 1400

        p_w = getattr(self.app_page, "width", None) or 400.0
        p_h = getattr(self.app_page, "height", None) or 700.0

        self.height = max(500.0, float(p_h) - 32.0)
        max_w = max(240.0, float(p_w) - 24.0)
        max_h = max(240.0, float(p_h) - 255.0)

        proporcja = w_orig / max(1, h_orig)
        if (max_w / max_h) > proporcja:
            h_r = max_h
            w_r = round(max_h * proporcja)
        else:
            w_r = max_w
            h_r = round(max_w / proporcja)

        self.SZER_KADRU = max(160.0, float(w_r))
        self.WYS_KADRU = max(160.0, float(h_r))

        self.img_view_zoom.width = round(self.SZER_KADRU * self.skala_zoom)
        self.img_view_zoom.height = round(self.WYS_KADRU * self.skala_zoom)
        self.img_view_crop.width = self.SZER_KADRU
        self.img_view_crop.height = self.WYS_KADRU

        self.warstwa_kadrowania.width = self.SZER_KADRU
        self.warstwa_kadrowania.height = self.WYS_KADRU

        self.crop_x1 = 0.0
        self.crop_y1 = 0.0
        self.crop_x2 = self.SZER_KADRU
        self.crop_y2 = self.WYS_KADRU
        self._odswiez_maski_i_uchwyty()

    def _wygeneruj_unikalny_podglad(self, sciezka_bazy: str) -> str:
        if not os.path.exists(sciezka_bazy): return sciezka_bazy
        unikalna = sciezka_bazy.replace(".jpg", f"_{int(time.time() * 1000)}.jpg")
        shutil.copy(sciezka_bazy, unikalna)
        return unikalna

    def _odswiez_obraz_na_ekranie(self):
        """Wstrzykuje bezpośrednią ścieżkę pliku do kontrolek Fleta."""
        if not self.sciezka_preview_akt or not os.path.exists(self.sciezka_preview_akt):
            return

        sciezka_pliku = os.path.abspath(self.sciezka_preview_akt)
        self.img_view_zoom.src = sciezka_pliku
        self.img_view_crop.src = sciezka_pliku
        self.app_page.update()

    def wczytaj_obraz(self, sciezka: str):
        sciezka_znormalizowana = image_processor.przygotuj_obraz_wejsciowy(sciezka)
        self.sciezka_pelna_bazowa = sciezka_znormalizowana
        self.sciezka_pelna_aktualna = sciezka_znormalizowana
        self.historia_pelna = [sciezka_znormalizowana]

        baza_podgladu = image_processor.przygotuj_kopie_podgladowa(sciezka_znormalizowana)
        self.sciezka_preview_baza = self._wygeneruj_unikalny_podglad(baza_podgladu)
        self.sciezka_preview_akt = self.sciezka_preview_baza

        self.skala_zoom = 1.0
        self.lbl_zoom.value = "1.0x"
        self.pasek_zoom.visible = True

        self.btn_cofnij.disabled = True
        self.btn_cofnij.icon_color = ft.Colors.WHITE38
        self.tryb_kadrowania = False
        self.obszar_roboczy.content = self.obszar_podgladu_scroll

        self._resetuj_suwaki(None)
        self._odswiez_obraz_na_ekranie()
        self.dostosuj_do_wymiarow_ekranu()

    def _suwak_on_change(self, e):
        self.akt_kontrast = round(self.slider_kontrast.value, 2)
        self.akt_jasnosc = round(self.slider_jasnosc.value, 2)
        self.akt_ostrosc = round(self.slider_ostrosc.value, 2)
        self.akt_kolor = list(self.seg_kolor.selected)[0] if self.seg_kolor.selected else "kolor"

        self.lbl_val_kontrast.value = str(self.akt_kontrast)
        self.lbl_val_jasnosc.value = str(self.akt_jasnosc)
        self.lbl_val_ostrosc.value = str(self.akt_ostrosc)
        self.app_page.update()

        if self._zadanie_suwakow and not self._zadanie_suwakow.done():
            self._zadanie_suwakow.cancel()
        self._zadanie_suwakow = asyncio.create_task(self._buforowane_przeliczenie())

    async def _buforowane_przeliczenie(self):
        try:
            await asyncio.sleep(0.08)
            if not self.sciezka_preview_baza or not os.path.exists(self.sciezka_preview_baza): return

            loop = asyncio.get_running_loop()
            nowa_sciezka = await loop.run_in_executor(
                None, image_processor.zastosuj_korekcje, self.sciezka_preview_baza,
                self.akt_kontrast, self.akt_jasnosc, self.akt_ostrosc, self.akt_kolor
            )
            self.sciezka_preview_akt = nowa_sciezka
            self._odswiez_obraz_na_ekranie()
        except asyncio.CancelledError:
            pass

    def _resetuj_suwaki(self, e=None):
        self.slider_kontrast.value = 1.0
        self.slider_jasnosc.value = 1.0
        self.slider_ostrosc.value = 1.0
        self.seg_kolor.selected = ["kolor"]
        self._suwak_on_change(None)

    def _zapisz_profil_jako_domyslny(self, e=None):
        cfg = config.wczytaj_konfiguracje()
        cfg["profil_auto_kontrast"] = self.akt_kontrast
        cfg["profil_auto_jasnosc"] = self.akt_jasnosc
        cfg["profil_auto_ostrosc"] = self.akt_ostrosc
        cfg["profil_auto_kolor"] = self.akt_kolor
        config.zapisz_konfiguracje(cfg)
        self.app_page.pop_dialog()

    async def zastosuj_profil_auto(self):
        cfg = config.wczytaj_konfiguracje()
        self.slider_kontrast.value = float(cfg.get("profil_auto_kontrast", 1.2))
        self.slider_jasnosc.value = float(cfg.get("profil_auto_jasnosc", 1.05))
        self.slider_ostrosc.value = float(cfg.get("profil_auto_ostrosc", 1.4))
        self.seg_kolor.selected = [str(cfg.get("profil_auto_kolor", "kolor"))]
        self._suwak_on_change(None)

    async def obroc(self, kat: int):
        if not self.sciezka_pelna_aktualna: return

        self.historia_pelna.append(self.sciezka_pelna_aktualna)
        self.btn_cofnij.disabled = False
        self.btn_cofnij.icon_color = ft.Colors.WHITE

        loop = asyncio.get_running_loop()
        nowa_pelna = await loop.run_in_executor(None, image_processor.obroc_obraz, self.sciezka_pelna_aktualna, kat)
        self.sciezka_pelna_bazowa = nowa_pelna
        self.sciezka_pelna_aktualna = nowa_pelna

        baza_podgladu = await loop.run_in_executor(None, image_processor.przygotuj_kopie_podgladowa, nowa_pelna)
        self.sciezka_preview_baza = self._wygeneruj_unikalny_podglad(baza_podgladu)
        self.sciezka_preview_akt = self.sciezka_preview_baza

        self.skala_zoom = 1.0
        self.lbl_zoom.value = "1.0x"

        self.dostosuj_do_wymiarow_ekranu()
        self._resetuj_suwaki(None)
        self._odswiez_obraz_na_ekranie()

    def _cofnij_krok(self):
        if len(self.historia_pelna) > 1:
            self.historia_pelna.pop()
            poprzednia = self.historia_pelna[-1]
            self.sciezka_pelna_bazowa =图标_prev = poprzednia
            self.sciezka_pelna_aktualna = poprzednia

            baza_podgladu = image_processor.przygotuj_kopie_podgladowa(poprzednia)
            self.sciezka_preview_baza = self._wygeneruj_unikalny_podglad(baza_podgladu)
            self.sciezka_preview_akt = self.sciezka_preview_baza

            self.skala_zoom = 1.0
            self.lbl_zoom.value = "1.0x"

            self.dostosuj_do_wymiarow_ekranu()
            self._resetuj_suwaki(None)
            self.btn_cofnij.disabled = (len(self.historia_pelna) <= 1)
            self.btn_cofnij.icon_color = ft.Colors.WHITE if not self.btn_cofnij.disabled else ft.Colors.WHITE38
            self._odswiez_obraz_na_ekranie()

    def _przepnij_tryb_kadrowania(self, e=None):
        self.tryb_kadrowania = not self.tryb_kadrowania
        if self.tryb_kadrowania:
            self.pasek_zoom.visible = False
            self.obszar_roboczy.content = self.warstwa_kadrowania
            self.warstwa_kadrowania.visible = True
            self.btn_kadruj.icon = ft.Icons.CHECK
            self.btn_kadruj.bgcolor = ft.Colors.BLUE_800
        else:
            self.pasek_zoom.visible = True
            self.obszar_roboczy.content = self.obszar_podgladu_scroll
            self.warstwa_kadrowania.visible = False
            self.btn_kadruj.icon = ft.Icons.CROP
            self.btn_kadruj.bgcolor = ft.Colors.BLUE_GREY_800
            asyncio.create_task(self._wykonaj_ciecie_kadru())

        self.app_page.update()

    async def _wykonaj_ciecie_kadru(self):
        proc_l = (self.crop_x1 / self.SZER_KADRU) * 100.0
        proc_t = (self.crop_y1 / self.WYS_KADRU) * 100.0
        proc_r = ((self.SZER_KADRU - self.crop_x2) / self.SZER_KADRU) * 100.0
        proc_b = ((self.WYS_KADRU - self.crop_y2) / self.WYS_KADRU) * 100.0

        if proc_l > 0.5 or proc_t > 0.5 or proc_r > 0.5 or proc_b > 0.5:
            self.historia_pelna.append(self.sciezka_pelna_aktualna)
            self.btn_cofnij.disabled = False
            self.btn_cofnij.icon_color = ft.Colors.WHITE

            loop = asyncio.get_running_loop()
            nowa_pelna = await loop.run_in_executor(
                None, image_processor.kadruj_obraz, self.sciezka_pelna_aktualna, proc_l, proc_t, proc_r, proc_b
            )

            self.sciezka_pelna_bazowa = nowa_pelna
            self.sciezka_pelna_aktualna = nowa_pelna

            baza_podgladu = await loop.run_in_executor(
                None, image_processor.przygotuj_kopie_podgladowa, nowa_pelna
            )
            self.sciezka_preview_baza = self._wygeneruj_unikalny_podglad(baza_podgladu)
            self.sciezka_preview_akt = self.sciezka_preview_baza

            self.skala_zoom = 1.0
            self.lbl_zoom.value = "1.0x"

            self.dostosuj_do_wymiarow_ekranu()
            self._resetuj_suwaki(None)
            self._odswiez_obraz_na_ekranie()

    def _odswiez_maski_i_uchwyty(self):
        w, h = self.SZER_KADRU, self.WYS_KADRU
        x1, y1, x2, y2 = self.crop_x1, self.crop_y1, self.crop_x2, self.crop_y2
        pol = self.UCHWYT_ROZMIAR / 2.0

        self.maska_gora.width = w
        self.maska_gora.height = y1
        self.maska_dol.width = w
        self.maska_dol.height = max(0.0, h - y2)
        self.maska_lewo.top = y1
        self.maska_lewo.height = max(0.0, y2 - y1)
        self.maska_lewo.width = x1
        self.maska_prawo.top = y1
        self.maska_prawo.height = max(0.0, y2 - y1)
        self.maska_prawo.width = max(0.0, w - x2)

        self.strefa_srodka.top = y1
        self.strefa_srodka.left = x1
        self.strefa_srodka.width = max(0.0, x2 - x1)
        self.strefa_srodka.height = max(0.0, y2 - y1)

        self.u_lt.left = max(0.0, x1 - pol)
        self.u_lt.top = max(0.0, y1 - pol)
        self.u_rt.left = min(w - self.UCHWYT_ROZMIAR, x2 - pol)
        self.u_rt.top = max(0.0, y1 - pol)
        self.u_lb.left = max(0.0, x1 - pol)
        self.u_lb.top = min(h - self.UCHWYT_ROZMIAR, y2 - pol)
        self.u_rb.left = min(w - self.UCHWYT_ROZMIAR, x2 - pol)
        self.u_rb.top = min(h - self.UCHWYT_ROZMIAR, y2 - pol)
        self.app_page.update()

    def _pobierz_deltas(self, e):
        dx = getattr(e, "delta", None)
        if dx is not None: return e.delta.x, e.delta.y
        loc = getattr(e, "local_delta", None)
        if loc is not None: return e.local_delta.x, e.local_delta.y
        return getattr(e, "delta_x", 0.0), getattr(e, "delta_y", 0.0)

    def _pan_uchwytu(self, ktory: str, e):
        dx, dy = self._pobierz_deltas(e)
        min_r = 40.0
        w, h = self.SZER_KADRU, self.WYS_KADRU

        if ktory == "lt":
            self.crop_x1 = max(0.0, min(self.crop_x1 + dx, self.crop_x2 - min_r))
            self.crop_y1 = max(0.0, min(self.crop_y1 + dy, self.crop_y2 - min_r))
        elif ktory == "rt":
            self.crop_x2 = min(w, max(self.crop_x2 + dx, self.crop_x1 + min_r))
            self.crop_y1 = max(0.0, min(self.crop_y1 + dy, self.crop_y2 - min_r))
        elif ktory == "lb":
            self.crop_x1 = max(0.0, min(self.crop_x1 + dx, self.crop_x2 - min_r))
            self.crop_y2 = min(h, max(self.crop_y2 + dy, self.crop_y1 + min_r))
        elif ktory == "rb":
            self.crop_x2 = min(w, max(self.crop_x2 + dx, self.crop_x1 + min_r))
            self.crop_y2 = min(h, max(self.crop_y2 + dy, self.crop_y1 + min_r))

        self._odswiez_maski_i_uchwyty()

    def _pan_calego_kadru(self, e):
        dx, dy = self._pobierz_deltas(e)
        szer_k = self.crop_x2 - self.crop_x1
        wys_k = self.crop_y2 - self.crop_y1

        self.crop_x1 += dx
        self.crop_y1 += dy
        self.crop_x2 = self.crop_x1 + szer_k
        self.crop_y2 = self.crop_y1 + wys_k

        if self.crop_x1 < 0:
            self.crop_x1 = 0.0
            self.crop_x2 = szer_k
        if self.crop_y1 < 0:
            self.crop_y1 = 0.0
            self.crop_y2 = wys_k
        if self.crop_x2 > self.SZER_KADRU:
            self.crop_x2 = self.SZER_KADRU
            self.crop_x1 = self.crop_x2 - szer_k
        if self.crop_y2 > self.WYS_KADRU:
            self.crop_y2 = self.WYS_KADRU
            self.crop_y1 = self.crop_y2 - wys_k

        self._odswiez_maski_i_uchwyty()

    def _klik_anuluj(self, e=None):
        if self.on_anuluj: self.on_anuluj()

    async def _klik_wyslij_async(self):
        if self.tryb_kadrowania:
            await self._wykonaj_ciecie_kadru()
        if self.sciezka_pelna_aktualna:
            loop = asyncio.get_running_loop()
            sciezka_finalna = await loop.run_in_executor(
                None, image_processor.zastosuj_korekcje, self.sciezka_pelna_aktualna,
                self.akt_kontrast, self.akt_jasnosc, self.akt_ostrosc, self.akt_kolor
            )
            if self.on_zatwierdz:
                self.on_zatwierdz(sciezka_finalna)
