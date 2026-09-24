import os
import shutil
import asyncio
from datetime import datetime
import flet as ft
from PIL import Image, ImageOps

import config
import core


class ModulScanMixin:
    def _inicjalizuj_modul_skanera(self):
        # Bezpieczne granice kadrowania dopasowane do ekranu telefonu (spójne z PZ i Dokument)
        self.MAX_SZEROKOSC_KADRU = 330.0
        self.MAX_WYSOKOSC_KADRU = 460.0
        self.UCHWYT_ROZMIAR_DOK_SKAN = 40

        self.SZEROKOSC_DOK_SKAN = int(self.MAX_SZEROKOSC_KADRU)
        self.WYSOKOSC_DOK_SKAN = int(self.MAX_WYSOKOSC_KADRU)

        self.crop_skan_x1 = 0.0
        self.crop_skan_y1 = 0.0
        self.crop_skan_x2 = float(self.SZEROKOSC_DOK_SKAN)
        self.crop_skan_y2 = float(self.WYSOKOSC_DOK_SKAN)
        self.kadr_skan_zmieniony = False

        self.historia_skan = []
        self.aktywny_filtr_skan = None
        self.zdjecie_skan = {"sciezka": None, "oryginal": None}

        # 1. Podgląd na ekranie głównym skanera
        self.podglad_obrazu_skan = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit="contain",
            width=320,
            height=240
        )

        # 2. Obraz na pełnym ekranie roboczym z zachowaniem proporcji
        self.img_pelny_podglad_skan = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit="contain",
            width=self.SZEROKOSC_DOK_SKAN,
            height=self.WYSOKOSC_DOK_SKAN
        )

        self.maska_skan_gora = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, left=0, width=self.SZEROKOSC_DOK_SKAN, height=0)
        self.maska_skan_dol = ft.Container(bgcolor=ft.Colors.BLACK54, bottom=0, left=0, width=self.SZEROKOSC_DOK_SKAN, height=0)
        self.maska_skan_lewo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, left=0, width=0)
        self.maska_skan_prawo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, right=0, width=0)

        self.strefa_srodka_skan = ft.GestureDetector(
            content=ft.Container(
                border=ft.Border.all(2.0, ft.Colors.ORANGE_ACCENT),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ORANGE_ACCENT)
            ),
            drag_interval=10,
            on_pan_update=lambda e: self._przesun_caly_kadr_skan(*self._pobierz_deltas_skan(e)),
            top=0, left=0, width=self.SZEROKOSC_DOK_SKAN, height=self.WYSOKOSC_DOK_SKAN
        )

        def stworz_uchwyt_skan():
            return ft.Container(
                alignment=ft.Alignment(0, 0),
                content=ft.Container(
                    width=26, height=26,
                    bgcolor=ft.Colors.ORANGE_ACCENT,
                    border_radius=13,
                    border=ft.Border.all(2.0, ft.Colors.WHITE)
                ),
                width=self.UCHWYT_ROZMIAR_DOK_SKAN,
                height=self.UCHWYT_ROZMIAR_DOK_SKAN
            )

        self.uchwyt_skan_lt = ft.GestureDetector(content=stworz_uchwyt_skan(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_skan("lt", *self._pobierz_deltas_skan(e)))
        self.uchwyt_skan_rt = ft.GestureDetector(content=stworz_uchwyt_skan(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_skan("rt", *self._pobierz_deltas_skan(e)))
        self.uchwyt_skan_lb = ft.GestureDetector(content=stworz_uchwyt_skan(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_skan("lb", *self._pobierz_deltas_skan(e)))
        self.uchwyt_skan_rb = ft.GestureDetector(content=stworz_uchwyt_skan(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_skan("rb", *self._pobierz_deltas_skan(e)))

        self.ramka_kadrowania_skan = ft.Container(
            content=ft.Stack([
                self.img_pelny_podglad_skan,
                self.maska_skan_gora, self.maska_skan_dol, self.maska_skan_lewo, self.maska_skan_prawo,
                self.strefa_srodka_skan,
                self.uchwyt_skan_lt, self.uchwyt_skan_rt, self.uchwyt_skan_lb, self.uchwyt_skan_rb
            ]),
            width=self.SZEROKOSC_DOK_SKAN,
            height=self.WYSOKOSC_DOK_SKAN,
            alignment=ft.Alignment(0, 0)
        )

        # Górna belka: obroty i filtry
        self.btn_obrot_l_skan = ft.IconButton(
            icon=ft.Icons.ROTATE_LEFT, icon_color=ft.Colors.WHITE, icon_size=28,
            width=50, height=50,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=10)),
            tooltip="Obróć w lewo (90°)",
            on_click=lambda e: asyncio.create_task(self.obroc_skan(90))
        )
        self.btn_f_bw_skan = ft.Button(
            content=ft.Text("B&W", size=12, weight=ft.FontWeight.BOLD),
            height=50, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_skan("bw"))
        )
        self.btn_f_szary_skan = ft.Button(
            content=ft.Text("GRY", size=12, weight=ft.FontWeight.BOLD),
            height=50, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_skan("szary"))
        )
        self.btn_f_wyostrz_skan = ft.Button(
            content=ft.Text("SHP", size=12, weight=ft.FontWeight.BOLD),
            height=50, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_skan("wyostrz"))
        )
        self.btn_obrot_r_skan = ft.IconButton(
            icon=ft.Icons.ROTATE_RIGHT, icon_color=ft.Colors.WHITE, icon_size=28,
            width=50, height=50,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=10)),
            tooltip="Obróć w prawo (90°)",
            on_click=lambda e: asyncio.create_task(self.obroc_skan(-90))
        )

        self.wiersz_filtrow_skan = ft.Row([
            self.btn_obrot_l_skan,
            self.btn_f_bw_skan,
            self.btn_f_szary_skan,
            self.btn_f_wyostrz_skan,
            self.btn_obrot_r_skan
        ], spacing=4)

        # Przyciski dolne (wysokość 52, zaokrąglenie 10)
        self.btn_pelny_anuluj_skan = ft.Button(
            content=ft.Text("Anuluj", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._zamknij_pelny_ekran_skan())
        )
        self.btn_pelny_cofnij_skan = ft.Button(
            content=ft.Text("Cofnij", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            disabled=True,
            on_click=lambda e: self._cofnij_krok_pelny_skan()
        )
        self.btn_pelny_zatwierdz_skan = ft.Button(
            content=ft.Text("Zatwierdź", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._zatwierdz_krok_pelny_skan())
        )
        self.btn_pelny_udostepnij_skan = ft.Button(
            content=ft.Text("Udostępnij", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._zakoncz_i_udostepnij_skan())
        )
        self.wiersz_akcji_pelnych_skan = ft.Row([
            self.btn_pelny_anuluj_skan,
            self.btn_pelny_cofnij_skan,
            self.btn_pelny_zatwierdz_skan,
            self.btn_pelny_udostepnij_skan
        ], spacing=4)

        # Kontener pełnego ekranu kadrowania
        self.widok_kadrowania_skan = ft.Container(
            content=ft.Column([
                self.wiersz_filtrow_skan,
                ft.Container(
                    content=self.ramka_kadrowania_skan,
                    alignment=ft.Alignment(0, 0),
                    expand=True,
                    padding=ft.Padding(top=6, bottom=6, left=0, right=0)
                ),
                self.wiersz_akcji_pelnych_skan
            ], spacing=6, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=6,
            expand=True,
            visible=False
        )

        # Kontrolki ekranu głównego
        self.status_skan = ft.Text(
            "Zrób zdjęcie lub wybierz skan z galerii.",
            size=12, color=ft.Colors.ORANGE_200, text_align=ft.TextAlign.CENTER
        )

        self.btn_foto_skan = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("Wybierz z galerii")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.wybierz_foto_skan
        )
        self.btn_aparat_skan = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Zrób zdjęcie")]),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.ui.otworz_aparat_dla("skaner"))
        )
        self.wiersz_wyboru_zdjecia_skan = ft.Row([self.btn_foto_skan, self.btn_aparat_skan], spacing=10)

        self.kontener_podgladu_skan = ft.Container(
            content=ft.GestureDetector(
                content=self.podglad_obrazu_skan,
                on_tap=lambda e: asyncio.create_task(self.otworz_pelny_podglad_skan(e))
            ),
            alignment=ft.Alignment(0, 0),
            height=250,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            visible=False
        )

        self.btn_otworz_kadrowanie_skan = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CROP, size=20), ft.Text("Dopasuj kadr / Obróbka", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_pelny_podglad_skan(e))
        )

        self.btn_udostepnij_gotowe_skan = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.SHARE, size=20), ft.Text("Udostępnij gotowy skan", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.udostepnij_plik(self.zdjecie_skan["sciezka"], "Skan dokumentu"))
        )

        self.kolumna_glowna_skan = ft.Column([
            ft.Row([
                ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: asyncio.create_task(self.przelacz_widok("menu"))),
                ft.Column([
                    ft.Text("Szybki Skaner Graficzny", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_400),
                    ft.Text("Obróbka zdjęć, kadrowanie i filtry kontrastowe (offline)", size=11, color=ft.Colors.GREY_400)
                ], spacing=1)
            ]),
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self.wiersz_wyboru_zdjecia_skan,
            self.status_skan,
            self.kontener_podgladu_skan,
            self.btn_otworz_kadrowanie_skan,
            self.btn_udostepnij_gotowe_skan
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        # Główny kontener widoku
        self.widok_skanera = ft.Column([
            self.kolumna_glowna_skan,
            self.widok_kadrowania_skan
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0, visible=False)

    # --- OBSŁUGA GESTÓW I RAMKI ---
    def _napraw_orientacje_exif(self, sciezka: str) -> str:
        try:
            with Image.open(sciezka) as img:
                img_poprawiony = ImageOps.exif_transpose(img)
                if img_poprawiony:
                    img_poprawiony.save(sciezka, quality=95)
        except Exception:
            pass
        return sciezka

    def _pobierz_deltas_skan(self, e):
        dx = getattr(e, "delta", None)
        if dx is not None:
            return e.delta.x, e.delta.y
        loc = getattr(e, "local_delta", None)
        if loc is not None:
            return e.local_delta.x, e.local_delta.y
        return getattr(e, "delta_x", 0.0), getattr(e, "delta_y", 0.0)

    def _aktualizuj_kadrowanie_skan(self):
        w = float(self.SZEROKOSC_DOK_SKAN)
        h = float(self.WYSOKOSC_DOK_SKAN)
        min_rozmiar = 40.0

        self.crop_skan_x1 = max(0.0, min(self.crop_skan_x1, w - min_rozmiar))
        self.crop_skan_y1 = max(0.0, min(self.crop_skan_y1, h - min_rozmiar))
        self.crop_skan_x2 = max(self.crop_skan_x1 + min_rozmiar, min(self.crop_skan_x2, w))
        self.crop_skan_y2 = max(self.crop_skan_y1 + min_rozmiar, min(self.crop_skan_y2, h))

        x1, y1, x2, y2 = self.crop_skan_x1, self.crop_skan_y1, self.crop_skan_x2, self.crop_skan_y2
        pol_uchwytu = self.UCHWYT_ROZMIAR_DOK_SKAN / 2.0

        self.maska_skan_gora.width = w
        self.maska_skan_gora.height = y1

        self.maska_skan_dol.width = w
        self.maska_skan_dol.height = max(0.0, h - y2)

        self.maska_skan_lewo.top = y1
        self.maska_skan_lewo.height = max(0.0, y2 - y1)
        self.maska_skan_lewo.width = x1

        self.maska_skan_prawo.top = y1
        self.maska_skan_prawo.height = max(0.0, y2 - y1)
        self.maska_skan_prawo.width = max(0.0, w - x2)

        self.strefa_srodka_skan.top = y1
        self.strefa_srodka_skan.left = x1
        self.strefa_srodka_skan.width = max(0.0, x2 - x1)
        self.strefa_srodka_skan.height = max(0.0, y2 - y1)

        self.uchwyt_skan_lt.left = max(0.0, x1 - pol_uchwytu)
        self.uchwyt_skan_lt.top = max(0.0, y1 - pol_uchwytu)

        self.uchwyt_skan_rt.left = min(w - self.UCHWYT_ROZMIAR_DOK_SKAN, x2 - pol_uchwytu)
        self.uchwyt_skan_rt.top = max(0.0, y1 - pol_uchwytu)

        self.uchwyt_skan_lb.left = max(0.0, x1 - pol_uchwytu)
        self.uchwyt_skan_lb.top = min(h - self.UCHWYT_ROZMIAR_DOK_SKAN, y2 - pol_uchwytu)

        self.uchwyt_skan_rb.left = min(w - self.UCHWYT_ROZMIAR_DOK_SKAN, x2 - pol_uchwytu)
        self.uchwyt_skan_rb.top = min(h - self.UCHWYT_ROZMIAR_DOK_SKAN, y2 - pol_uchwytu)

        self.page.update()

    def _przesun_uchwyt_skan(self, ktory: str, dx: float, dy: float):
        self.kadr_skan_zmieniony = True
        if ktory == "lt":
            self.crop_skan_x1 += dx
            self.crop_skan_y1 += dy
        elif ktory == "rt":
            self.crop_skan_x2 += dx
            self.crop_skan_y1 += dy
        elif ktory == "lb":
            self.crop_skan_x1 += dx
            self.crop_skan_y2 += dy
        elif ktory == "rb":
            self.crop_skan_x2 += dx
            self.crop_skan_y2 += dy
        self._aktualizuj_kadrowanie_skan()

    def _przesun_caly_kadr_skan(self, dx: float, dy: float):
        self.kadr_skan_zmieniony = True
        szer_k = self.crop_skan_x2 - self.crop_skan_x1
        wys_k = self.crop_skan_y2 - self.crop_skan_y1

        self.crop_skan_x1 += dx
        self.crop_skan_y1 += dy
        self.crop_skan_x2 = self.crop_skan_x1 + szer_k
        self.crop_skan_y2 = self.crop_skan_y1 + wys_k

        if self.crop_skan_x1 < 0:
            self.crop_skan_x1 = 0.0
            self.crop_skan_x2 = szer_k
        if self.crop_skan_y1 < 0:
            self.crop_skan_y1 = 0.0
            self.crop_skan_y2 = wys_k
        if self.crop_skan_x2 > self.SZEROKOSC_DOK_SKAN:
            self.crop_skan_x2 = float(self.SZEROKOSC_DOK_SKAN)
            self.crop_skan_x1 = self.crop_skan_x2 - szer_k
        if self.crop_skan_y2 > self.WYSOKOSC_DOK_SKAN:
            self.crop_skan_y2 = float(self.WYSOKOSC_DOK_SKAN)
            self.crop_skan_y1 = self.crop_skan_y2 - wys_k

        self._aktualizuj_kadrowanie_skan()

    def _dopasuj_pola_robocze_pod_obraz_skan(self, sciezka: str):
        try:
            with Image.open(sciezka) as img:
                w_orig, h_orig = img.size
        except Exception:
            w_orig, h_orig = 1000, 1400

        max_w = self.MAX_SZEROKOSC_KADRU
        max_h = self.MAX_WYSOKOSC_KADRU

        proporcja = w_orig / max(1, h_orig)

        if (max_w / max_h) > proporcja:
            h_ramki = max_h
            w_ramki = round(max_h * proporcja)
        else:
            w_ramki = max_w
            h_ramki = round(max_w / proporcja)

        self.SZEROKOSC_DOK_SKAN = max(140, int(w_ramki))
        self.WYSOKOSC_DOK_SKAN = max(140, int(h_ramki))

        self.ramka_kadrowania_skan.width = self.SZEROKOSC_DOK_SKAN
        self.ramka_kadrowania_skan.height = self.WYSOKOSC_DOK_SKAN
        self.img_pelny_podglad_skan.width = self.SZEROKOSC_DOK_SKAN
        self.img_pelny_podglad_skan.height = self.WYSOKOSC_DOK_SKAN

        self.crop_skan_x1 = 0.0
        self.crop_skan_y1 = 0.0
        self.crop_skan_x2 = float(self.SZEROKOSC_DOK_SKAN)
        self.crop_skan_y2 = float(self.WYSOKOSC_DOK_SKAN)
        self.kadr_skan_zmieniony = False
        self._aktualizuj_kadrowanie_skan()

    def ustaw_nowy_obraz_skan(self, sciezka: str):
        nowa_sciezka = os.path.join(config.KATALOG_DANYCH, f"img_skan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        try:
            shutil.copyfile(sciezka, nowa_sciezka)
        except Exception:
            nowa_sciezka = sciezka

        self._napraw_orientacje_exif(nowa_sciezka)

        self.zdjecie_skan["oryginal"] = nowa_sciezka
        self.zdjecie_skan["sciezka"] = nowa_sciezka
        self.historia_skan = [(nowa_sciezka, None)]
        self.aktywny_filtr_skan = None
        self._odswiez_styl_przyciskow_filtrow_skan()
        self.btn_pelny_cofnij_skan.disabled = True

        self.podglad_obrazu_skan.src_base64 = None
        self.podglad_obrazu_skan.src = nowa_sciezka
        self.img_pelny_podglad_skan.src = nowa_sciezka

        self.kontener_podgladu_skan.visible = True
        self.btn_otworz_kadrowanie_skan.visible = True
        self.btn_udostepnij_gotowe_skan.visible = True
        self.status_skan.value = "Zdjęcie wczytane. Kliknij w podgląd, aby obrobić i skadrować."
        self.status_skan.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    async def otworz_pelny_podglad_skan(self, e):
        if not self.zdjecie_skan["sciezka"] or not os.path.exists(self.zdjecie_skan["sciezka"]):
            return

        self._dopasuj_pola_robocze_pod_obraz_skan(self.zdjecie_skan["sciezka"])
        self.img_pelny_podglad_skan.src = self.zdjecie_skan["sciezka"]

        self.kolumna_glowna_skan.visible = False
        self.widok_kadrowania_skan.visible = True
        self.page.scroll = None
        self.page.update()

    async def _zamknij_pelny_ekran_skan(self):
        self.widok_kadrowania_skan.visible = False
        self.kolumna_glowna_skan.visible = True
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.update()

    async def obroc_skan(self, kat: int):
        if not self.zdjecie_skan["sciezka"] or not os.path.exists(self.zdjecie_skan["sciezka"]):
            return

        sciezka_akt = self.zdjecie_skan["sciezka"]
        self.historia_skan.append((sciezka_akt, self.aktywny_filtr_skan))
        self.btn_pelny_cofnij_skan.disabled = False

        loop = asyncio.get_running_loop()
        nowa_sciezka = await loop.run_in_executor(
            None, core.obroc_plik_graficzny, sciezka_akt, kat, "rot_skan"
        )

        self.zdjecie_skan["sciezka"] = str(nowa_sciezka)
        self.img_pelny_podglad_skan.src_base64 = None
        self.img_pelny_podglad_skan.src = str(nowa_sciezka)
        self.podglad_obrazu_skan.src_base64 = None
        self.podglad_obrazu_skan.src = str(nowa_sciezka)

        self._dopasuj_pola_robocze_pod_obraz_skan(str(nowa_sciezka))
        self.page.update()

    async def _przelacz_filtr_pelny_skan(self, typ: str):
        if not self.zdjecie_skan["sciezka"] or not os.path.exists(self.zdjecie_skan["sciezka"]):
            return

        if self.aktywny_filtr_skan == typ:
            self._cofnij_krok_pelny_skan()
            return

        sciezka_akt = self.zdjecie_skan["sciezka"]
        self.historia_skan.append((sciezka_akt, self.aktywny_filtr_skan))
        self.btn_pelny_cofnij_skan.disabled = False

        loop = asyncio.get_running_loop()
        nowa_sciezka = await loop.run_in_executor(
            None, core.filtruj_plik_graficzny, sciezka_akt, typ
        )

        self.zdjecie_skan["sciezka"] = str(nowa_sciezka)
        self.aktywny_filtr_skan = typ
        self.img_pelny_podglad_skan.src_base64 = None
        self.img_pelny_podglad_skan.src = str(nowa_sciezka)
        self.podglad_obrazu_skan.src_base64 = None
        self.podglad_obrazu_skan.src = str(nowa_sciezka)

        self._odswiez_styl_przyciskow_filtrow_skan()
        self.page.update()

    def _odswiez_styl_przyciskow_filtrow_skan(self):
        aktywny_kolor = ft.Colors.ORANGE_800
        zwykly_kolor = ft.Colors.GREY_800

        self.btn_f_bw_skan.style.bgcolor = aktywny_kolor if self.aktywny_filtr_skan == "bw" else zwykly_kolor
        self.btn_f_szary_skan.style.bgcolor = aktywny_kolor if self.aktywny_filtr_skan == "szary" else zwykly_kolor
        self.btn_f_wyostrz_skan.style.bgcolor = aktywny_kolor if self.aktywny_filtr_skan == "wyostrz" else zwykly_kolor

    async def _zatwierdz_krok_pelny_skan(self):
        if not self.zdjecie_skan["sciezka"] or not os.path.exists(self.zdjecie_skan["sciezka"]):
            return

        proc_lewo = (self.crop_skan_x1 / self.SZEROKOSC_DOK_SKAN) * 100.0
        proc_gora = (self.crop_skan_y1 / self.WYSOKOSC_DOK_SKAN) * 100.0
        proc_prawo = ((self.SZEROKOSC_DOK_SKAN - self.crop_skan_x2) / self.SZEROKOSC_DOK_SKAN) * 100.0
        proc_dol = ((self.WYSOKOSC_DOK_SKAN - self.crop_skan_y2) / self.WYSOKOSC_DOK_SKAN) * 100.0

        if proc_lewo <= 0.5 and proc_gora <= 0.5 and proc_prawo <= 0.5 and proc_dol <= 0.5:
            return

        sciezka_akt = self.zdjecie_skan["sciezka"]
        self.historia_skan.append((sciezka_akt, self.aktywny_filtr_skan))
        self.btn_pelny_cofnij_skan.disabled = False

        loop = asyncio.get_running_loop()
        wyciety_plik = await loop.run_in_executor(
            None, core.kadruj_plik_graficzny, sciezka_akt,
            proc_lewo, proc_gora, proc_prawo, proc_dol
        )

        self.zdjecie_skan["sciezka"] = str(wyciety_plik)
        self.img_pelny_podglad_skan.src_base64 = None
        self.img_pelny_podglad_skan.src = str(wyciety_plik)
        self.podglad_obrazu_skan.src_base64 = None
        self.podglad_obrazu_skan.src = str(wyciety_plik)

        self._dopasuj_pola_robocze_pod_obraz_skan(str(wyciety_plik))

    def _cofnij_krok_pelny_skan(self):
        if not self.historia_skan:
            return
        poprzednia_sciezka, poprzedni_filtr = self.historia_skan.pop()
        self.zdjecie_skan["sciezka"] = str(poprzednia_sciezka)
        self.aktywny_filtr_skan = poprzedni_filtr

        self.img_pelny_podglad_skan.src_base64 = None
        self.img_pelny_podglad_skan.src = str(poprzednia_sciezka)
        self.podglad_obrazu_skan.src_base64 = None
        self.podglad_obrazu_skan.src = str(poprzednia_sciezka)

        self._dopasuj_pola_robocze_pod_obraz_skan(str(poprzednia_sciezka))
        self._odswiez_styl_przyciskow_filtrow_skan()
        self.btn_pelny_cofnij_skan.disabled = (len(self.historia_skan) == 0)
        self.page.update()

    async def _zakoncz_i_udostepnij_skan(self):
        if self.kadr_skan_zmieniony:
            await self._zatwierdz_krok_pelny_skan()
        await self._zamknij_pelny_ekran_skan()
        await self.udostepnij_plik(self.zdjecie_skan["sciezka"], "Skan dokumentu")

    async def wybierz_foto_skan(self, e):
        picker = self.pickery.get("foto") if hasattr(self, "pickery") else None
        if not picker and hasattr(self, "ui") and hasattr(self.ui, "pickery"):
            picker = self.ui.pickery.get("foto")

        if picker:
            pliki = await picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            if pliki and len(pliki) > 0 and pliki[0].path:
                self.ustaw_nowy_obraz_skan(pliki[0].path)#FFFFFF
