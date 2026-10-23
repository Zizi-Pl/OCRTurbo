import os
import shutil
import asyncio
from datetime import datetime
import flet as ft

import config
import image_processor
from image_viewer import PełnyEdytorObrazu


class ModulScanMixin:
    def _inicjalizuj_modul_skan(self):
        self.zdjecie_skan = {"sciezka": None, "strony": None, "pdf": None}

    def _inicjalizuj_modul_skaner(self):
        self._inicjalizuj_modul_skan()

        self.podglad_skan = ft.Image(
            src=config.PUSTY_OBRAZ,
            fit=ft.BoxFit.CONTAIN,
            width=320,
            height=240
        )

        self.edytor_pelny_skan = PełnyEdytorObrazu(
            page=self.page,
            on_zatwierdz=lambda sciezka: asyncio.create_task(self._zatwierdz_edycje_skan(sciezka)),
            on_anuluj=self._zamknij_pelny_ekran_skan
        )

        self.status_skan = ft.Text(
            "Wybierz zdjęcie lub zrób nowe, aby przygotować czysty skan dokumentu.",
            size=13, color=ft.Colors.GREY_300, text_align=ft.TextAlign.CENTER
        )

        self.btn_foto_skan = ft.ElevatedButton(
            content=ft.Row([ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("ZDJĘCIA")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.otworz_galerie_skan())
        )
        self.btn_aparat_skan = ft.ElevatedButton(
            content=ft.Row([ft.Icon(ft.Icons.CAMERA_ALT), ft.Text("APARAT")], alignment=ft.MainAxisAlignment.CENTER),
            height=55, expand=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.ui.otworz_aparat_dla("skaner"))
        )
        self.wiersz_foto_skan = ft.Row([self.btn_foto_skan, self.btn_aparat_skan], spacing=10)

        self.kontener_podgladu_skan = ft.Container(
            content=ft.GestureDetector(
                content=self.podglad_skan,
                on_tap=lambda e: self.otworz_pelny_podglad_skan()
            ),
            alignment=ft.Alignment(0, 0),
            height=250,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            visible=False
        )

        self.btn_otworz_kadr_skan = ft.ElevatedButton(
            content=ft.Row([ft.Icon(ft.Icons.TUNE, size=20), ft.Text("Dopasuj kadr / Suwaki / Auto", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: self.otworz_pelny_podglad_skan()
        )

        self.btn_udostepnij_skan = ft.ElevatedButton(
            content=ft.Row([ft.Icon(ft.Icons.SHARE), ft.Text("Udostępnij gotowy skan (JPG)")], alignment=ft.MainAxisAlignment.CENTER),
            height=48, visible=False,
            style=ft.ButtonStyle(bgcolor=ft.Colors.PURPLE_800, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: asyncio.create_task(self.udostepnij_skan())
        )

        self.btn_usun_foto_skan = ft.ElevatedButton(
            content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, size=18), ft.Text("Usuń wybrane zdjęcie", size=12)], alignment=ft.MainAxisAlignment.CENTER),
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
            visible=False,
            on_click=lambda e: self.usun_wybrane_zdjecie_skan()
        )

        self.btn_konsola_skan = ft.IconButton(
            icon=ft.Icons.TERMINAL, tooltip="Konsola zdarzeń (logi)", on_click=self.ui.otworz_konsole
        )

        pasek_tytulu_skan = ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Menu Główne", on_click=lambda e: asyncio.create_task(self.przelacz_widok("menu"))),
                    ft.Column([
                        ft.Text("ocrLmm Mobile", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.DEEP_ORANGE_400),
                        ft.Text("Szybki Skaner Graficzny", size=11, color=ft.Colors.GREY_400)
                    ], spacing=1)
                ]),
                self.btn_konsola_skan
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.Padding(4, 38, 4, 0)
        )

        self.kolumna_glowna_skan = ft.Column([
            pasek_tytulu_skan,
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self.wiersz_foto_skan,
            self.status_skan,
            self.kontener_podgladu_skan,
            self.btn_otworz_kadr_skan,
            self.btn_udostepnij_skan,
            self.btn_usun_foto_skan
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=10)

        self.widok_skan = ft.Column([
            self.kolumna_glowna_skan,
            self.edytor_pelny_skan
        ], expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0, visible=False)

        self.edytor_pelny_skan.visible = False
        self.widok_skaner = self.widok_skan

    def ustaw_stan_foto_skan(self, czy_ma: bool):
        self.kontener_podgladu_skan.visible = czy_ma
        self.btn_otworz_kadr_skan.visible = czy_ma
        self.btn_udostepnij_skan.visible = czy_ma
        self.btn_usun_foto_skan.visible = czy_ma
        self.page.update()

    def _ustaw_napis_udostepniania_skan(self):
        strony = self.zdjecie_skan.get("strony") or []
        if self.zdjecie_skan.get("pdf"):
            napis = f"Udostępnij skan (PDF, {len(strony)} str.)"
        elif len(strony) > 1:
            napis = f"Udostępnij skan ({len(strony)} × JPG)"
        else:
            napis = "Udostępnij gotowy skan (JPG)"
        self.btn_udostepnij_skan.content.controls[1].value = napis

    def przyjmij_skany_skan(self, obrazy: list, pdf=None):
        """Strony ze skanera Google - gotowe do udostępnienia."""
        self.zdjecie_skan["sciezka"] = obrazy[0]
        self.zdjecie_skan["strony"] = list(obrazy)
        self.zdjecie_skan["pdf"] = pdf
        self.podglad_skan.src = None
        self.podglad_skan.src = obrazy[0]
        self._ustaw_napis_udostepniania_skan()
        self.ustaw_stan_foto_skan(True)
        ile = len(obrazy)
        self.status_skan.value = (
            f"✅ Zeskanowano {ile} str. Możesz od razu udostępnić skan."
            if ile > 1 else "✅ Skan gotowy. Możesz od razu udostępnić plik."
        )
        self.status_skan.color = ft.Colors.GREEN_ACCENT
        self.page.update()

    async def udostepnij_skan(self):
        """PDF ze wszystkimi stronami (jeśli jest aktualny), inaczej strony JPG."""
        pdf = self.zdjecie_skan.get("pdf")
        if pdf and os.path.exists(pdf):
            await self.udostepnij_plik_skan(pdf, tytul="Skan dokumentu (PDF)")
            return
        strony = [s for s in (self.zdjecie_skan.get("strony") or []) if os.path.exists(s)]
        if len(strony) > 1:
            await self.udostepnij_plik_skan(strony, tytul=f"Skan dokumentu ({len(strony)} str.)")
        else:
            await self.udostepnij_plik_skan(self.zdjecie_skan["sciezka"])

    def ustaw_nowy_obraz_skan(self, sciezka: str):
        nowa_sciezka = image_processor.przygotuj_obraz_wejsciowy(sciezka, prefiks="img_skan")
        self.zdjecie_skan["sciezka"] = nowa_sciezka
        self.zdjecie_skan["strony"] = None
        self.zdjecie_skan["pdf"] = None
        self._ustaw_napis_udostepniania_skan()
        self.podglad_skan.src = None
        self.podglad_skan.src = nowa_sciezka

        self.ustaw_stan_foto_skan(True)
        self.status_skan.value = "Zdjęcie gotowe. Kliknij w podgląd, aby dopasować kadr lub użyć suwaków."
        self.status_skan.color = ft.Colors.CYAN_ACCENT
        self.page.update()

    def otworz_pelny_podglad_skan(self):
        if not self.zdjecie_skan["sciezka"] or not os.path.exists(self.zdjecie_skan["sciezka"]):
            return

        # 1. NAJPIERW pokaż kontener edytora i zablokuj scroll
        self.kolumna_glowna_skan.visible = False
        self.edytor_pelny_skan.visible = True
        self.page.scroll = None
        self.page.update()

        # 2. DOPIERO TERAZ wczytaj obraz (gdy kontrolka Image fizycznie istnieje na ekranie)
        self.edytor_pelny_skan.wczytaj_obraz(self.zdjecie_skan["sciezka"])

    def _zamknij_pelny_ekran_skan(self):
        self.edytor_pelny_skan.visible = False
        self.kolumna_glowna_skan.visible = True
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.update()

    async def _zatwierdz_edycje_skan(self, sciezka_po_edycji: str):
        strony = self.zdjecie_skan.get("strony")
        if strony:
            strony[0] = sciezka_po_edycji  # edytor zmienia 1. stronę skanu
        # PDF ze skanera nie zawiera już poprawek - udostępniamy strony JPG
        self.zdjecie_skan["pdf"] = None
        self._ustaw_napis_udostepniania_skan()
        self.zdjecie_skan["sciezka"] = sciezka_po_edycji
        self.podglad_skan.src = None
        self.podglad_skan.src = sciezka_po_edycji

        self._zamknij_pelny_ekran_skan()
        self.status_skan.value = "✅ Zmiany zatwierdzone. Możesz udostępnić gotowy plik skanu."
        self.status_skan.color = ft.Colors.GREEN_ACCENT
        self.page.update()

    def usun_wybrane_zdjecie_skan(self):
        pliki = set(self.zdjecie_skan.get("strony") or [])
        for klucz in ("sciezka", "pdf"):
            if self.zdjecie_skan.get(klucz):
                pliki.add(self.zdjecie_skan[klucz])
        for sciezka_pliku in pliki:
            if os.path.exists(sciezka_pliku):
                try:
                    os.remove(sciezka_pliku)
                    self.ui.dopisz_log(f"Usunięto plik: {os.path.basename(sciezka_pliku)}")
                except Exception as err:
                    self.ui.dopisz_log(f"Błąd usuwania pliku: {err}", ft.Colors.AMBER)

        self.zdjecie_skan["sciezka"] = None
        self.zdjecie_skan["strony"] = None
        self.zdjecie_skan["pdf"] = None
        self.podglad_skan.src = None
        self.podglad_skan.src = config.PUSTY_OBRAZ
        self.ustaw_stan_foto_skan(False)
        self.status_skan.value = "Wybierz zdjęcie lub zrób nowe, aby przygotować czysty skan dokumentu."
        self.status_skan.color = ft.Colors.GREY_300
        self.page.update()

    async def otworz_galerie_skan(self):
        try:
            pliki = await self.pickery["foto"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            if pliki and len(pliki) > 0 and pliki[0].path:
                self.ustaw_nowy_obraz_skan(pliki[0].path)
        except Exception as e_pick:
            self.status_skan.value = f"Błąd wyboru pliku: {e_pick}"
            self.page.update()

    async def udostepnij_plik_skan(self, sciezki, tytul: str = "Skan dokumentu (JPG)"):
        pliki = [sciezki] if isinstance(sciezki, str) else list(sciezki or [])
        if not pliki or not all(os.path.exists(s) for s in pliki):
            self.ui.pokaz_okno_bledu("Brak pliku", "Wskazany plik nie istnieje na dysku.")
            return

        try:
            if hasattr(self.ui.serwis_udostepniania, "share_files"):
                try:
                    await self.ui.serwis_udostepniania.share_files(
                        [ft.ShareFile.from_path(s) for s in pliki],
                        text=tytul
                    )
                except Exception:
                    await self.ui.serwis_udostepniania.share_files(pliki)
            else:
                self.ui.dopisz_log("Błąd: Serwis udostępniania niedostępny.", ft.Colors.RED)
        except Exception as err_s:
            self.ui.dopisz_log(f"Błąd udostępniania skanu: {err_s}", ft.Colors.RED)
            self.ui.pokaz_okno_bledu("Błąd udostępniania", str(err_s))
