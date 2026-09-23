import os
import json
import copy
import shutil
import asyncio
from datetime import datetime
import flet as ft
import flet_camera as fc

import config
import core


class UIManager:
    def __init__(self, page: ft.Page, serwis_udostepniania: ft.Share, pickery: dict):
        self.page = page
        self.serwis_udostepniania = serwis_udostepniania
        self.pickery = pickery

        # Callbacki i referencje do ViewsManager
        self.views_manager = None
        self.on_foto_captured = None

        # Historia dialogów
        self.poprzedni_dialog = {"dlg": None}

        # Status bazy
        self.lbl_status_bazy = ft.Text("", size=12)

        # Pozycja suwaka listy weryfikacji PZ
        self._pozycja_scrolla_pz = 0.0        

        # Aparat
        self.cel_aparatu = {"modul": "pz"}
        self.kamera_obiektyw = fc.Camera(expand=True)
        self.page.on_view_pop = lambda e: asyncio.create_task(self.zamknij_pelny_ekran_aparatu())

        # Inicjalizacja komponentów
        self._inicjalizuj_alert_dialog()
        self._inicjalizuj_konsole_logow()
        
        self._inicjalizuj_okno_mapowan()
        self._inicjalizuj_okno_ustawien()
        self._inicjalizuj_okno_weryfikacji()

    # --- ZARZĄDZANIE DIALOGAMI ---
    def zamknij_kazdy_dialog(self, e=None):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def bezpiecznie_otworz_dialog(self, dlg):
        if hasattr(self.page, "_dialogs") and dlg in self.page._dialogs.controls and dlg.open:
            return
        self.zamknij_kazdy_dialog()
        if hasattr(self.page, "_dialogs") and dlg in self.page._dialogs.controls:
            self.page._dialogs.controls.remove(dlg)
        self.page.show_dialog(dlg)

    # --- OKNO BŁĘDÓW / ALERT ---
    def _inicjalizuj_alert_dialog(self):
        self.tytul_bledu = ft.Text("Komunikat", weight=ft.FontWeight.BOLD)
        self.tresc_bledu = ft.Text("", size=14)

        def zamknij_alert_i_wroc(e):
            self.zamknij_kazdy_dialog()
            odtworz = self.poprzedni_dialog["dlg"]
            self.poprzedni_dialog["dlg"] = None
            if odtworz:
                self.bezpiecznie_otworz_dialog(odtworz)

        self.dlg_alert = ft.AlertDialog(
            modal=True,
            title=self.tytul_bledu,
            content=self.tresc_bledu,
            actions=[ft.Button(content=ft.Text("Rozumiem"), on_click=zamknij_alert_i_wroc)]
        )

    def pokaz_okno_bledu(self, tytul: str, wiadomosc: str, powrot_do=None):
        self.poprzedni_dialog["dlg"] = powrot_do
        self.tytul_bledu.value = str(tytul)
        self.tresc_bledu.value = str(wiadomosc)
        self.bezpiecznie_otworz_dialog(self.dlg_alert)

    # --- KONSOLA LOGÓW ---
    def _inicjalizuj_konsole_logow(self):
        self.konsola_logow = ft.ListView(expand=True, auto_scroll=True, height=300, spacing=5)

        async def kopiuj_logi(e):
            tekst = "\n".join([c.value for c in self.konsola_logow.controls])
            sciezka_logow = os.path.join(
                config.KATALOG_DANYCH,
                f"logi_ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )
            try:
                with open(sciezka_logow, "w", encoding="utf-8") as f:
                    f.write(tekst)
                if hasattr(self.serwis_udostepniania, "share_files"):
                    try:
                        await self.serwis_udostepniania.share_files(
                            [ft.ShareFile.from_path(sciezka_logow)],
                            text="Logi z aplikacji ocrLmm"
                        )
                    except Exception:
                        await self.serwis_udostepniania.share_files([sciezka_logow])
                else:
                    self.dopisz_log("Błąd: Moduł udostępniania plików niedostępny.", ft.Colors.RED)
            except Exception as err:
                self.dopisz_log(f"Błąd eksportu: {err}", ft.Colors.RED)

            self.page.update()
            self.page.pop_dialog()

        self.dlg_konsola = ft.AlertDialog(
            modal=True,
            title=ft.Text("Konsola systemowa (Logi)"),
            content=ft.Container(content=self.konsola_logow, width=400, height=350),
            actions=[
                ft.Button("Udostępnij / Kopiuj", on_click=kopiuj_logi),
                ft.Button("Zamknij", on_click=lambda e: self.page.pop_dialog())
            ]
        )

    def dopisz_log(self, wiadomosc: str, kolor=ft.Colors.WHITE):
        czas = datetime.now().strftime("%H:%M:%S")
        self.konsola_logow.controls.append(ft.Text(f"[{czas}] {wiadomosc}", size=12, color=kolor))
        if len(self.konsola_logow.controls) > 300:
            del self.konsola_logow.controls[:-300]
        self.page.update()

    def otworz_konsole(self, e=None):
        self.bezpiecznie_otworz_dialog(self.dlg_konsola)

    # --- OBSŁUGA APARATU 1:1 Z MAIN (PEŁNY EKRAN + DOTYKOWA MIGAWKA) ---
    def aparat_obslugiwany(self) -> bool:
        return bool(self.page.web) or self.page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)

    async def zamknij_pelny_ekran_aparatu(self, e=None):
        try:
            await self.kamera_obiektyw.dispose()
        except Exception:
            pass

        if len(self.page.views) > 1:
            self.page.views.pop()
            self.page.update()

    async def klik_migawka(self, e=None):
        try:
            dane_zdjecia = await self.kamera_obiektyw.take_picture()
            if not isinstance(dane_zdjecia, (bytes, bytearray)):
                raise ValueError(f"Aparat zwrócił nieoczekiwany typ: {type(dane_zdjecia).__name__}")

            nazwa_pliku = f"foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            sciezka_zapisu = os.path.join(config.KATALOG_DANYCH, nazwa_pliku)

            with open(sciezka_zapisu, "wb") as f:
                f.write(dane_zdjecia)

            await self.zamknij_pelny_ekran_aparatu()

            if self.on_foto_captured:
                self.on_foto_captured(sciezka_zapisu, self.cel_aparatu["modul"])

        except Exception as err:
            self.dopisz_log(f"Błąd migawki: {err}", ft.Colors.RED)
            self.pokaz_okno_bledu("Błąd aparatu", f"Nie udało się zrobić zdjęcia: {err}")

    async def otworz_aparat_dla(self, modul: str):
        self.cel_aparatu["modul"] = modul

        if not self.aparat_obslugiwany():
            self.dopisz_log("Aparat działa tylko na Android/iOS. Wybór z pliku...", ft.Colors.AMBER)
            picker_foto = self.pickery.get("foto")
            if picker_foto:
                pliki = await picker_foto.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
                if pliki and len(pliki) > 0 and pliki[0].path:
                    if self.on_foto_captured:
                        self.on_foto_captured(pliki[0].path, modul)
            return

        try:
            widok_aparatu = ft.View(
                route="/aparat",
                controls=[
                    ft.Stack([
                        ft.GestureDetector(
                            content=self.kamera_obiektyw,
                            on_tap=lambda ev: asyncio.create_task(self.klik_migawka(ev)),
                            expand=True
                        ),
                        ft.Container(
                            content=ft.Button(
                                "Anuluj",
                                style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE),
                                on_click=lambda ev: asyncio.create_task(self.zamknij_pelny_ekran_aparatu(ev))
                            ),
                            top=40,
                            right=20
                        ),
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Text(
                                        "Stuknij w dowolne miejsce, aby zrobić zdjęcie",
                                        color=ft.Colors.WHITE70,
                                        size=14,
                                        text_align=ft.TextAlign.CENTER
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.CENTER
                            ),
                            bottom=30,
                            left=0,
                            right=0
                        )
                    ], expand=True)
                ],
                padding=0,
                bgcolor=ft.Colors.BLACK
            )

            self.page.views.append(widok_aparatu)
            self.page.update()

            kamery = await asyncio.wait_for(self.kamera_obiektyw.get_available_cameras(), timeout=10)
            if not kamery:
                await self.zamknij_pelny_ekran_aparatu()
                self.pokaz_okno_bledu("Brak aparatu", "Nie wykryto żadnego sensora kamery w urządzeniu.")
                return

            wybrana = next(
                (c for c in kamery if c.lens_direction == fc.CameraLensDirection.BACK),
                kamery[0]
            )
            await asyncio.wait_for(
                self.kamera_obiektyw.initialize(wybrana, fc.ResolutionPreset.HIGH, enable_audio=False),
                timeout=30
            )
            self.dopisz_log("Kamera pełnoekranowa zainicjalizowana.", ft.Colors.GREEN)

        except Exception as err:
            await self.zamknij_pelny_ekran_aparatu()
            self.dopisz_log(f"Błąd aparatu: {err}", ft.Colors.RED)
            self.pokaz_okno_bledu("Błąd aparatu", f"Nie udało się uruchomić aparatu: {err}")

    # --- ZARZĄDZANIE REGULAMI MAPOWAŃ ---
    def _inicjalizuj_okno_mapowan(self):
        self.txt_nowy_wzorzec = ft.TextField(label="Nazwa z faktury (np. BANAN)", dense=True, expand=True)
        self.txt_nowy_kod = ft.TextField(label="Kod PC-Market", dense=True, width=130)
        self.lista_mapowan_view = ft.ListView(expand=True, spacing=6, height=220)

        def dodaj_nowe_mapowanie(e):
            wz = self.txt_nowy_wzorzec.value.strip().upper()
            kd = self.txt_nowy_kod.value.strip()
            if not wz or not kd:
                self.pokaz_okno_bledu("Błąd", "Podaj nazwę wzorca oraz kod PC-Market.", powrot_do=self.dlg_baza_edycja)
                return

            mapa = core.wczytaj_baze_mapowan()
            core.dodaj_regule(mapa, wz, kd)
            core.zapisz_baze_mapowan(mapa)

            self.txt_nowy_wzorzec.value = ""
            self.txt_nowy_kod.value = ""
            self.odswiez_widok_mapowan(self.txt_filtr_bazy.value)
            self.odswiez_status_bazy()
            self.dopisz_log(f"Dodano powiązanie: {wz} -> {kd}", ft.Colors.GREEN_ACCENT)

        self.txt_filtr_bazy = ft.TextField(
            label="🔍 Filtruj zapisane reguły...",
            dense=True,
            on_change=lambda e: self.odswiez_widok_mapowan(self.txt_filtr_bazy.value)
        )

        self.dlg_baza_edycja = ft.AlertDialog(
            modal=True,
            title=ft.Text("📦 Baza i Edycja Powiązań"),
            content=ft.Column(
                [
                    ft.Text("Dodaj wzorzec towaru (np. BANAN -> 4001):", size=12, color=ft.Colors.GREY_400),
                    ft.Row([self.txt_nowy_wzorzec, self.txt_nowy_kod]),
                    ft.Button(
                        content=ft.Row([ft.Icon(ft.Icons.ADD), ft.Text("Zapisz powiązanie")], alignment=ft.MainAxisAlignment.CENTER),
                        style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE),
                        on_click=dodaj_nowe_mapowanie
                    ),
                    ft.Divider(),
                    self.txt_filtr_bazy,
                    self.lista_mapowan_view
                ],
                tight=True,
                width=360,
                spacing=10
            ),
            actions=[ft.Button(content=ft.Text("Zamknij"), on_click=lambda e: self.page.pop_dialog())]
        )

    def odswiez_widok_mapowan(self, filtr: str = ""):
        self.lista_mapowan_view.controls.clear()
        filtr_upper = filtr.upper().strip()
        mapa = core.wczytaj_baze_mapowan()

        for wzorzec, kod in sorted(mapa.items()):
            if filtr_upper and filtr_upper not in wzorzec and filtr_upper not in kod:
                continue

            def stworz_callback_usun(wz=wzorzec):
                def usun_klik(e):
                    m = core.wczytaj_baze_mapowan()
                    if wz in m:
                        del m[wz]
                        core.zapisz_baze_mapowan(m)
                        self.odswiez_widok_mapowan(self.txt_filtr_bazy.value)
                        self.odswiez_status_bazy()
                return usun_klik

            self.lista_mapowan_view.controls.append(
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
        self.page.update()

    def otworz_okno_bazy_recznej(self, e=None):
        self.odswiez_widok_mapowan()
        self.bezpiecznie_otworz_dialog(self.dlg_baza_edycja)

    def odswiez_status_bazy(self):
        konfig = config.wczytaj_konfiguracje()
        sciezka = config.pobierz_aktualna_sciezke_bazy(konfig)
        baza = core.wczytaj_baze_pcmarket(sciezka)
        mapa = core.wczytaj_baze_mapowan()
        nazwa = os.path.basename(sciezka)
        if baza:
            self.lbl_status_bazy.value = f"Katalog: {len(baza)} towarów ({nazwa}) | Własne reguły: {len(mapa)}"
            self.lbl_status_bazy.color = ft.Colors.GREEN_300
        else:
            self.lbl_status_bazy.value = f"⚠️ Brak towarów w pliku bazy ({nazwa}) | Własne reguły: {len(mapa)}"
            self.lbl_status_bazy.color = ft.Colors.ORANGE_300
        self.page.update()

    # --- OKNO USTAWIEŃ POŁĄCZENIA I KOPII ---
    def _inicjalizuj_okno_ustawien(self):
        konfig = config.wczytaj_konfiguracje()
        self.chk_cloud = ft.Checkbox(label="Użyj chmury (Google Gemini)", value=konfig.get("use_cloud", True))
        self.dd_rozdzielczosc = ft.Dropdown(
            label="Jakość skanu (Szybkość vs Tokeny)",
            options=[
                ft.dropdown.Option(key="2000", text="2000px (Podstawowa, najlepsza ostrość)"),
                ft.dropdown.Option(key="1800", text="1800px (Kompromis)"),
                ft.dropdown.Option(key="1400", text="1400px (Szybki, mały plik)")
            ],
            value=str(konfig.get("image_resolution", 1800)),
            dense=True
        )
        self.chk_db_matching = ft.Checkbox(label="Dopasowuj do bazy PC-Market", value=konfig.get("use_db_matching", True))
        self.txt_gemini_key = ft.TextField(label="Klucz Google AI Studio API", value=konfig.get("gemini_api_key", ""), password=True, can_reveal_password=True, dense=True)
        self.txt_gemini_model = ft.TextField(label="Model Google AI (np. gemini-2.5-flash)", value=konfig.get("gemini_model", "gemini-2.5-flash"), dense=True)

        self.txt_mac = ft.TextField(label="Adres MAC (Wake-on-LAN)", value=konfig.get("wol_mac", ""), dense=True)
        self.txt_ip = ft.TextField(label="IP Serwera LM Studio", value=konfig.get("local_ip", "192.168.1.154"), dense=True)
        self.txt_port = ft.TextField(label="Port LM Studio", value=konfig.get("local_port", "1234"), dense=True)

        lista_modeli = konfig.get("local_models_list", ["qwen/qwen3-vl-8b-instruct", "qwen3-vl-4b-instruct", "qwen3.5-9b"])
        akt_model = konfig.get("local_model", "qwen3.5-9b")
        if akt_model and akt_model not in lista_modeli:
            lista_modeli.append(akt_model)

        self.dd_local_model = ft.Dropdown(
            label="Wybierz model LM Studio",
            options=[ft.dropdown.Option(m) for m in lista_modeli],
            value=akt_model if lista_modeli else None,
            dense=True,
            expand=True
        )
        self.txt_dodaj_model = ft.TextField(label="Nazwa nowego modelu...", dense=True, expand=True)

        def klik_dodaj_model(e):
            m = self.txt_dodaj_model.value.strip()
            if m:
                istniejace = [opt.key for opt in self.dd_local_model.options]
                if m not in istniejace:
                    self.dd_local_model.options.append(ft.dropdown.Option(m))
                self.dd_local_model.value = m
                self.txt_dodaj_model.value = ""
                self.page.update()

        def klik_usun_model(e):
            m = self.dd_local_model.value
            if m:
                self.dd_local_model.options = [opt for opt in self.dd_local_model.options if opt.key != m]
                self.dd_local_model.value = self.dd_local_model.options[0].key if self.dd_local_model.options else None
                self.page.update()

        wiersz_wyboru_modelu = ft.Row([self.dd_local_model, ft.IconButton(icon=ft.Icons.DELETE, icon_color=ft.Colors.RED_400, tooltip="Usuń wybrany model", on_click=klik_usun_model)])
        wiersz_dodawania_modelu = ft.Row([self.txt_dodaj_model, ft.IconButton(icon=ft.Icons.ADD_CIRCLE, icon_color=ft.Colors.GREEN_400, tooltip="Dodaj do listy", on_click=klik_dodaj_model)])
        self.txt_local_api_key = ft.TextField(label="Klucz API serwera lokalnego (opcjonalnie)", value=konfig.get("local_api_key", ""), password=True, can_reveal_password=True, dense=True)

        async def klik_budzenie_wol(e):
            try:
                target_ip = self.txt_ip.value.strip() or "192.168.1.154"
                target_mac = self.txt_mac.value.strip()
                await asyncio.get_running_loop().run_in_executor(None, core.wyslij_wol, target_mac, target_ip)
                self.dopisz_log("Pakiet WoL wysłany pomyślnie.", ft.Colors.CYAN_ACCENT)
            except Exception as err_wol:
                self.dopisz_log(f"Błąd WoL: {err_wol}", ft.Colors.RED_ACCENT)

        btn_wol = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.POWER_SETTINGS_NEW), ft.Text("Obudź serwer lokalny (WoL)")]),
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_900, color=ft.Colors.BLUE_200),
            on_click=klik_budzenie_wol
        )

        async def wybierz_plik_bazy(e):
            try:
                pliki = await self.pickery["baza"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["txt"])
                if pliki and len(pliki) > 0 and pliki[0].path:
                    src = pliki[0].path
                    nazwa = os.path.basename(src)
                    if not core.wczytaj_baze_pcmarket(src):
                        self.pokaz_okno_bledu("Nieprawidłowy plik bazy", f"W pliku {nazwa} nie znaleziono żadnych towarów.", powrot_do=self.dlg_ustawienia)
                        return
                    dst = os.path.join(config.KATALOG_DANYCH, nazwa)
                    try:
                        shutil.copyfile(src, dst)
                    except Exception:
                        dst = src
                    konf = config.wczytaj_konfiguracje()
                    konf["baza_file_path"] = dst
                    config.zapisz_konfiguracje(konf)
                    self.odswiez_status_bazy()
                    self.dopisz_log(f"Wczytano bazę: {nazwa}", ft.Colors.CYAN_ACCENT)
            except Exception as err_b:
                self.pokaz_okno_bledu("Błąd wczytywania bazy", str(err_b), powrot_do=self.dlg_ustawienia)

        async def wybierz_plik_mapowan(e):
            try:
                pliki = await self.pickery["mapa"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["json"])
                if pliki and len(pliki) > 0 and pliki[0].path:
                    src = pliki[0].path
                    nowe = core.wczytaj_plik_mapowan_z_walidacja(src)
                    dotychczas = core.wczytaj_baze_mapowan()
                    if dotychczas and os.path.exists(config.MAPA_FILE):
                        shutil.copyfile(config.MAPA_FILE, config.MAPA_FILE + ".bak")
                    polaczone = {**dotychczas, **nowe}
                    core.zapisz_baze_mapowan(polaczone)
                    self.odswiez_widok_mapowan()
                    self.odswiez_status_bazy()
                    self.dopisz_log(f"Wczytano {len(nowe)} reguł.", ft.Colors.CYAN_ACCENT)
            except Exception as err_m:
                self.pokaz_okno_bledu("Błąd mapowań", str(err_m), powrot_do=self.dlg_ustawienia)

        async def udostepnij_bazy_kody(e):
            k = config.wczytaj_konfiguracje()
            sciezka_bazy = config.pobierz_aktualna_sciezke_bazy(k)
            pliki_sciezki, pliki_share = [], []
            if os.path.exists(sciezka_bazy):
                pliki_sciezki.append(sciezka_bazy)
                pliki_share.append(ft.ShareFile.from_path(sciezka_bazy))
            if os.path.exists(config.MAPA_FILE):
                pliki_sciezki.append(config.MAPA_FILE)
                pliki_share.append(ft.ShareFile.from_path(config.MAPA_FILE))
            if not pliki_sciezki:
                self.pokaz_okno_bledu("Brak plików", "Nie znaleziono pliku bazy TXT ani mapowań JSON.", powrot_do=self.dlg_ustawienia)
                return
            try:
                if hasattr(self.serwis_udostepniania, "share_files"):
                    try:
                        await self.serwis_udostepniania.share_files(pliki_share, text="Baza towarowa i mapowania")
                    except Exception:
                        await self.serwis_udostepniania.share_files(pliki_sciezki)
            except Exception as err_s:
                self.pokaz_okno_bledu("Błąd udostępniania", str(err_s), powrot_do=self.dlg_ustawienia)

        kontener_baza = ft.Column([
            ft.Text("Baza towarowa PC-Market:", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
            self.chk_db_matching,
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN), ft.Text("Wybierz plik bazy (.txt)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.AMBER_900, color=ft.Colors.WHITE), on_click=wybierz_plik_bazy),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE), ft.Text("Wgraj plik mapowań (.json)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.DEEP_ORANGE_900, color=ft.Colors.WHITE), on_click=wybierz_plik_mapowan),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.EDIT_NOTE), ft.Text("Zarządzaj powiązaniami")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE), on_click=self.otworz_okno_bazy_recznej),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.IOS_SHARE), ft.Text("Udostępnij kody (TXT + JSON)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.DEEP_PURPLE_800, color=ft.Colors.WHITE), on_click=udostepnij_bazy_kody),
            self.lbl_status_bazy
        ], spacing=6)

        kontener_gemini = ft.Column([
            ft.Text("Konfiguracja Google Gemini:", weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
            self.txt_gemini_key, self.txt_gemini_model
        ], spacing=8, visible=self.chk_cloud.value)

        kontener_lokalny = ft.Column([
            ft.Text("Konfiguracja serwera lokalnego:", weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_300),
            self.txt_mac, self.txt_ip, self.txt_port,
            ft.Text("Zarządzanie modelami LM Studio:", size=12, color=ft.Colors.GREY_400),
            wiersz_wyboru_modelu, wiersz_dodawania_modelu, self.txt_local_api_key, btn_wol
        ], spacing=8, visible=not self.chk_cloud.value)

        def przelacz_profil(e):
            kontener_gemini.visible = self.chk_cloud.value
            kontener_lokalny.visible = not self.chk_cloud.value
            self.page.update()

        self.chk_cloud.on_change = przelacz_profil

        async def eksportuj_backup(e):
            try:
                k = config.wczytaj_konfiguracje()
                k["use_cloud"] = self.chk_cloud.value
                k["use_db_matching"] = self.chk_db_matching.value
                k["gemini_api_key"] = self.txt_gemini_key.value.strip()
                k["gemini_model"] = self.txt_gemini_model.value.strip() or "gemini-2.5-flash"
                k["wol_mac"] = self.txt_mac.value.strip()
                k["local_ip"] = self.txt_ip.value.strip()
                k["local_port"] = self.txt_port.value.strip()
                k["local_model"] = self.dd_local_model.value or ""
                k["local_models_list"] = [opt.key for opt in self.dd_local_model.options]
                k["local_api_key"] = self.txt_local_api_key.value.strip()
                k["image_resolution"] = int(self.dd_rozdzielczosc.value)

                mapa = core.wczytaj_baze_mapowan()
                pakiet = {
                    "wersja": "1.0",
                    "data_utworzenia": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "konfiguracja": k,
                    "mapowania": mapa
                }
                nazwa = f"backup_ocrlmm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                sciezka = os.path.join(config.KATALOG_DANYCH, nazwa)
                with open(sciezka, "w", encoding="utf-8") as f:
                    json.dump(pakiet, f, indent=4, ensure_ascii=False)

                if hasattr(self.serwis_udostepniania, "share_files"):
                    try:
                        await self.serwis_udostepniania.share_files([ft.ShareFile.from_path(sciezka)], text="Kopia zapasowa ocrLmm")
                    except Exception:
                        await self.serwis_udostepniania.share_files([sciezka])
                self.dopisz_log(f"Wyeksportowano kopię: {nazwa}", ft.Colors.GREEN_ACCENT)
            except Exception as err_exp:
                self.pokaz_okno_bledu("Błąd eksportu", str(err_exp), powrot_do=self.dlg_ustawienia)

        async def importuj_backup(e):
            try:
                pliki = await self.pickery["backup"].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["json"])
                if not pliki or len(pliki) == 0 or not pliki[0].path:
                    return
                with open(pliki[0].path, "r", encoding="utf-8-sig") as f:
                    dane_b = json.load(f)
                nowa_k = dane_b.get("konfiguracja", dane_b)
                nowe_m = dane_b.get("mapowania", {})

                konf = config.wczytaj_konfiguracje()
                konf.update(nowa_k)
                config.zapisz_konfiguracje(konf)

                self.chk_cloud.value = konf.get("use_cloud", True)
                self.chk_db_matching.value = konf.get("use_db_matching", True)
                self.dd_rozdzielczosc.value = str(konf.get("image_resolution", 1800))
                self.txt_gemini_key.value = konf.get("gemini_api_key", "")
                self.txt_gemini_model.value = konf.get("gemini_model", "gemini-2.5-flash")
                self.txt_mac.value = konf.get("wol_mac", "")
                self.txt_ip.value = konf.get("local_ip", "192.168.1.154")
                self.txt_port.value = konf.get("local_port", "1234")
                self.txt_local_api_key.value = konf.get("local_api_key", "")

                modele = konf.get("local_models_list", [])
                self.dd_local_model.options = [ft.dropdown.Option(m) for m in modele]
                self.dd_local_model.value = konf.get("local_model", "")
                przelacz_profil(None)

                if isinstance(nowe_m, dict) and nowe_m:
                    poprz = core.wczytaj_baze_mapowan()
                    poprz.update(nowe_m)
                    core.zapisz_baze_mapowan(poprz)
                    self.odswiez_widok_mapowan()

                self.odswiez_status_bazy()
                self.pokaz_okno_bledu("Kopia przywrócona", "Pomyślnie zaimportowano konfigurację i przypisania towarów.", powrot_do=self.dlg_ustawienia)
            except Exception as err_imp:
                self.pokaz_okno_bledu("Błąd importu", str(err_imp), powrot_do=self.dlg_ustawienia)

        kontener_backup = ft.Column([
            ft.Text("Kopia zapasowa (Ustawienia + Reguły):", weight=ft.FontWeight.BOLD, color=ft.Colors.TEAL_300),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.UPLOAD), ft.Text("Eksportuj kopię (wszystko w jednym)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.TEAL_800, color=ft.Colors.WHITE), on_click=eksportuj_backup),
            ft.Button(content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD), ft.Text("Importuj kopię z pliku (.json)")], alignment=ft.MainAxisAlignment.CENTER), style=ft.ButtonStyle(bgcolor=ft.Colors.INDIGO_800, color=ft.Colors.WHITE), on_click=importuj_backup)
        ], spacing=6)

        def zapisz_i_zamknij(e):
            konf = config.wczytaj_konfiguracje()
            konf["use_cloud"] = self.chk_cloud.value
            konf["use_db_matching"] = self.chk_db_matching.value
            konf["gemini_api_key"] = self.txt_gemini_key.value.strip()
            konf["gemini_model"] = self.txt_gemini_model.value.strip() or "gemini-2.5-flash"
            konf["wol_mac"] = self.txt_mac.value.strip()
            konf["local_ip"] = self.txt_ip.value.strip()
            konf["local_port"] = self.txt_port.value.strip()
            konf["local_model"] = self.dd_local_model.value or ""
            konf["local_models_list"] = [opt.key for opt in self.dd_local_model.options]
            konf["local_api_key"] = self.txt_local_api_key.value.strip()
            konf["image_resolution"] = int(self.dd_rozdzielczosc.value)

            config.zapisz_konfiguracje(konf)
            self.page.pop_dialog()
            self.dopisz_log("Zapisano konfigurację aplikacji.", ft.Colors.CYAN_ACCENT)

        self.dlg_ustawienia = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚙️ Ustawienia połączenia"),
            content=ft.Column([
                self.chk_cloud, self.dd_rozdzielczosc, ft.Divider(),
                kontener_gemini, kontener_lokalny, ft.Divider(),
                kontener_baza, ft.Divider(),
                kontener_backup
            ], tight=True, scroll=ft.ScrollMode.AUTO, spacing=10),
            actions=[
                ft.Button(content=ft.Text("Anuluj"), on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Zapisz"), style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE), on_click=zapisz_i_zamknij)
            ]
        )

    def otworz_ustawienia(self, e=None):
        self.bezpiecznie_otworz_dialog(self.dlg_ustawienia)

    # --- OKNO WERYFIKACJI I UNIWERSALNA EDYCJA POZYCJI ---
    def _inicjalizuj_okno_weryfikacji(self):
        self.lbl_podsumowanie_weryfikacji = ft.Text("", size=12, weight=ft.FontWeight.BOLD)
        # Rejestracja bieżącej pozycji suwaka
        def zapisz_ruch_scrolla(e: ft.OnScrollEvent):
            if e.pixels is not None:
                self._pozycja_scrolla_pz = e.pixels

        self.lista_pozycji_weryfikacji = ft.ListView(
            expand=True,
            spacing=8,
            height=350,
            on_scroll=zapisz_ruch_scrolla
        )

        # Kontrolki w uniwersalnym oknie edycji pozycji
        self.lbl_edycja_nazwa = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self.txt_edycja_kod = ft.TextField(label="Kod PC-Market / EAN", dense=True, expand=True)

        btn_szukaj_w_bazie = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.SEARCH, size=18), ft.Text("Szukaj w bazie")], spacing=4),
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900, color=ft.Colors.WHITE, padding=10),
            on_click=lambda e: self.otworz_wyszukiwarke(self.views_manager.stan_weryfikacji.get("indeks_edytowany", -1))
        )
        wiersz_kodu = ft.Row([self.txt_edycja_kod, btn_szukaj_w_bazie], spacing=8)

        # Kafelki Jednostki Miary (JM)
        self.txt_edycja_jm = ft.TextField(label="JM", dense=True, width=70)

        def ustaw_jm(wartosc: str):
            self.txt_edycja_jm.value = wartosc
            kolor_aktywny = ft.Colors.GREEN_800
            kolor_nieaktywny = ft.Colors.GREY_800
            self.btn_jm_kg.style.bgcolor = kolor_aktywny if wartosc == "kg" else kolor_nieaktywny
            self.btn_jm_szt.style.bgcolor = kolor_aktywny if wartosc == "szt" else kolor_nieaktywny
            self.btn_jm_op.style.bgcolor = kolor_aktywny if wartosc == "op" else kolor_nieaktywny
            self.page.update()

        self.btn_jm_kg = ft.Button("kg", style=ft.ButtonStyle(padding=12, bgcolor=ft.Colors.GREY_800), on_click=lambda e: ustaw_jm("kg"))
        self.btn_jm_szt = ft.Button("szt", style=ft.ButtonStyle(padding=12, bgcolor=ft.Colors.GREY_800), on_click=lambda e: ustaw_jm("szt"))
        self.btn_jm_op = ft.Button("op", style=ft.ButtonStyle(padding=12, bgcolor=ft.Colors.GREY_800), on_click=lambda e: ustaw_jm("op"))
        self.ustaw_jm_fn = ustaw_jm

        wiersz_jm = ft.Row([
            ft.Text("JM:", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400),
            self.btn_jm_kg, self.btn_jm_szt, self.btn_jm_op, self.txt_edycja_jm
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # Pola wartości liczbowych
        self.txt_edycja_ilosc = ft.TextField(label="Ilość", dense=True, expand=True)
        self.txt_edycja_cena = ft.TextField(label="Cena netto", dense=True, expand=True)
        self.txt_edycja_wartosc = ft.TextField(label="Wartość netto (edytowalna)", dense=True)

        def przelicz_w_locie(e):
            il = core.parsuj_liczbe(self.txt_edycja_ilosc.value)
            cn = core.parsuj_liczbe(self.txt_edycja_cena.value)
            if il is not None and cn is not None:
                self.txt_edycja_wartosc.value = f"{il * cn:.2f}"
                self.page.update()

        self.txt_edycja_ilosc.on_change = przelicz_w_locie
        self.txt_edycja_cena.on_change = przelicz_w_locie

        # Zapis i aktualizacja mapowania
        def zapisz_pelna_edycje(e):
            if not self.views_manager:
                return
            idx = self.views_manager.stan_weryfikacji.get("indeks_edytowany", -1)
            dane = self.views_manager.stan_weryfikacji.get("dane")
            if idx >= 0 and dane and idx < len(dane.get("pozycje", [])):
                poz = dane["pozycje"][idx]
                surowa_jm = str(self.txt_edycja_jm.value or "kg").strip().lower().rstrip(".")
                poz["jm"] = surowa_jm if surowa_jm else "kg"
                poz["ilosc"] = self.txt_edycja_ilosc.value.strip()
                poz["cena_netto"] = self.txt_edycja_cena.value.strip()
                poz["wartosc_netto"] = self.txt_edycja_wartosc.value.strip()

                nowy_kod = self.txt_edycja_kod.value.strip()
                poz["kod_dopasowany"] = nowy_kod
                poz["pewnosc"] = "REGULA" if nowy_kod else "BRAK"

                # Zapis do pliku mapowań, jeśli kod został wpisany/zmieniony
                oryg_nazwa = poz.get("oryg_nazwa", "").upper().strip()
                if oryg_nazwa and nowy_kod:
                    mapa = core.wczytaj_baze_mapowan()
                    core.dodaj_regule(mapa, oryg_nazwa, nowy_kod)
                    core.zapisz_baze_mapowan(mapa)
                    self.odswiez_status_bazy()

                poz["ostrzezenia"] = core.ostrzezenia_pozycji(poz)
                status_sum, info_sum = core.weryfikuj_sumy_netto(dane)
                self.views_manager.stan_weryfikacji["status_sum"] = status_sum
                self.views_manager.stan_weryfikacji["info_sumy"] = info_sum

            self.odswiez_weryfikacje()
            self.bezpiecznie_otworz_dialog(self.dlg_weryfikacja)

        # Wyczyść kod / powiązanie (pod F5 w PC-Market)
        def wyczysc_kod_pozycji(e):
            self.txt_edycja_kod.value = ""
            if not self.views_manager:
                return
            idx = self.views_manager.stan_weryfikacji.get("indeks_edytowany", -1)
            dane = self.views_manager.stan_weryfikacji.get("dane")
            if idx >= 0 and dane and idx < len(dane.get("pozycje", [])):
                poz = dane["pozycje"][idx]
                oryg_nazwa = poz.get("oryg_nazwa", "").upper().strip()
                if oryg_nazwa:
                    mapa = core.wczytaj_baze_mapowan()
                    if core.usun_regule(mapa, oryg_nazwa):
                        core.zapisz_baze_mapowan(mapa)
                        self.odswiez_status_bazy()
            zapisz_pelna_edycje(None)

        # Usunięcie pozycji z PZ
        def usun_pozycje_z_pz(e):
            if not self.views_manager:
                return
            idx = self.views_manager.stan_weryfikacji.get("indeks_edytowany", -1)
            dane = self.views_manager.stan_weryfikacji.get("dane")
            if idx >= 0 and dane and idx < len(dane.get("pozycje", [])):
                del dane["pozycje"][idx]
                # Ustawienie scrolla na pozycję wyżej
                nowy_idx = max(0, idx - 1) if dane["pozycje"] else -1
                self.views_manager.stan_weryfikacji["indeks_edytowany"] = nowy_idx

                status_sum, info_sum = core.weryfikuj_sumy_netto(dane)
                self.views_manager.stan_weryfikacji["status_sum"] = status_sum
                self.views_manager.stan_weryfikacji["info_sumy"] = info_sum

            self.odswiez_weryfikacje()
            self.bezpiecznie_otworz_dialog(self.dlg_weryfikacja)

        self.dlg_edycja_pozycji = ft.AlertDialog(
            modal=True,
            title=ft.Text("✏️ Edycja pozycji PZ"),
            content=ft.Column(
                [
                    self.lbl_edycja_nazwa,
                    ft.Divider(height=1, color=ft.Colors.GREY_800),
                    wiersz_kodu,
                    wiersz_jm,
                    ft.Row([self.txt_edycja_ilosc, self.txt_edycja_cena]),
                    self.txt_edycja_wartosc,
                    ft.Row([
                        ft.Button(
                            content=ft.Row([ft.Icon(ft.Icons.LINK_OFF, size=16), ft.Text("Wyczyść kod (F5)", size=12)]),
                            style=ft.ButtonStyle(bgcolor=ft.Colors.ORANGE_900, color=ft.Colors.WHITE, padding=8),
                            on_click=wyczysc_kod_pozycji
                        ),
                        ft.Button(
                            content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, size=16), ft.Text("Usuń z PZ", size=12)]),
                            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_900, color=ft.Colors.WHITE, padding=8),
                            on_click=usun_pozycje_z_pz
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ],
                tight=True,
                spacing=10,
                width=340
            ),
            actions=[
                ft.Button("Anuluj", on_click=lambda e: self.bezpiecznie_otworz_dialog(self.dlg_weryfikacja)),
                ft.Button("Zapisz", style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE), on_click=zapisz_pelna_edycje)
            ]
        )

        # Wyszukiwarka w locie
        self.lista_wyszukiwarki = ft.ListView(expand=True, spacing=5, height=350)
        self.pole_szukaj_towaru = ft.TextField(
            label="Wpisz nazwę lub kod z PC-Market...",
            dense=True,
            on_change=lambda e: self.filtruj_wyszukiwarke()
        )

        self.dlg_wyszukiwarka = ft.AlertDialog(
            modal=True,
            title=ft.Text("Baza PC-Market"),
            content=ft.Container(
                content=ft.Column([self.pole_szukaj_towaru, self.lista_wyszukiwarki], tight=True),
                width=380,
                height=450
            ),
            actions=[
                ft.Button("Wróć do edycji", on_click=lambda e: self.bezpiecznie_otworz_dialog(self.dlg_edycja_pozycji))
            ]
        )

        async def klik_zatwierdz_weryfikacje(e):
            self.zamknij_kazdy_dialog()
            if self.views_manager:
                await self.views_manager.zapisz_edi_i_zakoncz()

        def klik_anuluj_weryfikacje(e):
            self.zamknij_kazdy_dialog()
            if self.views_manager:
                self.views_manager.anuluj_weryfikacje()

        self.dlg_weryfikacja = ft.AlertDialog(
            modal=True,
            title=ft.Text("Weryfikacja pozycji PZ"),
            content=ft.Container(
                content=ft.Column([
                    self.lbl_podsumowanie_weryfikacji,
                    ft.Divider(height=1, color=ft.Colors.GREY_800),
                    self.lista_pozycji_weryfikacji
                ], tight=True),
                width=380,
                height=460
            ),
            actions=[
                ft.Button("Anuluj", color=ft.Colors.RED_400, on_click=klik_anuluj_weryfikacje),
                ft.Button("Zatwierdź i Generuj", style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE), on_click=klik_zatwierdz_weryfikacje)
            ]
        )

    def otworz_edycje_pozycji(self, idx: int):
        if not self.views_manager:
            return
        dane = self.views_manager.stan_weryfikacji.get("dane")
        if not dane or idx < 0 or idx >= len(dane.get("pozycje", [])):
            return

        self.views_manager.stan_weryfikacji["indeks_edytowany"] = idx
        poz = dane["pozycje"][idx]

        self.lbl_edycja_nazwa.value = poz.get("oryg_nazwa") or poz.get("nazwa") or "Pozycja bez nazwy"
        self.txt_edycja_kod.value = str(poz.get("kod_dopasowany") or poz.get("kod") or "")

        aktualna_jm = str(poz.get("jm") or "kg").strip().lower().rstrip(".")
        self.ustaw_jm_fn(aktualna_jm if aktualna_jm else "kg")

        self.txt_edycja_ilosc.value = str(poz.get("ilosc") or "")
        self.txt_edycja_cena.value = str(poz.get("cena_netto") or "")
        self.txt_edycja_wartosc.value = str(poz.get("wartosc_netto") or "")

        self.bezpiecznie_otworz_dialog(self.dlg_edycja_pozycji)

    def otworz_wyszukiwarke(self, idx: int):
        if not self.views_manager:
            return
        self.views_manager.stan_weryfikacji["indeks_edytowany"] = idx
        self.pole_szukaj_towaru.value = ""
        self.filtruj_wyszukiwarke()
        self.bezpiecznie_otworz_dialog(self.dlg_wyszukiwarka)

    def filtruj_wyszukiwarke(self):
        self.lista_wyszukiwarki.controls.clear()
        if not self.views_manager:
            return
        fraza = core.usun_diakrytyki(self.pole_szukaj_towaru.value.strip().upper())
        fragmenty = fraza.split()

        licznik = 0
        baza = self.views_manager.stan_weryfikacji.get("baza", [])
        for towar in baza:
            nazwa_towaru = towar["nazwa"]
            kod_towaru = towar["kod_wew"]

            czy_pasuje = True
            for frag in fragmenty:
                if frag not in core.usun_diakrytyki(nazwa_towaru) and frag not in kod_towaru:
                    czy_pasuje = False
                    break

            if czy_pasuje:
                self.lista_wyszukiwarki.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(nazwa_towaru, size=12, weight=ft.FontWeight.BOLD),
                                ft.Text(f"Kod: {kod_towaru}", size=11, color=ft.Colors.GREY_400)
                            ], expand=True),
                            ft.Button("Wybierz", style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_900), on_click=lambda e, k=kod_towaru: self.klik_wybierz_z_wyszukiwarki(k))
                        ]),
                        padding=4,
                        border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.GREY_800))
                    )
                )
                licznik += 1
                if licznik >= 40:
                    break
        self.page.update()

    def klik_wybierz_z_wyszukiwarki(self, kod: str):
        # Podstawienie kodu do okna edycji
        self.txt_edycja_kod.value = kod
        self.page.update()
        self.bezpiecznie_otworz_dialog(self.dlg_edycja_pozycji)

    def aktualizuj_pasek_podsumowania(self):
        if not self.views_manager or not self.views_manager.stan_weryfikacji.get("dane"):
            self.lbl_podsumowanie_weryfikacji.value = ""
            return

        dane = self.views_manager.stan_weryfikacji["dane"]
        pozycje = dane.get("pozycje") or []
        suma_obliczona = sum(core.parsuj_kwote(p.get("wartosc_netto")) for p in pozycje)
        suma_odczytana = core.parsuj_kwote(dane.get("suma_netto_dokument"))

        if suma_odczytana <= 0.0:
            stawki = dane.get("stawki") or []
            suma_odczytana = sum(core.parsuj_kwote(s.get("suma_netto")) for s in stawki)

        tekst = f"📦 Pozycji PZ: {len(pozycje)} | Suma: {suma_obliczona:.2f} zł"
        if suma_odczytana > 0:
            roznica = abs(suma_obliczona - suma_odczytana)
            if roznica <= 0.15:
                tekst += f" (Zgodna z fakturą: {suma_odczytana:.2f} zł)"
                self.lbl_podsumowanie_weryfikacji.color = ft.Colors.GREEN_400
            else:
                tekst += f"\n⚠️ Faktura: {suma_odczytana:.2f} zł | Różnica: {roznica:.2f} zł"
                self.lbl_podsumowanie_weryfikacji.color = ft.Colors.AMBER_400
        else:
            self.lbl_podsumowanie_weryfikacji.color = ft.Colors.CYAN_300

        self.lbl_podsumowanie_weryfikacji.value = tekst

    def odswiez_weryfikacje(self):
        self.lista_pozycji_weryfikacji.controls.clear()
        if not self.views_manager or not self.views_manager.stan_weryfikacji.get("dane"):
            return

        self.aktualizuj_pasek_podsumowania()
        baza = self.views_manager.stan_weryfikacji.get("baza", [])
        mapa_kod_nazwa = {t["kod_wew"]: t["nazwa"] for t in baza}

        dane = self.views_manager.stan_weryfikacji["dane"]
        for i, poz in enumerate(dane.get("pozycje", [])):
            nazwa = poz.get("oryg_nazwa", "")
            kod = poz.get("kod_dopasowany", "")
            pewnosc = poz.get("pewnosc", "BRAK")

            # Status kodowania
            if kod:
                if pewnosc == "ORYGINAL":
                    tekst_kodu = ft.Text(f"Kod z faktury: {kod}", size=12, color=ft.Colors.CYAN_400)
                elif pewnosc == "WAGA_KOD":
                    tekst_kodu = ft.Text(f"Kod wagowy: {kod}", size=12, color=ft.Colors.GREEN_400)
                elif pewnosc == "EAN":
                    tekst_kodu = ft.Text(f"EAN: {kod}", size=12, color=ft.Colors.BLUE_400)
                else:
                    nazwa_dopasowana = mapa_kod_nazwa.get(kod, "Pozycja zdefiniowana ręcznie")
                    if pewnosc == "ROZMYTE":
                        tekst_kodu = ft.Text(f"Towar: {nazwa_dopasowana} (Kod: {kod}) [⚠️ Sprawdź]", size=12, color=ft.Colors.AMBER_300)
                    else:
                        tekst_kodu = ft.Text(f"Towar: {nazwa_dopasowana} (Kod: {kod})", size=12, color=ft.Colors.GREEN_400)
            else:
                tekst_kodu = ft.Text("BRAK KODU (Dotknij, aby wybrać lub zostawić F5)", size=12, color=ft.Colors.ORANGE_400, weight=ft.FontWeight.BOLD)

            ilosc_str = poz.get("ilosc") or "0"
            jm_str = poz.get("jm") or "kg"
            cena_str = poz.get("cena_netto") or "0.00"
            wart_str = poz.get("wartosc_netto") or "0.00"
            tekst_wartosci = ft.Text(f"{ilosc_str} {jm_str} × {cena_str} zł = {wart_str} zł netto", size=12, color=ft.Colors.GREY_300)

            kolumna_tekstow = [
                ft.Text(nazwa, weight=ft.FontWeight.BOLD, size=13),
                tekst_kodu,
                tekst_wartosci
            ]
            for ostrzezenie in poz.get("ostrzezenia", []):
                kolumna_tekstow.append(ft.Text(f"⚠️ {ostrzezenie}", size=11, color=ft.Colors.AMBER_300))

            # CAŁY WIERSZ JEST JEDNYM DUŻYM, KLIKALNYM KAFELKIEM
            self.lista_pozycji_weryfikacji.controls.append(
                ft.Container(
                    key=f"poz_{i}",
                    content=ft.Row([
                        ft.Column(kolumna_tekstow, expand=True, spacing=2),
                        ft.Icon(ft.Icons.CHEVRON_RIGHT, color=ft.Colors.GREY_500, size=24)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=10,
                    bgcolor=ft.Colors.GREY_900,
                    border_radius=8,
                    ink=True,
                    on_click=lambda e, idx=i: self.otworz_edycje_pozycji(idx)
                )
            )

        self.page.update()

        # Natychmiastowe przywrócenie dokładnej pozycji w pikselach
        if self._pozycja_scrolla_pz > 0:
            async def przywroc_scroll():
                await asyncio.sleep(0.05)
                try:
                    await self.lista_pozycji_weryfikacji.scroll_to(offset=self._pozycja_scrolla_pz, duration=0)
                except Exception:
                    pass
            asyncio.create_task(przywroc_scroll())
