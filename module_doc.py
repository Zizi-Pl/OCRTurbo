import os
import re
import shutil
import asyncio
from datetime import datetime
import flet as ft
import httpx
from PIL import Image

import config
import core


class ModulDocMixin:
    def _inicjalizuj_modul_dokument(self):
        # Wymiary robocze obszaru kadrowania (zbieżne z PZ)
        self.SZEROKOSC_DOK_DOC = 360
        self.WYSOKOSC_DOK_DOC = 600
        self.UCHWYT_ROZMIAR_DOK_DOC = 48

        self.crop_doc_x1 = 0.0
        self.crop_doc_y1 = 0.0
        self.crop_doc_x2 = float(self.SZEROKOSC_DOK_DOC)
        self.crop_doc_y2 = float(self.WYSOKOSC_DOK_DOC)
        self.kadr_doc_zmieniony = False

        self.historia_doc = []
        self.aktywny_filtr_doc = None
        self.ostatni_wynik_dok = {"tekst": None}
        self.zdjecie_dok = {"sciezka": None}

        # 1. Podgląd na ekranie głównym Modułu Dok
        self.podglad_obrazu_dok = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit="contain",
            width=320,
            height=240
        )

        # 2. Obraz na dedykowanym pełnym ekranie kadrowania
        self.img_pelny_podglad_doc = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit="fill",
            width=self.SZEROKOSC_DOK_DOC,
            height=self.WYSOKOSC_DOK_DOC
        )

        self.maska_doc_gora = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, left=0, width=self.SZEROKOSC_DOK_DOC, height=0)
        self.maska_doc_dol = ft.Container(bgcolor=ft.Colors.BLACK54, bottom=0, left=0, width=self.SZEROKOSC_DOK_DOC, height=0)
        self.maska_doc_lewo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, left=0, width=0)
        self.maska_doc_prawo = ft.Container(bgcolor=ft.Colors.BLACK54, top=0, bottom=0, right=0, width=0)

        self.strefa_srodka_doc = ft.GestureDetector(
            content=ft.Container(
                border=ft.Border.all(2.0, ft.Colors.BLUE_ACCENT),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLUE_ACCENT)
            ),
            drag_interval=10,
            on_pan_update=lambda e: self._przesun_caly_kadr_doc(*self._pobierz_deltas_doc(e)),
            top=0, left=0, width=self.SZEROKOSC_DOK_DOC, height=self.WYSOKOSC_DOK_DOC
        )

        def stworz_uchwyt_doc():
            return ft.Container(
                alignment=ft.Alignment(0, 0),
                content=ft.Container(
                    width=28, height=28,
                    bgcolor=ft.Colors.BLUE_ACCENT,
                    border_radius=14,
                    border=ft.Border.all(2.5, ft.Colors.WHITE)
                ),
                width=self.UCHWYT_ROZMIAR_DOK_DOC,
                height=self.UCHWYT_ROZMIAR_DOK_DOC
            )

        self.uchwyt_doc_lt = ft.GestureDetector(content=stworz_uchwyt_doc(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_doc("lt", *self._pobierz_deltas_doc(e)), top=0, left=0)
        self.uchwyt_doc_rt = ft.GestureDetector(content=stworz_uchwyt_doc(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_doc("rt", *self._pobierz_deltas_doc(e)), top=0, left=self.SZEROKOSC_DOK_DOC - self.UCHWYT_ROZMIAR_DOK_DOC)
        self.uchwyt_doc_lb = ft.GestureDetector(content=stworz_uchwyt_doc(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_doc("lb", *self._pobierz_deltas_doc(e)), top=self.WYSOKOSC_DOK_DOC - self.UCHWYT_ROZMIAR_DOK_DOC, left=0)
        self.uchwyt_doc_rb = ft.GestureDetector(content=stworz_uchwyt_doc(), drag_interval=10, on_pan_update=lambda e: self._przesun_uchwyt_doc("rb", *self._pobierz_deltas_doc(e)), top=self.WYSOKOSC_DOK_DOC - self.UCHWYT_ROZMIAR_DOK_DOC, left=self.SZEROKOSC_DOK_DOC - self.UCHWYT_ROZMIAR_DOK_DOC)

        self.ramka_kadrowania_doc = ft.Container(
            content=ft.Stack([
                self.img_pelny_podglad_doc,
                self.maska_doc_gora, self.maska_doc_dol, self.maska_doc_lewo, self.maska_doc_prawo,
                self.strefa_srodka_doc,
                self.uchwyt_doc_lt, self.uchwyt_doc_rt, self.uchwyt_doc_lb, self.uchwyt_doc_rb
            ]),
            width=self.SZEROKOSC_DOK_DOC,
            height=self.WYSOKOSC_DOK_DOC,
            alignment=ft.Alignment(0, 0)
        )

        # Górna belka: Obrót Lewo | Filtry B&W, GRY, SHP | Obrót Prawo (duże przyciski 58px)
        self.btn_obrot_l_doc = ft.IconButton(
            icon=ft.Icons.ROTATE_LEFT, icon_color=ft.Colors.WHITE, icon_size=34,
            width=62, height=58,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=10)),
            tooltip="Obróć w lewo (90°)",
            on_click=lambda e: asyncio.create_task(self.obroc_dok(90))
        )
        self.btn_f_bw_doc = ft.Button(
            content=ft.Text("B&W", size=14, weight=ft.FontWeight.BOLD),
            height=58, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_doc("bw"))
        )
        self.btn_f_szary_doc = ft.Button(
            content=ft.Text("GRY", size=14, weight=ft.FontWeight.BOLD),
            height=58, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_doc("szary"))
        )
        self.btn_f_wyostrz_doc = ft.Button(
            content=ft.Text("SHP", size=14, weight=ft.FontWeight.BOLD),
            height=58, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._przelacz_filtr_pelny_doc("wyostrz"))
        )
        self.btn_obrot_r_doc = ft.IconButton(
            icon=ft.Icons.ROTATE_RIGHT, icon_color=ft.Colors.WHITE, icon_size=34,
            width=62, height=58,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, shape=ft.RoundedRectangleBorder(radius=10)),
            tooltip="Obróć w prawo (90°)",
            on_click=lambda e: asyncio.create_task(self.obroc_dok(-90))
        )

        self.wiersz_filtrow_doc = ft.Row([
            self.btn_obrot_l_doc,
            self.btn_f_bw_doc,
            self.btn_f_szary_doc,
            self.btn_f_wyostrz_doc,
            self.btn_obrot_r_doc
        ], spacing=4)

        # Przyciski dolne ekranu kadrowania (wysokość 60px)
        self.btn_pelny_anuluj_doc = ft.Button(
            content=ft.Text("Anuluj", size=15, weight=ft.FontWeight.BOLD),
            height=60, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._zamknij_pelny_ekran_doc(zapisz=False))
        )
        self.btn_pelny_cofnij_doc = ft.Button(
            content=ft.Text("Cofnij", size=15, weight=ft.FontWeight.BOLD),
            height=60, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            disabled=True,
            on_click=lambda e: self._cofnij_krok_pelny_doc()
        )
        self.btn_pelny_zatwierdz_doc = ft.Button(
            content=ft.Text("Zatwierdź", size=15, weight=ft.FontWeight.BOLD),
            height=60, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._zatwierdz_krok_pelny_doc())
        )
        self.btn_pelny_wyslij_doc = ft.Button(
            content=ft.Text("Wyślij", size=15, weight=ft.FontWeight.BOLD),
            height=60, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10), padding=0),
            on_click=lambda e: asyncio.create_task(self._wyslij_pelny_ekran_doc())
        )
        self.wiersz_akcji_pelnych_doc = ft.Row([
            self.btn_pelny_anuluj_doc,
            self.btn_pelny_cofnij_doc,
            self.btn_pelny_zatwierdz_doc,
            self.btn_pelny_wyslij_doc
        ], spacing=6)

        # Dedykowany widok kadrowania w kontenerze
        self.widok_kadrowania_doc = ft.Container(
            content=ft.Column([
                self.wiersz_filtrow_doc,
                ft.Container(content=self.ramka_kadrowania_doc, alignment=ft.Alignment(0, 0), expand=True),
                self.wiersz_akcji_pelnych_doc
            ], spacing=8, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=8,
            expand=True,
            visible=False
        )

        # Kontrolki ekranu głównego modułu dokumentu
        self.status_dok = ft.Text("Zrób zdjęcie lub wybierz dokument z galerii.", size=12, color=ft.Colors.BLUE_200, text_align=ft.TextAlign.CENTER)
        self.pasek_dok = ft.ProgressBar(visible=False, color=ft.Colors.BLUE_ACCENT)

        self.btn_foto_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("Wybierz z galerii")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.wybierz_foto_dok
        )
        self.btn_aparat_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("Zrób zdjęcie")]),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.ui.otworz_aparat_dla("dokument"))
        )
        self.wiersz_wyboru_zdjecia_dok = ft.Row([self.btn_foto_dok, self.btn_aparat_dok], spacing=10)

        self.kontener_podgladu_dok = ft.Container(
            content=ft.GestureDetector(
                content=self.podglad_obrazu_dok,
                on_tap=lambda e: asyncio.create_task(self.otworz_pelny_podglad_dok(e))
            ),
            alignment=ft.Alignment(0, 0),
            height=250,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            visible=False
        )

        self.btn_otworz_kadrowanie_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CROP, size=20), ft.Text("Dopasuj kadr / Filtry", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_pelny_podglad_dok(e))
        )

        self.btn_start_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=24), ft.Text("Rozpocznij odczyt dokumentu", size=15, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, disabled=True, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.AMBER_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.analizuj_dokument_dok
        )

        self.btn_wroc_wynik_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.HISTORY, size=18), ft.Text("Wróć do ostatnich wyników odczytu", size=12)], alignment=ft.MainAxisAlignment.CENTER),
            visible=False, height=44,
            style=ft.ButtonStyle(bgcolor=ft.Colors.TEAL_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.klik_wroc_do_wynikow_dok
        )

        # Edytor wyników i przyciski eksportu
        self.txt_edytor_dok = ft.TextField(
            multiline=True, min_lines=12, max_lines=24, text_size=12, dense=True,
            border_color=ft.Colors.BLUE_GREY_700, bgcolor=ft.Colors.GREY_900, border_radius=8
        )

        self.btn_kopiuj_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.COPY, size=18), ft.Text("Kopiuj", size=12, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=44, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.kopiuj_do_schowka_dok
        )
        self.btn_zapisz_txt_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.TEXT_SNIPPET, size=18), ft.Text(".TXT", size=12, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=44, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.udostepnij_tekst_dok
        )
        self.btn_zapisz_docx_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.DESCRIPTION, size=18), ft.Text(".DOCX", size=12, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=44, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.udostepnij_docx_dok
        )
        self.btn_zapisz_xlsx_dok = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.TABLE_CHART, size=18), ft.Text(".XLSX", size=12, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=44, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.udostepnij_xlsx_dok
        )

        self.dlg_wynik_dok = ft.AlertDialog(
            modal=True,
            inset_padding=ft.Padding(10, 20, 10, 20),
            title=ft.Row([
                ft.Icon(ft.Icons.ARTICLE, color=ft.Colors.BLUE_400),
                ft.Text("Wynik odczytu", size=18, weight=ft.FontWeight.BOLD)
            ], spacing=8),
            content=ft.Container(
                content=ft.Column([
                    ft.Row([self.btn_kopiuj_dok, self.btn_zapisz_txt_dok], spacing=8),
                    ft.Row([self.btn_zapisz_docx_dok, self.btn_zapisz_xlsx_dok], spacing=8),
                    ft.Divider(height=10, color=ft.Colors.GREY_800),
                    self.txt_edytor_dok
                ], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO),
                width=450
            ),
            actions=[
                ft.Button("Zamknij", on_click=lambda e: self.zamknij_dlg_wynik_dok())
            ]
        )

        # Belka tytułowa z ikoną konsoli logów (identycznie jak w module PZ)
        self.btn_konsola_dok = ft.IconButton(
            icon=ft.Icons.TERMINAL,
            tooltip="Konsola zdarzeń (logi)",
            on_click=self.ui.otworz_konsole
        )

        pasek_tytulu_dok = ft.Row(
            [
                ft.Row([
                    ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Menu Główne", on_click=lambda e: asyncio.create_task(self.przelacz_widok("menu"))),
                    ft.Column([
                        ft.Text("Odczyt Dokumentu (1:1)", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_400),
                        ft.Text("Zaznacz kadr lub odczytaj całość do TXT, Word lub Excel", size=11, color=ft.Colors.GREY_400)
                    ], spacing=1)
                ], spacing=4, expand=True),
                self.btn_konsola_dok
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        # Główna kolumna formularza Modułu Dokumentów
        self.kolumna_glowna_doc = ft.Column([
            pasek_tytulu_dok,
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self.wiersz_wyboru_zdjecia_dok,
            self.pasek_dok,
            self.status_dok,
            self.kontener_podgladu_dok,
            self.btn_otworz_kadrowanie_dok,
            self.btn_start_dok,
            self.btn_wroc_wynik_dok
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        # Kontener nadrzędny widoku dokumentów
        self.widok_dokument = ft.Column([
            self.kolumna_glowna_doc,
            self.widok_kadrowania_doc
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0, visible=False)

    # --- METODY KADROWANIA I GESTÓW (ZGODNE Z PZ) ---
    def _pobierz_deltas_doc(self, e):
        dx = getattr(e, "delta", None)
        if dx is not None:
            return e.delta.x, e.delta.y
        loc = getattr(e, "local_delta", None)
        if loc is not None:
            return e.local_delta.x, e.local_delta.y
        return getattr(e, "delta_x", 0.0), getattr(e, "delta_y", 0.0)

    def _aktualizuj_kadrowanie_doc(self):
        w = self.SZEROKOSC_DOK_DOC
        h = self.WYSOKOSC_DOK_DOC

        self.crop_doc_x1 = max(0.0, min(self.crop_doc_x1, w - self.UCHWYT_ROZMIAR_DOK_DOC))
        self.crop_doc_y1 = max(0.0, min(self.crop_doc_y1, h - self.UCHWYT_ROZMIAR_DOK_DOC))
        self.crop_doc_x2 = max(self.crop_doc_x1 + self.UCHWYT_ROZMIAR_DOK_DOC, min(self.crop_doc_x2, float(w)))
        self.crop_doc_y2 = max(self.crop_doc_y1 + self.UCHWYT_ROZMIAR_DOK_DOC, min(self.crop_doc_y2, float(h)))

        x1, y1, x2, y2 = self.crop_doc_x1, self.crop_doc_y1, self.crop_doc_x2, self.crop_doc_y2

        self.maska_doc_gora.height = y1
        self.maska_doc_dol.height = h - y2
        self.maska_doc_lewo.top = y1
        self.maska_doc_lewo.height = y2 - y1
        self.maska_doc_lewo.width = x1
        self.maska_doc_prawo.top = y1
        self.maska_doc_prawo.height = y2 - y1
        self.maska_doc_prawo.width = w - x2

        self.strefa_srodka_doc.top = y1
        self.strefa_srodka_doc.left = x1
        self.strefa_srodka_doc.width = x2 - x1
        self.strefa_srodka_doc.height = y2 - y1

        self.uchwyt_doc_lt.top = y1
        self.uchwyt_doc_lt.left = x1
        self.uchwyt_doc_rt.top = y1
        self.uchwyt_doc_rt.left = x2 - self.UCHWYT_ROZMIAR_DOK_DOC
        self.uchwyt_doc_lb.top = y2 - self.UCHWYT_ROZMIAR_DOK_DOC
        self.uchwyt_doc_lb.left = x1
        self.uchwyt_doc_rb.top = y2 - self.UCHWYT_ROZMIAR_DOK_DOC
        self.uchwyt_doc_rb.left = x2 - self.UCHWYT_ROZMIAR_DOK_DOC
        self.page.update()

    def _przesun_uchwyt_doc(self, ktory: str, dx: float, dy: float):
        self.kadr_doc_zmieniony = True
        if ktory == "lt":
            self.crop_doc_x1 += dx
            self.crop_doc_y1 += dy
        elif ktory == "rt":
            self.crop_doc_x2 += dx
            self.crop_doc_y1 += dy
        elif ktory == "lb":
            self.crop_doc_x1 += dx
            self.crop_doc_y2 += dy
        elif ktory == "rb":
            self.crop_doc_x2 += dx
            self.crop_doc_y2 += dy
        self._aktualizuj_kadrowanie_doc()

    def _przesun_caly_kadr_doc(self, dx: float, dy: float):
        self.kadr_doc_zmieniony = True
        szer_k = self.crop_doc_x2 - self.crop_doc_x1
        wys_k = self.crop_doc_y2 - self.crop_doc_y1

        self.crop_doc_x1 += dx
        self.crop_doc_y1 += dy
        self.crop_doc_x2 = self.crop_doc_x1 + szer_k
        self.crop_doc_y2 = self.crop_doc_y1 + wys_k

        if self.crop_doc_x1 < 0:
            self.crop_doc_x1 = 0.0
            self.crop_doc_x2 = szer_k
        if self.crop_doc_y1 < 0:
            self.crop_doc_y1 = 0.0
            self.crop_doc_y2 = wys_k
        if self.crop_doc_x2 > self.SZEROKOSC_DOK_DOC:
            self.crop_doc_x2 = float(self.SZEROKOSC_DOK_DOC)
            self.crop_doc_x1 = self.crop_doc_x2 - szer_k
        if self.crop_doc_y2 > self.WYSOKOSC_DOK_DOC:
            self.crop_doc_y2 = float(self.WYSOKOSC_DOK_DOC)
            self.crop_doc_y1 = self.crop_doc_y2 - wys_k

        self._aktualizuj_kadrowanie_doc()

    def _dopasuj_pola_robocze_pod_obraz_doc(self, sciezka: str):
        try:
            with Image.open(sciezka) as img:
                w_orig, h_orig = img.size
        except Exception:
            w_orig, h_orig = 1000, 1400

        czy_poziom = (w_orig > h_orig)
        if czy_poziom:
            max_w, max_h = 640.0, 310.0
        else:
            max_w, max_h = 360.0, 560.0

        proporcja = w_orig / max(1, h_orig)
        if proporcja >= (max_w / max_h):
            w_ramki = max_w
            h_ramki = round(max_w / proporcja)
        else:
            h_ramki = max_h
            w_ramki = round(max_h * proporcja)

        self.SZEROKOSC_DOK_DOC = max(180, int(w_ramki))
        self.WYSOKOSC_DOK_DOC = max(180, int(h_ramki))

        self.ramka_kadrowania_doc.width = self.SZEROKOSC_DOK_DOC
        self.ramka_kadrowania_doc.height = self.WYSOKOSC_DOK_DOC
        self.img_pelny_podglad_doc.width = self.SZEROKOSC_DOK_DOC
        self.img_pelny_podglad_doc.height = self.WYSOKOSC_DOK_DOC

        self.crop_doc_x1 = 0.0
        self.crop_doc_y1 = 0.0
        self.crop_doc_x2 = float(self.SZEROKOSC_DOK_DOC)
        self.crop_doc_y2 = float(self.WYSOKOSC_DOK_DOC)
        self.kadr_doc_zmieniony = False
        self._aktualizuj_kadrowanie_doc()

    def resetuj_kadr_doc(self):
        self.crop_doc_x1 = 0.0
        self.crop_doc_y1 = 0.0
        self.crop_doc_x2 = float(self.SZEROKOSC_DOK_DOC)
        self.crop_doc_y2 = float(self.WYSOKOSC_DOK_DOC)
        self.kadr_doc_zmieniony = False
        self._aktualizuj_kadrowanie_doc()

    def ustaw_nowy_obraz_dok(self, sciezka: str):
        nowa_sciezka = os.path.join(config.KATALOG_DANYCH, f"img_dok_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        try:
            shutil.copyfile(sciezka, nowa_sciezka)
        except Exception:
            nowa_sciezka = sciezka

        self.zdjecie_dok["sciezka"] = nowa_sciezka
        self.historia_doc = [(nowa_sciezka, None)]
        self.aktywny_filtr_doc = None
        self._odswiez_styl_przyciskow_filtrow_doc()
        self.btn_pelny_cofnij_doc.disabled = True

        self.podglad_obrazu_dok.src_base64 = None
        self.podglad_obrazu_dok.src = nowa_sciezka
        self.img_pelny_podglad_doc.src = nowa_sciezka

        self.kontener_podgladu_dok.visible = True
        self.btn_otworz_kadrowanie_dok.visible = True
        self.btn_start_dok.visible = True
        self.btn_start_dok.disabled = False
        self.status_dok.value = "Zdjęcie gotowe. Kliknij w podgląd, aby dopasować kadr lub rozpocznij odczyt."
        self.status_dok.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    async def otworz_pelny_podglad_dok(self, e):
        if not self.zdjecie_dok["sciezka"] or not os.path.exists(self.zdjecie_dok["sciezka"]):
            return

        self._dopasuj_pola_robocze_pod_obraz_doc(self.zdjecie_dok["sciezka"])
        self.img_pelny_podglad_doc.src = self.zdjecie_dok["sciezka"]

        self.kolumna_glowna_doc.visible = False
        self.widok_kadrowania_doc.visible = True
        self.page.scroll = None
        self.page.update()

    async def _zamknij_pelny_ekran_doc(self, zapisz=False):
        self.widok_kadrowania_doc.visible = False
        self.kolumna_glowna_doc.visible = True
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.update()

    async def obroc_dok(self, kat: int):
        if not self.zdjecie_dok["sciezka"] or not os.path.exists(self.zdjecie_dok["sciezka"]):
            return

        sciezka_akt = self.zdjecie_dok["sciezka"]
        self.historia_doc.append((sciezka_akt, self.aktywny_filtr_doc))
        self.btn_pelny_cofnij_doc.disabled = False

        loop = asyncio.get_running_loop()
        nowa_sciezka = await loop.run_in_executor(
            None, core.obroc_plik_graficzny, sciezka_akt, kat, "rot_dok"
        )

        self.zdjecie_dok["sciezka"] = str(nowa_sciezka)
        self.img_pelny_podglad_doc.src_base64 = None
        self.img_pelny_podglad_doc.src = str(nowa_sciezka)
        self.podglad_obrazu_dok.src_base64 = None
        self.podglad_obrazu_dok.src = str(nowa_sciezka)

        self._dopasuj_pola_robocze_pod_obraz_doc(str(nowa_sciezka))
        self.page.update()

    async def _przelacz_filtr_pelny_doc(self, typ: str):
        if not self.zdjecie_dok["sciezka"] or not os.path.exists(self.zdjecie_dok["sciezka"]):
            return

        if self.aktywny_filtr_doc == typ:
            self._cofnij_krok_pelny_doc()
            return

        sciezka_akt = self.zdjecie_dok["sciezka"]
        self.historia_doc.append((sciezka_akt, self.aktywny_filtr_doc))
        self.btn_pelny_cofnij_doc.disabled = False

        loop = asyncio.get_running_loop()
        nowa_sciezka = await loop.run_in_executor(
            None, core.filtruj_plik_graficzny, sciezka_akt, typ
        )

        self.zdjecie_dok["sciezka"] = nowa_sciezka
        self.aktywny_filtr_doc = typ
        self.img_pelny_podglad_doc.src_base64 = None
        self.img_pelny_podglad_doc.src = nowa_sciezka
        self.podglad_obrazu_dok.src_base64 = None
        self.podglad_obrazu_dok.src = nowa_sciezka

        self._odswiez_styl_przyciskow_filtrow_doc()
        self.page.update()

    def _odswiez_styl_przyciskow_filtrow_doc(self):
        aktywny_kolor = ft.Colors.BLUE_700
        zwykly_kolor = ft.Colors.GREY_800

        self.btn_f_bw_doc.style.bgcolor = aktywny_kolor if self.aktywny_filtr_doc == "bw" else zwykly_kolor
        self.btn_f_szary_doc.style.bgcolor = aktywny_kolor if self.aktywny_filtr_doc == "szary" else zwykly_kolor
        self.btn_f_wyostrz_doc.style.bgcolor = aktywny_kolor if self.aktywny_filtr_doc == "wyostrz" else zwykly_kolor

    async def _zatwierdz_krok_pelny_doc(self):
        if not self.zdjecie_dok["sciezka"] or not os.path.exists(self.zdjecie_dok["sciezka"]):
            return

        proc_lewo = (self.crop_doc_x1 / self.SZEROKOSC_DOK_DOC) * 100.0
        proc_gora = (self.crop_doc_y1 / self.WYSOKOSC_DOK_DOC) * 100.0
        proc_prawo = ((self.SZEROKOSC_DOK_DOC - self.crop_doc_x2) / self.SZEROKOSC_DOK_DOC) * 100.0
        proc_dol = ((self.WYSOKOSC_DOK_DOC - self.crop_doc_y2) / self.WYSOKOSC_DOK_DOC) * 100.0

        if proc_lewo == 0.0 and proc_gora == 0.0 and proc_prawo == 0.0 and proc_dol == 0.0:
            return

        sciezka_akt = self.zdjecie_dok["sciezka"]
        self.historia_doc.append((sciezka_akt, self.aktywny_filtr_doc))
        self.btn_pelny_cofnij_doc.disabled = False

        loop = asyncio.get_running_loop()
        wyciety_plik = await loop.run_in_executor(
            None, core.kadruj_plik_graficzny, sciezka_akt,
            proc_lewo, proc_gora, proc_prawo, proc_dol
        )

        self.zdjecie_dok["sciezka"] = wyciety_plik
        self.img_pelny_podglad_doc.src_base64 = None
        self.img_pelny_podglad_doc.src = wyciety_plik
        self.podglad_obrazu_dok.src_base64 = None
        self.podglad_obrazu_dok.src = wyciety_plik

        self._dopasuj_pola_robocze_pod_obraz_doc(wyciety_plik)

    def _cofnij_krok_pelny_doc(self):
        if not self.historia_doc:
            return
        poprzednia_sciezka, poprzedni_filtr = self.historia_doc.pop()
        self.zdjecie_dok["sciezka"] = poprzednia_sciezka
        self.aktywny_filtr_doc = poprzedni_filtr

        self.img_pelny_podglad_doc.src_base64 = None
        self.img_pelny_podglad_doc.src = poprzednia_sciezka
        self.podglad_obrazu_dok.src_base64 = None
        self.podglad_obrazu_dok.src = poprzednia_sciezka

        self._dopasuj_pola_robocze_pod_obraz_doc(poprzednia_sciezka)
        self._odswiez_styl_przyciskow_filtrow_doc()
        self.btn_pelny_cofnij_doc.disabled = (len(self.historia_doc) == 0)
        self.page.update()

    async def _wyslij_pelny_ekran_doc(self):
        if self.kadr_doc_zmieniony:
            await self._zatwierdz_krok_pelny_doc()
        await self._zamknij_pelny_ekran_doc(zapisz=True)
        await self.analizuj_dokument_dok(None)

    # --- OCR DOKUMENTU ---
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

        # Waga pliku przed kadrowaniem
        waga_oryg_kb = round(os.path.getsize(sciezka_do_analizy) / 1024, 1)

        if self.kadr_doc_zmieniony:
            proc_lewo = (self.crop_doc_x1 / self.SZEROKOSC_DOK_DOC) * 100.0
            proc_gora = (self.crop_doc_y1 / self.WYSOKOSC_DOK_DOC) * 100.0
            proc_prawo = ((self.SZEROKOSC_DOK_DOC - self.crop_doc_x2) / self.SZEROKOSC_DOK_DOC) * 100.0
            proc_dol = ((self.WYSOKOSC_DOK_DOC - self.crop_doc_y2) / self.WYSOKOSC_DOK_DOC) * 100.0
            sciezka_do_analizy = await loop.run_in_executor(
                None, core.kadruj_plik_graficzny, self.zdjecie_dok["sciezka"],
                proc_lewo, proc_gora, proc_prawo, proc_dol
            )
            self.ui.dopisz_log(f"✂️ Zastosowano kadr: L={proc_lewo:.0f}%, T={proc_gora:.0f}%, R={proc_prawo:.0f}%, B={proc_dol:.0f}%", ft.Colors.GREY_400)

        prompt_dok = (
            "Jesteś precyzyjnym systemem OCR do dokumentów biurowych, faktur i specyfikacji.\n"
            "Przepisz CAŁY tekst widoczny na obrazie z zachowaniem układu:\n"
            "1. Jeżeli na obrazie występuje tabela, zestawienie kolumnowe lub lista z cenami/ilościami, "
            "zapisz ją BEZWZGLĘDNIE jako standardową tabelę Markdown (używając pionowych kresek '|' oraz nagłówków '|---|').\n"
            "2. Zachowaj oryginalne akapity, tytuły i odstępy.\n"
            "3. Nie dodawaj żadnych własnych komentarzy, wstępów ani znaczników ```markdown. Zwróć sam czysty tekst z tabelami."
        )

        try:
            cfg = config.wczytaj_konfiguracje()
            uzywa_chmury = cfg.get("use_cloud", True)
            wymiar = cfg.get("image_resolution", 1800)

            if not uzywa_chmury:
                ip_lokalne = cfg.get("local_ip", "192.168.1.154").strip()
                port_str = cfg.get("local_port", "1234").strip()
                mac_adres = cfg.get("wol_mac", "").strip()
                port_lokalny = int(port_str) if port_str.isdigit() else 1234

                self.ui.dopisz_log(f"Sprawdzanie stanu serwera LM Studio ({ip_lokalne}:{port_lokalny})...")
                serwer_zyje = await core.sprawdz_port_tcp(ip_lokalne, port_lokalny, timeout=3.0)
                if not serwer_zyje:
                    self.ui.dopisz_log("Serwer lokalny nie odpowiada. Wysyłanie WoL...", ft.Colors.AMBER)
                    try:
                        await loop.run_in_executor(None, core.wyslij_wol, mac_adres, ip_lokalne)
                    except Exception:
                        pass
                    await asyncio.sleep(15)

            # Wymiary faktyczne klatki
            try:
                with Image.open(sciezka_do_analizy) as img:
                    w_px, h_px = img.size
            except Exception:
                w_px, h_px = "?", "?"

            base64_image = await loop.run_in_executor(None, core.kompresuj_do_base64, sciezka_do_analizy, wymiar)
            waga_b64_kb = round(len(base64_image) * 0.75 / 1024, 1)
            self.ui.dopisz_log(f"📷 Kadr wejściowy: {w_px}x{h_px}px | Waga: {waga_b64_kb} KB (oryginał: {waga_oryg_kb} KB)", ft.Colors.GREY_400)

            if uzywa_chmury:
                model_nazwa = cfg.get("gemini_model", "gemini-2.5-flash")
                url = "[https://generativelanguage.googleapis.com/v1beta/openai/chat/completions](https://generativelanguage.googleapis.com/v1beta/openai/chat/completions)"
                headers = {"Authorization": f"Bearer {cfg.get('gemini_api_key', '')}", "Content-Type": "application/json"}
                payload = {
                    "model": model_nazwa,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_dok}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                    "temperature": 0.0,
                    "max_tokens": 8192
                }
                cel_logu = f"Google Cloud ({model_nazwa})"
            else:
                model_nazwa = cfg.get("local_model", "qwen3.5-9b")
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

            self.status_dok.value = "Odczytywanie dokumentu przez AI..."
            self.ui.dopisz_log(f"🌐 Wysyłanie żądania do: {cel_logu}...")
            self.page.update()

            start_siec = time.perf_counter()
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=300.0)) as client:
                res = await client.post(url, headers=headers, json=payload)
                res.raise_for_status()
                dane_odp = res.json()

            czas_siec = time.perf_counter() - start_siec
            wybor = dane_odp["choices"][0]
            surowy_tekst = wybor["message"]["content"].strip()
            powod_konca = wybor.get("finish_reason")

            # Telemetria tokenów i wydajności
            uzycie = dane_odp.get("usage") or {}
            in_tok = uzycie.get("prompt_tokens", 0)
            out_tok = uzycie.get("completion_tokens", 0)
            think_tok = (uzycie.get("completion_tokens_details") or {}).get("reasoning_tokens")

            predkosc = (out_tok / czas_siec) if (czas_siec > 0 and out_tok > 0) else 0.0

            log_wydajnosc = f"⏱️ Czas AI: {czas_siec:.2f}s | Tokeny: {in_tok} wejście / {out_tok} wyjście"
            if think_tok:
                log_wydajnosc += f" (myślenie: {think_tok})"
            if predkosc > 0:
                log_wydajnosc += f" | Prędkość: {predkosc:.1f} tok/s"
            self.ui.dopisz_log(log_wydajnosc, ft.Colors.CYAN)

            if powod_konca == "length":
                self.ui.dopisz_log("⚠️ OSTRZEŻENIE: Odpowiedź ucięta po limicie tokenów!", ft.Colors.RED)

            # Analiza struktury rozpoznanego tekstu
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

    def klik_wroc_do_wynikow_dok(self, e):
        if self.ostatni_wynik_dok.get("tekst"):
            self.txt_edytor_dok.value = self.ostatni_wynik_dok["tekst"]
            self.ui.bezpiecznie_otworz_dialog(self.dlg_wynik_dok)

    def zamknij_dlg_wynik_dok(self):
        self.page.pop_dialog()
        self.btn_wroc_wynik_dok.visible = self.ostatni_wynik_dok.get("tekst") is not None
        self.status_dok.value = "Wyniki odczytu dostępne. Możesz je przywrócić przyciskiem poniżej."
        self.status_dok.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    # --- SCHOWEK I UDOSTĘPNIANIE PLIKÓW ---
    async def kopiuj_do_schowka_dok(self, e):
        try:
            await self.page.set_clipboard(self.txt_edytor_dok.value)
            self.ui.dopisz_log("Skopiowano tekst dokumentu do schowka.", ft.Colors.GREEN)
        except Exception:
            try:
                await ft.Clipboard().set(self.txt_edytor_dok.value)
                self.ui.dopisz_log("Skopiowano tekst dokumentu do schowka.", ft.Colors.GREEN)
            except Exception as err_clip:
                self.ui.dopisz_log(f"Błąd schowka: {err_clip}", ft.Colors.AMBER)

    async def _bezpiecznie_udostepnij_plik(self, sciezka_pliku: str, tytul: str):
        if not os.path.exists(sciezka_pliku):
            self.ui.pokaz_okno_bledu("Brak pliku", "Plik wyjściowy nie istnieje.")
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

    async def udostepnij_tekst_dok(self, e):
        if not self.txt_edytor_dok.value:
            return
        sciezka_txt = os.path.join(config.KATALOG_DANYCH, f"dok_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(sciezka_txt, "w", encoding="utf-8") as f:
            f.write(self.txt_edytor_dok.value)
        await self._bezpiecznie_udostepnij_plik(sciezka_txt, "Odczytany dokument TXT")

    async def udostepnij_docx_dok(self, e):
        tekst = (self.txt_edytor_dok.value or "").strip()
        if not tekst:
            return

        def generuj_docx():
            import docx
            from docx.shared import Pt, Inches

            doc = docx.Document()
            for sec in doc.sections:
                sec.top_margin = Inches(0.6)
                sec.bottom_margin = Inches(0.6)
                sec.left_margin = Inches(0.6)
                sec.right_margin = Inches(0.6)

            linie = tekst.splitlines()
            bufor_tabeli = []

            def zapisz_bufor_tabeli():
                if not bufor_tabeli:
                    return
                wiersze_danych = [w for w in bufor_tabeli if not re.match(r'^\s*\|?\s*[-:]+[-| :]*$', w)]
                if not wiersze_danych:
                    bufor_tabeli.clear()
                    return

                tabela_dane = []
                for wiersz in wiersze_danych:
                    komorki = [c.strip() for c in wiersz.strip().strip('|').split('|')]
                    tabela_dane.append(komorki)

                max_kolumn = max(len(r) for r in tabela_dane)
                tabela_word = doc.add_table(rows=len(tabela_dane), cols=max_kolumn)
                tabela_word.style = 'Table Grid'

                for r_idx, wiersz in enumerate(tabela_dane):
                    for c_idx, wartosc in enumerate(wiersz):
                        cell = tabela_word.cell(r_idx, c_idx)
                        p = cell.paragraphs[0]
                        p.paragraph_format.space_before = Pt(2)
                        p.paragraph_format.space_after = Pt(2)
                        run = p.add_run(wartosc)
                        run.font.name = 'Calibri'
                        run.font.size = Pt(9.5)
                        if r_idx == 0:
                            run.bold = True
                doc.add_paragraph()
                bufor_tabeli.clear()

            for linia in linie:
                l_strip = linia.strip()
                if l_strip.startswith('|') and l_strip.endswith('|'):
                    bufor_tabeli.append(l_strip)
                else:
                    zapisz_bufor_tabeli()
                    if l_strip:
                        p = doc.add_paragraph()
                        p.paragraph_format.space_before = Pt(1)
                        p.paragraph_format.space_after = Pt(2)
                        run = p.add_run(linia)
                        run.font.name = 'Calibri'
                        run.font.size = Pt(10.5)

            zapisz_bufor_tabeli()
            sciezka_docx = os.path.join(config.KATALOG_DANYCH, f"dok_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx")
            doc.save(sciezka_docx)
            return sciezka_docx

        try:
            sciezka_docx = await asyncio.get_running_loop().run_in_executor(None, generuj_docx)
            await self._bezpiecznie_udostepnij_plik(sciezka_docx, "Odczytany dokument Word (.docx)")
        except Exception as err:
            self.ui.pokaz_okno_bledu("Błąd eksportu Word", f"Upewnij się, że zainstalowano python-docx:\n{err}")

    async def udostepnij_xlsx_dok(self, e):
        tekst = (self.txt_edytor_dok.value or "").strip()
        if not tekst:
            return

        def generuj_xlsx():
            import openpyxl
            from openpyxl.styles import Font, Alignment, Border, Side
            from openpyxl.utils import get_column_letter

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Dokument OCR"
            ws.views.sheetView[0].showGridLines = True

            czcionka_zwykla = Font(name="Calibri", size=10)
            ramka_cienka = Border(
                left=Side(style='thin', color='D9D9D9'),
                right=Side(style='thin', color='D9D9D9'),
                top=Side(style='thin', color='D9D9D9'),
                bottom=Side(style='thin', color='D9D9D9')
            )

            aktualny_wiersz = 1
            linie = tekst.splitlines()

            for linia in linie:
                l_strip = linia.strip()
                if not l_strip:
                    aktualny_wiersz += 1
                    continue

                if re.match(r'^\s*\|?\s*[-:]+[-| :]*$', l_strip):
                    continue

                if l_strip.startswith('|') and l_strip.endswith('|'):
                    komorki = [c.strip() for c in l_strip.strip('|').split('|')]
                elif '\t' in linia:
                    komorki = [c.strip() for c in linia.split('\t')]
                else:
                    komorki = [linia]

                for c_idx, val in enumerate(komorki, start=1):
                    cell = ws.cell(row=aktualny_wiersz, column=c_idx)
                    liczba_str = val.replace(" ", "").replace(",", ".")
                    if re.match(r'^-?\d+(\.\d+)?$', liczba_str):
                        cell.value = float(liczba_str) if '.' in liczba_str else int(liczba_str)
                        cell.alignment = Alignment(horizontal="right")
                    else:
                        cell.value = val
                        cell.alignment = Alignment(horizontal="left")

                    cell.font = czcionka_zwykla
                    cell.border = ramka_cienka

                aktualny_wiersz += 1

            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    if cell.value is not None:
                        max_len = max(max_len, len(str(cell.value)))
                ws.column_dimensions[col_letter].width = max(max_len + 3, 11)

            sciezka_xlsx = os.path.join(config.KATALOG_DANYCH, f"dok_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
            wb.save(sciezka_xlsx)
            return sciezka_xlsx

        try:
            sciezka_xlsx = await asyncio.get_running_loop().run_in_executor(None, generuj_xlsx)
            await self._bezpiecznie_udostepnij_plik(sciezka_xlsx, "Odczytana tabela Excel (.xlsx)")
        except Exception as err:
            self.ui.pokaz_okno_bledu("Błąd eksportu Excel", f"Upewnij się, że zainstalowano openpyxl:\n{err}")

    async def wybierz_foto_dok(self, e):
        picker = self.pickery.get("foto") if hasattr(self, "pickery") else None
        if not picker and hasattr(self, "ui") and hasattr(self.ui, "pickery"):
            picker = self.ui.pickery.get("foto")

        if picker:
            pliki = await picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            if pliki and len(pliki) > 0 and pliki[0].path:
                self.ustaw_nowy_obraz_dok(pliki[0].path)
