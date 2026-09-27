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


class ModulPZMixin:
    def _inicjalizuj_modul_pz(self):
        # Bezpieczne granice obszaru roboczego w pionie dla ekranu telefonu
        self.MAX_SZEROKOSC_ROBOCZA_PZ = 330.0
        self.MAX_WYSOKOSC_ROBOCZA_PZ = 460.0
        self.UCHWYT_ROZMIAR_DOK_PZ = 40

        self.SZEROKOSC_DOK_PZ = int(self.MAX_SZEROKOSC_ROBOCZA_PZ)
        self.WYSOKOSC_DOK_PZ = int(self.MAX_WYSOKOSC_ROBOCZA_PZ)

        self.crop_pz_x1 = 0.0
        self.crop_pz_y1 = 0.0
        self.crop_pz_x2 = float(self.SZEROKOSC_DOK_PZ)
        self.crop_pz_y2 = float(self.WYSOKOSC_DOK_PZ)
        self.kadr_pz_zmieniony = False

        self.historia_pz = []
        self.aktywny_filtr_pz = None

        # 1. Podgląd na ekranie głównym PZ
        self.podglad_obrazu_pz = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit="contain",
            width=320,
            height=240
        )

        # 2. Obraz na dedykowanym pełnym ekranie kadrowania
        self.img_pelny_podglad_pz = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit="fill",
            width=self.SZEROKOSC_DOK_PZ,
            height=self.WYSOKOSC_DOK_PZ
        )

        self.maska_pz_gora = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, left=0, width=self.SZEROKOSC_DOK_PZ, height=0)
        self.maska_pz_dol = ft.Container(bgcolor=ft.Colors.BLACK54, bottom=0, left=0, width=self.SZEROKOSC_DOK_PZ, height=0)
        self.maska_pz_lewo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, left=0, width=0)
        self.maska_pz_prawo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, right=0, width=0)

        self.strefa_srodka_pz = ft.GestureDetector(
            content=ft.Container(
                border=ft.Border.all(2.0, ft.Colors.BLUE_ACCENT),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLUE_ACCENT)
            ),
            drag_interval=10,
            on_pan_update=lambda e: self._przesun_caly_kadr_pz(*self._pobierz_deltas_pz(e)),
            top=0, left=0, width=self.SZEROKOSC_DOK_PZ, height=self.WYSOKOSC_DOK_PZ
        )

        def stworz_uchwyt_pz():
            return ft.Container(
                alignment=ft.Alignment(0, 0),
                content=ft.Container(
                    width=26, height=26,
                    bgcolor=ft.Colors.BLUE_ACCENT,
                    border_radius=13,
                    border=ft.Border.all(2.0, ft.Colors.WHITE)
                ),
                width=self.UCHWYT_ROZMIAR_DOK_PZ,
                height=self.UCHWYT_ROZMIAR_DOK_PZ
            )

        self.uchwyt_pz_lt = ft.GestureDetector(content=stworz_uchwyt_pz(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_pz("lt", *self._pobierz_deltas_pz(e)))
        self.uchwyt_pz_rt = ft.GestureDetector(content=stworz_uchwyt_pz(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_pz("rt", *self._pobierz_deltas_pz(e)))
        self.uchwyt_pz_lb = ft.GestureDetector(content=stworz_uchwyt_pz(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_pz("lb", *self._pobierz_deltas_pz(e)))
        self.uchwyt_pz_rb = ft.GestureDetector(content=stworz_uchwyt_pz(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_pz("rb", *self._pobierz_deltas_pz(e)))

        self.ramka_kadrowania_pz = ft.Container(
            content=ft.Stack([
                self.img_pelny_podglad_pz,
                self.maska_pz_gora, self.maska_pz_dol, self.maska_pz_lewo, self.maska_pz_prawo,
                self.strefa_srodka_pz,
                self.uchwyt_pz_lt, self.uchwyt_pz_rt, self.uchwyt_pz_lb, self.uchwyt_pz_rb
            ]),
            width=self.SZEROKOSC_DOK_PZ,
            height=self.WYSOKOSC_DOK_PZ,
            alignment=ft.Alignment(0, 0)
        )

        # Górna belka
        self.btn_obrot_l_pz = ft.IconButton(
            icon=ft.Icons.ROTATE_LEFT, icon_color=ft.Colors.WHITE, icon_size=28,
            width=50, height=50,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=10)),
            tooltip="Obróć w lewo (90°)",
            on_click=lambda e: asyncio.create_task(self.obroc_pz(90))
        )
        self.btn_f_bw = ft.Button(
            content=ft.Text("B&W", size=12, weight=ft.FontWeight.BOLD),
            height=50, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_pz("bw"))
        )
        self.btn_f_szary = ft.Button(
            content=ft.Text("GRY", size=12, weight=ft.FontWeight.BOLD),
            height=50, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_pz("szary"))
        )
        self.btn_f_wyostrz = ft.Button(
            content=ft.Text("SHP", size=12, weight=ft.FontWeight.BOLD),
            height=50, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_pz("wyostrz"))
        )
        self.btn_obrot_r_pz = ft.IconButton(
            icon=ft.Icons.ROTATE_RIGHT, icon_color=ft.Colors.WHITE, icon_size=28,
            width=50, height=50,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=10)),
            tooltip="Obróć w prawo (90°)",
            on_click=lambda e: asyncio.create_task(self.obroc_pz(-90))
        )

        self.wiersz_filtrow_pz = ft.Row([
            self.btn_obrot_l_pz,
            self.btn_f_bw,
            self.btn_f_szary,
            self.btn_f_wyostrz,
            self.btn_obrot_r_pz
        ], spacing=4)

        # Przyciski dolne
        self.btn_pelny_anuluj = ft.Button(
            content=ft.Text("Anuluj", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._zamknij_pelny_ekran_pz(zapisz=False))
        )
        self.btn_pelny_cofnij = ft.Button(
            content=ft.Text("Cofnij", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            disabled=True,
            on_click=lambda e: self._cofnij_krok_pelny_pz()
        )
        self.btn_pelny_zatwierdz = ft.Button(
            content=ft.Text("Zatwierdź", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._zatwierdz_krok_pelny_pz())
        )
        self.btn_pelny_wyslij = ft.Button(
            content=ft.Text("Wyślij", size=13, weight=ft.FontWeight.BOLD),
            height=52, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._wyslij_pelny_ekran_pz())
        )
        self.wiersz_akcji_pelnych_pz = ft.Row([
            self.btn_pelny_anuluj,
            self.btn_pelny_cofnij,
            self.btn_pelny_zatwierdz,
            self.btn_pelny_wyslij
        ], spacing=4)

        # Dedykowany pełny ekran kadrowania
        self.widok_kadrowania_pz = ft.Container(
            content=ft.Column([
                self.wiersz_filtrow_pz,
                ft.Container(
                    content=self.ramka_kadrowania_pz,
                    alignment=ft.Alignment(0, 0),
                    expand=True,
                    padding=ft.Padding(top=6, bottom=6, left=0, right=0)
                ),
                self.wiersz_akcji_pelnych_pz
            ], spacing=6, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=6,
            expand=True,
            visible=False
        )

        # Kontrolki głównego ekranu PZ
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
            content=ft.Row([ft.Icon(ft.Icons.CROP, size=20), ft.Text("Dopasuj kadr / Filtry", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_pelny_podglad_pz(e))
        )

        self.pasek_postepu_pz = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_ACCENT)
        self.status_text_pz = ft.Text("Wybierz z galerii lub zrób zdjęcie dokumentu PZ.", size=13, color=ft.Colors.GREY_300, text_align=ft.TextAlign.CENTER)

        self.btn_foto_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("ZDJĘCIA")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_galerie_pz())
        )

        self.btn_aparat_pz = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Zrób zdjęcie")]),
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
                on_tap=lambda e: asyncio.create_task(self.otworz_pelny_podglad_pz(e))
            ),
            alignment=ft.Alignment(0, 0),
            height=250,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            visible=False
        )

        # Główna kolumna formularza PZ
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

        # Kontener nadrzędny widoku PZ
        self.widok_pz = ft.Column([
            self.kolumna_glowna_pz,
            self.widok_kadrowania_pz
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0, visible=False)

    def _pobierz_deltas_pz(self, e):
        dx = getattr(e, "delta", None)
        if dx is not None:
            return e.delta.x, e.delta.y
        loc = getattr(e, "local_delta", None)
        if loc is not None:
            return e.local_delta.x, e.local_delta.y
        return getattr(e, "delta_x", 0.0), getattr(e, "delta_y", 0.0)

    def _aktualizuj_kadrowanie_pz(self):
        w = float(self.SZEROKOSC_DOK_PZ)
        h = float(self.WYSOKOSC_DOK_PZ)
        min_rozmiar = 40.0

        self.crop_pz_x1 = max(0.0, min(self.crop_pz_x1, w - min_rozmiar))
        self.crop_pz_y1 = max(0.0, min(self.crop_pz_y1, h - min_rozmiar))
        self.crop_pz_x2 = max(self.crop_pz_x1 + min_rozmiar, min(self.crop_pz_x2, w))
        self.crop_pz_y2 = max(self.crop_pz_y1 + min_rozmiar, min(self.crop_pz_y2, h))

        x1, y1, x2, y2 = self.crop_pz_x1, self.crop_pz_y1, self.crop_pz_x2, self.crop_pz_y2
        pol_uchwytu = self.UCHWYT_ROZMIAR_DOK_PZ / 2.0

        # Maski przyciemniające
        self.maska_pz_gora.width = w
        self.maska_pz_gora.height = y1

        self.maska_pz_dol.width = w
        self.maska_pz_dol.height = max(0.0, h - y2)

        self.maska_pz_lewo.top = y1
        self.maska_pz_lewo.height = max(0.0, y2 - y1)
        self.maska_pz_lewo.width = x1

        self.maska_pz_prawo.top = y1
        self.maska_pz_prawo.height = max(0.0, y2 - y1)
        self.maska_pz_prawo.width = max(0.0, w - x2)

        # Strefa środkowa
        self.strefa_srodka_pz.top = y1
        self.strefa_srodka_pz.left = x1
        self.strefa_srodka_pz.width = max(0.0, x2 - x1)
        self.strefa_srodka_pz.height = max(0.0, y2 - y1)

        # Pozycjonowanie uchwytów (środek uchwytu na krawędzi kadru z ograniczeniem wewnątrz ramki)
        self.uchwyt_pz_lt.left = max(0.0, x1 - pol_uchwytu)
        self.uchwyt_pz_lt.top = max(0.0, y1 - pol_uchwytu)

        self.uchwyt_pz_rt.left = min(w - self.UCHWYT_ROZMIAR_DOK_PZ, x2 - pol_uchwytu)
        self.uchwyt_pz_rt.top = max(0.0, y1 - pol_uchwytu)

        self.uchwyt_pz_lb.left = max(0.0, x1 - pol_uchwytu)
        self.uchwyt_pz_lb.top = min(h - self.UCHWYT_ROZMIAR_DOK_PZ, y2 - pol_uchwytu)

        self.uchwyt_pz_rb.left = min(w - self.UCHWYT_ROZMIAR_DOK_PZ, x2 - pol_uchwytu)
        self.uchwyt_pz_rb.top = min(h - self.UCHWYT_ROZMIAR_DOK_PZ, y2 - pol_uchwytu)

        self.page.update()

    def _przesun_uchwyt_pz(self, ktory: str, dx: float, dy: float):
        self.kadr_pz_zmieniony = True
        if ktory == "lt":
            self.crop_pz_x1 += dx
            self.crop_pz_y1 += dy
        elif ktory == "rt":
            self.crop_pz_x2 += dx
            self.crop_pz_y1 += dy
        elif ktory == "lb":
            self.crop_pz_x1 += dx
            self.crop_pz_y2 += dy
        elif ktory == "rb":
            self.crop_pz_x2 += dx
            self.crop_pz_y2 += dy
        self._aktualizuj_kadrowanie_pz()

    def _przesun_caly_kadr_pz(self, dx: float, dy: float):
        self.kadr_pz_zmieniony = True
        szer_k = self.crop_pz_x2 - self.crop_pz_x1
        wys_k = self.crop_pz_y2 - self.crop_pz_y1

        self.crop_pz_x1 += dx
        self.crop_pz_y1 += dy
        self.crop_pz_x2 = self.crop_pz_x1 + szer_k
        self.crop_pz_y2 = self.crop_pz_y1 + wys_k

        if self.crop_pz_x1 < 0:
            self.crop_pz_x1 = 0.0
            self.crop_pz_x2 = szer_k
        if self.crop_pz_y1 < 0:
            self.crop_pz_y1 = 0.0
            self.crop_pz_y2 = wys_k
        if self.crop_pz_x2 > self.SZEROKOSC_DOK_PZ:
            self.crop_pz_x2 = float(self.SZEROKOSC_DOK_PZ)
            self.crop_pz_x1 = self.crop_pz_x2 - szer_k
        if self.crop_pz_y2 > self.WYSOKOSC_DOK_PZ:
            self.crop_pz_y2 = float(self.WYSOKOSC_DOK_PZ)
            self.crop_pz_y1 = self.crop_pz_y2 - wys_k

        self._aktualizuj_kadrowanie_pz()

    def _dopasuj_pola_robocze_pod_obraz(self, sciezka: str):
        try:
            with Image.open(sciezka) as img:
                w_orig, h_orig = img.size
        except Exception:
            w_orig, h_orig = 1000, 1400

        self._ustaw_orientacje_sync([ft.DeviceOrientation.PORTRAIT_UP])

        max_w = self.MAX_SZEROKOSC_ROBOCZA_PZ
        max_h = self.MAX_WYSOKOSC_ROBOCZA_PZ

        proporcja = w_orig / max(1, h_orig)
        if (max_w / max_h) > proporcja:
            h_ramki = max_h
            w_ramki = round(max_h * proporcja)
        else:
            w_ramki = max_w
            h_ramki = round(max_w / proporcja)

        self.SZEROKOSC_DOK_PZ = max(140, int(w_ramki))
        self.WYSOKOSC_DOK_PZ = max(140, int(h_ramki))

        self.ramka_kadrowania_pz.width = self.SZEROKOSC_DOK_PZ
        self.ramka_kadrowania_pz.height = self.WYSOKOSC_DOK_PZ
        self.img_pelny_podglad_pz.width = self.SZEROKOSC_DOK_PZ
        self.img_pelny_podglad_pz.height = self.WYSOKOSC_DOK_PZ

        self.crop_pz_x1 = 0.0
        self.crop_pz_y1 = 0.0
        self.crop_pz_x2 = float(self.SZEROKOSC_DOK_PZ)
        self.crop_pz_y2 = float(self.WYSOKOSC_DOK_PZ)
        self.kadr_pz_zmieniony = False
        self._aktualizuj_kadrowanie_pz()

    def _ustaw_orientacje_sync(self, orientacje: list):
        plat = getattr(self.page, "platform", None)
        if plat in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS, "android", "ios"):
            try:
                res = self.page.set_allowed_device_orientations(orientacje)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                pass

    def _napraw_orientacje_exif(self, sciezka: str) -> str:
        """Fizycznie obraca plik zgodnie z tagiem EXIF aparatu."""
        try:
            with Image.open(sciezka) as img:
                img_poprawiony = ImageOps.exif_transpose(img)
                if img_poprawiony:
                    img_poprawiony.save(sciezka, quality=95)
        except Exception:
            pass
        return sciezka

    def ustaw_stan_przycisku_foto_pz(self, czy_ma_zdjecie: bool):
        self.kontener_podgladu_pz.visible = czy_ma_zdjecie
        self.btn_otworz_kadrowanie.visible = czy_ma_zdjecie
        self.btn_usun_zdjecie_pz.visible = czy_ma_zdjecie
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

        # Kluczowe: natychmiastowe wyrównanie orientacji EXIF
        self._napraw_orientacje_exif(nowa_sciezka)

        self.aktualne_zdjecie_pz["sciezka"] = nowa_sciezka
        self.historia_pz = [(nowa_sciezka, None)]
        self.aktywny_filtr_pz = None
        self._odswiez_styl_przyciskow_filtrow_pz()
        self.btn_pelny_cofnij.disabled = True

        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = nowa_sciezka
        self.img_pelny_podglad_pz.src = nowa_sciezka

        self.ustaw_stan_przycisku_foto_pz(True)
        self.status_text_pz.value = "Zdjęcie gotowe. Kliknij w podgląd, aby dopasować kadr."
        self.status_text_pz.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    async def otworz_pelny_podglad_pz(self, e):
        if not self.aktualne_zdjecie_pz["sciezka"] or not os.path.exists(self.aktualne_zdjecie_pz["sciezka"]):
            return

        self._dopasuj_pola_robocze_pod_obraz(self.aktualne_zdjecie_pz["sciezka"])
        self.img_pelny_podglad_pz.src = self.aktualne_zdjecie_pz["sciezka"]

        self.kolumna_glowna_pz.visible = False
        self.widok_kadrowania_pz.visible = True
        self.page.scroll = None
        self.page.update()

    async def _zamknij_pelny_ekran_pz(self, zapisz=False):
        self.widok_kadrowania_pz.visible = False
        self.kolumna_glowna_pz.visible = True
        self.page.scroll = ft.ScrollMode.AUTO

        self._ustaw_orientacje_sync([
            ft.DeviceOrientation.PORTRAIT_UP,
            ft.DeviceOrientation.LANDSCAPE_LEFT,
            ft.DeviceOrientation.LANDSCAPE_RIGHT,
        ])
        self.page.update()

    async def obroc_pz(self, kat: int):
        if not self.aktualne_zdjecie_pz["sciezka"] or not os.path.exists(self.aktualne_zdjecie_pz["sciezka"]):
            return

        sciezka_akt = self.aktualne_zdjecie_pz["sciezka"]
        self.historia_pz.append((sciezka_akt, self.aktywny_filtr_pz))
        self.btn_pelny_cofnij.disabled = False

        loop = asyncio.get_running_loop()
        nowa_sciezka = await loop.run_in_executor(
            None, core.obroc_plik_graficzny, sciezka_akt, kat, "rot_pz"
        )

        self.aktualne_zdjecie_pz["sciezka"] = str(nowa_sciezka)
        self.img_pelny_podglad_pz.src_base64 = None
        self.img_pelny_podglad_pz.src = str(nowa_sciezka)
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = str(nowa_sciezka)

        self._dopasuj_pola_robocze_pod_obraz(str(nowa_sciezka))
        self.page.update()

    async def _przelacz_filtr_pelny_pz(self, typ: str):
        if not self.aktualne_zdjecie_pz["sciezka"] or not os.path.exists(self.aktualne_zdjecie_pz["sciezka"]):
            return

        if self.aktywny_filtr_pz == typ:
            self._cofnij_krok_pelny_pz()
            return

        sciezka_akt = self.aktualne_zdjecie_pz["sciezka"]
        self.historia_pz.append((sciezka_akt, self.aktywny_filtr_pz))
        self.btn_pelny_cofnij.disabled = False

        loop = asyncio.get_running_loop()
        nowa_sciezka = await loop.run_in_executor(
            None, core.filtruj_plik_graficzny, sciezka_akt, typ
        )

        self.aktualne_zdjecie_pz["sciezka"] = str(nowa_sciezka)
        self.aktywny_filtr_pz = typ
        self.img_pelny_podglad_pz.src_base64 = None
        self.img_pelny_podglad_pz.src = str(nowa_sciezka)
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = str(nowa_sciezka)

        self._odswiez_styl_przyciskow_filtrow_pz()
        self.page.update()

    def _odswiez_styl_przyciskow_filtrow_pz(self):
        aktywny_kolor = ft.Colors.BLUE_700
        zwykly_kolor = ft.Colors.GREY_800

        self.btn_f_bw.style.bgcolor = aktywny_kolor if self.aktywny_filtr_pz == "bw" else zwykly_kolor
        self.btn_f_szary.style.bgcolor = aktywny_kolor if self.aktywny_filtr_pz == "szary" else zwykly_kolor
        self.btn_f_wyostrz.style.bgcolor = aktywny_kolor if self.aktywny_filtr_pz == "wyostrz" else zwykly_kolor

    async def _zatwierdz_krok_pelny_pz(self):
        if not self.aktualne_zdjecie_pz["sciezka"] or not os.path.exists(self.aktualne_zdjecie_pz["sciezka"]):
            return

        proc_lewo = (self.crop_pz_x1 / self.SZEROKOSC_DOK_PZ) * 100.0
        proc_gora = (self.crop_pz_y1 / self.WYSOKOSC_DOK_PZ) * 100.0
        proc_prawo = ((self.SZEROKOSC_DOK_PZ - self.crop_pz_x2) / self.SZEROKOSC_DOK_PZ) * 100.0
        proc_dol = ((self.WYSOKOSC_DOK_PZ - self.crop_pz_y2) / self.WYSOKOSC_DOK_PZ) * 100.0

        if proc_lewo <= 0.5 and proc_gora <= 0.5 and proc_prawo <= 0.5 and proc_dol <= 0.5:
            return

        sciezka_akt = self.aktualne_zdjecie_pz["sciezka"]
        self.historia_pz.append((sciezka_akt, self.aktywny_filtr_pz))
        self.btn_pelny_cofnij.disabled = False

        loop = asyncio.get_running_loop()
        wyciety_plik = await loop.run_in_executor(
            None, core.kadruj_plik_graficzny, sciezka_akt,
            proc_lewo, proc_gora, proc_prawo, proc_dol
        )

        self.aktualne_zdjecie_pz["sciezka"] = str(wyciety_plik)
        self.img_pelny_podglad_pz.src_base64 = None
        self.img_pelny_podglad_pz.src = str(wyciety_plik)
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = str(wyciety_plik)

        self._dopasuj_pola_robocze_pod_obraz(str(wyciety_plik))

    def _cofnij_krok_pelny_pz(self):
        if not self.historia_pz:
            return
        poprzednia_sciezka, poprzedni_filtr = self.historia_pz.pop()
        self.aktualne_zdjecie_pz["sciezka"] = str(poprzednia_sciezka)
        self.aktywny_filtr_pz = poprzedni_filtr

        self.img_pelny_podglad_pz.src_base64 = None
        self.img_pelny_podglad_pz.src = str(poprzednia_sciezka)
        self.podglad_obrazu_pz.src_base64 = None
        self.podglad_obrazu_pz.src = str(poprzednia_sciezka)

        self._dopasuj_pola_robocze_pod_obraz(str(poprzednia_sciezka))
        self._odswiez_styl_przyciskow_filtrow_pz()
        self.btn_pelny_cofnij.disabled = (len(self.historia_pz) == 0)
        self.page.update()

    async def _wyslij_pelny_ekran_pz(self):
        if self.kadr_pz_zmieniony:
            await self._zatwierdz_krok_pelny_pz()
        await self._zamknij_pelny_ekran_pz(zapisz=True)
        await self.przetworz_plik_pz(self.aktualne_zdjecie_pz["sciezka"])

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
        self.podglad_obrazu_pz.src_base64 = None
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

                self.ui.dopisz_log(f"Sprawdzanie stanu serwera LM Studio ({ip_lokalne}:{port_lokalny})...")
                serwer_zyje = await core.sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0)
                if not serwer_zyje:
                    self.ui.dopisz_log("Serwer lokalny nie odpowiada. Wysyłanie WoL...", ft.Colors.AMBER)
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
                            self.ui.dopisz_log(f"Serwer LM Studio gotowy po {czas_miniony}s!", ft.Colors.GREEN)
                            break

                    if not serwer_zyje:
                        raise TimeoutError(f"Serwer pod adresem {ip_lokalne} nie uruchomił się w czasie {maks_czas_oczekiwania}s.")

            wymiar_obrazu = aktualny_konfig.get("image_resolution", 1800)
            base64_image = await loop.run_in_executor(None, core.kompresuj_do_base64, sciezka_obrazu, wymiar_obrazu)
            
            try:
                with Image.open(sciezka_obrazu) as img:
                    w_px, h_px = img.size
            except Exception:
                w_px, h_px = "?", "?"

            waga_b64_kb = round(len(base64_image) * 0.75 / 1024, 1)
            self.ui.dopisz_log(f"📷 Obraz: {w_px}x{h_px}px | Waga: {waga_b64_kb} KB (kompresja z {waga_oryg_kb} KB)", ft.Colors.GREY_400)

            prompt = (
                "Rola: Działasz jako precyzyjny, deterministyczny system OCR wyspecjalizowany w polskich dokumentach "
                "magazynowo-handlowych (faktury VAT, WZ, PZ). Ekstrahuj dane WYŁĄCZNIE na podstawie tego, co widoczne "
                "na obrazie. Zakaz zgadywania i konfabulacji: jeśli dana wartość jest nieczytelna, zamazana albo nie "
                "występuje na dokumencie, zwróć dla niej pusty ciąg znaków \"\" zamiast zgadywać.\n\n"
                "1. Nagłówek i kontrahenci:\n"
                "   - nr: pełny numer dokumentu z nagłówka. Ignoruj puste pola powiązane, np. niewypełnione 'Realizacja faktury nr:'.\n"
                "   - dt: data wystawienia/sprzedaży w formacie DD.MM.RRRR.\n"
                "   - w, o: nazwa oraz 10-cyfrowy NIP (same cyfry, bez 'PL', spacji i myślników) odpowiednio dla "
                "sprzedawcy/wystawcy (w) i nabywcy/odbiorcy (o). NIP pobieraj WYŁĄCZNIE z bloku danych adresowych "
                "firmy. Nigdy nie myl NIP-u z numerem rachunku bankowego, numerem BDO ani numerem dokumentu.\n\n"
                "2. Pozycje towarowe (tabela główna, klucz \"p\") – ZWRACAJ ŚCISŁĄ UWAGĘ NA NAGŁÓWKI KOLUMN:\n"
                "   - n: pełna nazwa towaru z kolumny 'Towar' / 'Nazwa'.\n"
                "   - k: kod towaru. POBIERAJ WYŁĄCZNIE z kolumn oznaczonych jako 'EAN', 'Kod', 'CN', 'PKWiU', 'Indeks':\n"
                "       * Jeśli taka kolumna jest pusta dla danej pozycji, wpisz pusty ciąg znaków: \"\".\n"
                "       * BEZWZGLĘDNY ZAKAZ: NIGDY nie pobieraj wartości z kolumn 'Partia', 'Nr partii', 'Seria', "
                "'Batch', 'Lot', 'L/N' ani z dat przydatności! Nawet jeśli numer partii ma 8 cyfr i wygląda jak kod, "
                "NIE JEST to kod towaru — w takim przypadku k musi zostać puste: \"\".\n"
                "   - j: jednostka miary DOKŁADNIE z kolumny 'JM' ('kg', 'szt', 'op').\n"
                "   - i: ilość z kolumny 'Ilość':\n"
                "       * Jeśli j to 'szt' lub 'op': ilość MUSI być liczbą całkowitą. Nie wolno podawać ułamków dla sztuk!\n"
                "       * Jeśli j to 'kg': przepisz dokładnie wagę z kropką jako separatorem.\n"
                "   - c: ostateczna cena jednostkowa netto PO RABACIE. WAŻNE: Jeśli w tabeli są obok siebie dwie kolumny "
                "('Cena net bez rab.' oraz 'Cena netto'), ZAWSZE wybieraj wartość z kolumny 'Cena netto' (faktyczna cena po rabacie).\n"
                "   - w: wartość netto TEJ POZYCJI z kolumny 'Wartość netto'.\n\n"
                "3. Podsumowanie:\n"
                "   - sn: całkowita wartość netto dokumentu, z wiersza sumarycznego 'Razem' pod tabelą rozliczenia "
                "podatku. Kategoryczny zakaz pobierania kwoty z pojedynczych wierszy cząstkowych stawek VAT.\n"
                "   - dz: ostateczna kwota do zapłaty / suma brutto (jeśli występuje na dokumencie, w przeciwnym razie \"\").\n\n"
                "Formatowanie: wszystkie liczby z kropką jako separatorem dziesiętnym. Nie wstawiaj kresek ani spacji w NIP-ie.\n\n"
                "Zwróć WYŁĄCZNIE surowy, poprawny obiekt JSON — bez znaczników markdown (bez ```json, bez ```), bez "
                "żadnego tekstu przed ani po nim:\n"
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

            self.ui.dopisz_log(f"🌐 Wysyłanie zapytania do: {cel_logu}...")

            max_prob = 4
            opoznienie_poczatkowe = 2.0
            odpowiedz = None
            timeout_cfg = httpx.Timeout(10.0, read=300.0)

            start_siec = time.perf_counter()
            async with httpx.AsyncClient(timeout=timeout_cfg, verify=True) as client:
                for proba in range(max_prob):
                    if proba > 0:
                        self.ui.dopisz_log(f"Ponawianie zapytania (próba {proba + 1}/{max_prob})...", ft.Colors.AMBER)
                    odpowiedz = await client.post(pelny_url, headers=naglowki, json=cialo_zapytania)

                    if odpowiedz.status_code in [503, 429]:
                        if proba < max_prob - 1:
                            czas_oczekiwania = opoznienie_poczatkowe * (2 ** proba)
                            self.status_text_pz.value = f"Serwer zajęty ({odpowiedz.status_code}). Ponawianie za {czas_oczekiwania:.1f}s..."
                            self.status_text_pz.color = ft.Colors.AMBER_ACCENT
                            self.page.update()
                            await asyncio.sleep(czas_oczekiwania)
                            continue

                    odpowiedz.raise_for_status()
                    break

            czas_siec = time.perf_counter() - start_siec
            dane_odp = odpowiedz.json()
            wybor = dane_odp["choices"][0]
            odp_tekst = (wybor.get("message", {}).get("content") or "").strip()
            powod_konca = wybor.get("finish_reason")

            uzycie = dane_odp.get("usage") or {}
            in_tok = uzycie.get("prompt_tokens", 0)
            out_tok = uzycie.get("completion_tokens", 0)
            detale_out = uzycie.get("completion_tokens_details") or {}
            think_tok = detale_out.get("reasoning_tokens")

            predkosc = (out_tok / czas_siec) if (czas_siec > 0 and out_tok > 0) else 0.0

            log_wydajnosc = f"⏱️ Czas AI: {czas_siec:.2f}s | Tokeny: {in_tok} wejście / {out_tok} wyjście"
            if think_tok:
                log_wydajnosc += f" (myślenie: {think_tok})"
            if predkosc > 0:
                log_wydajnosc += f" | Prędkość: {predkosc:.1f} tok/s"
            self.ui.dopisz_log(log_wydajnosc, ft.Colors.CYAN)

            if powod_konca == "length":
                self.ui.dopisz_log("⚠️ OSTRZEŻENIE: Odpowiedź modelu została ucięta (limit tokenów)!", ft.Colors.RED)

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

        except httpx.HTTPStatusError as http_err:
            status = http_err.response.status_code
            tresc = http_err.response.text[:350]
            self.ui.dopisz_log(f"Błąd HTTP {status}: {tresc}", ft.Colors.RED)
            if status in (401, 403) or "API_KEY_INVALID" in tresc:
                self.status_text_pz.value = "Błąd autoryzacji API"
                self.ui.pokaz_okno_bledu("🔑 Błąd autoryzacji", "Klucz API jest nieprawidłowy lub brak uprawnień. Sprawdź ustawienia.")
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
            self.btn_otworz_kadrowanie.visible = czy_ma_foto
            self.btn_usun_zdjecie_pz.visible = czy_ma_foto
            self.page.update()
