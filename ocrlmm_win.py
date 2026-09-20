import sys
import base64
import json
import os
import re
import threading
import ctypes
import time
import socket
from datetime import datetime

# Biblioteki przetwarzania dokumentów i dopasowania tekstu
import pymupdf
from thefuzz import fuzz, process

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QTextEdit, 
                             QFileDialog, QMessageBox, QDialog, QLineEdit, 
                             QRadioButton, QButtonGroup, QFormLayout, QFrame,
                             QSplashScreen, QTableWidget, QTableWidgetItem, QHeaderView,
                             QMenu, QCheckBox)
from PyQt6.QtCore import Qt, QBuffer, QIODevice, QRectF, QPointF, pyqtSignal, QObject
from PyQt6.QtGui import (QPixmap, QImage, QGuiApplication, QKeySequence, QIcon, 
                         QPainter, QColor, QFont, QPen, QBrush, QPolygonF)

from openai import OpenAI, APIStatusError

CONFIG_FILE = "config.json"
MAPA_FILE = "mapowania_towarow.json"
BAZA_TOWAROW_TXT = "NOWA_BAZA.txt"


# --- BAZA TOWAROWA I DOPASOWANIE ROZMYTE ---
def wczytaj_baze_mapowan():
    if os.path.exists(MAPA_FILE):
        try:
            with open(MAPA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def zapisz_baze_mapowan(mapa):
    with open(MAPA_FILE, "w", encoding="utf-8") as f:
        json.dump(mapa, f, indent=4, ensure_ascii=False)


def wczytaj_baze_pcmarket(sciezka_pliku=BAZA_TOWAROW_TXT):
    """Wczytuje zrzut towarów z PC-Market z poprawną obsługą polskich znaków Windows-1250."""
    baza = {}
    if not os.path.exists(sciezka_pliku):
        return baza

    kodowania = ["windows-1250", "utf-8", "cp852", "iso-8859-2"]
    linie = None

    for enc in kodowania:
        try:
            with open(sciezka_pliku, "r", encoding=enc) as f:
                linie = f.readlines()
            break
        except (UnicodeDecodeError, Exception):
            continue

    if not linie:
        return baza

    start_idx = 0
    if linie and ("Nazwa" in linie[0] or "Lista towarów" in linie[0]):
        for i, linia in enumerate(linie[:5]):
            if "Cena det." in linia or "Kod" in linia:
                start_idx = i + 1
                break

    for linia in linie[start_idx:]:
        czesci = linia.strip().split("\t")
        if len(czesci) >= 3:
            nazwa = czesci[0].strip().upper()
            kod = czesci[2].strip().replace("'", "").replace("?", "").strip()
            if nazwa and kod:
                baza[nazwa] = kod

    return baza


def znajdz_kod_fuzzy(nazwa_szukana, baza_towarowa, prog_podobienstwa=70):
    nazwa_czysta = nazwa_szukana.strip().upper()
    if not nazwa_czysta or not baza_towarowa:
        return ""
    
    if nazwa_czysta in baza_towarowa:
        return baza_towarowa[nazwa_czysta]
    
    wynik = process.extractOne(
        nazwa_czysta, 
        baza_towarowa.keys(), 
        scorer=fuzz.token_set_ratio
    )
    
    if wynik and wynik[1] >= prog_podobienstwa:
        return baza_towarowa[wynik[0]]

    return ""


# --- KOMUNIKACJA I WAKE-ON-LAN ---
class KomunikacjaWatek(QObject):
    sygnal_log = pyqtSignal(str)
    sygnal_blad = pyqtSignal(str)
    sygnal_dane_ai = pyqtSignal(dict)
    sygnal_zakonczono = pyqtSignal()


def wyslij_magic_packet(mac_address):
    mac_clean = mac_address.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(mac_clean) != 12:
        raise ValueError("Niepoprawny format adresu MAC (wymagane 12 znaków hex).")
    
    dane_mac = bytes.fromhex(mac_clean)
    magic_packet = b'\xff' * 6 + dane_mac * 16
    
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic_packet, ('255.255.255.255', 9))


def sprawdz_port(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def przygotuj_obraz_do_wysylki(image_data_bytes):
    """
    Standaryzuje format do JPEG i skaluje rozdzielczość, zapobiegając odrzuceniu
    przez API Gemini (Payload Too Large / 400 Bad Request).
    """
    if not image_data_bytes:
        raise ValueError("Brak danych obrazu do wysłania.")
    
    pixmap = QPixmap()
    if not pixmap.loadFromData(image_data_bytes):
        raise ValueError("Nie udało się zdekodować obrazu do przetworzenia.")

    max_wymiar = 1920
    if pixmap.width() > max_wymiar or pixmap.height() > max_wymiar:
        pixmap = pixmap.scaled(
            max_wymiar, max_wymiar,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

    bufor = QBuffer()
    bufor.open(QIODevice.OpenModeFlag.ReadWrite)
    pixmap.save(bufor, "JPEG", 82)
    bajty_jpeg = bytes(bufor.data())
    bufor.close()

    return base64.b64encode(bajty_jpeg).decode("utf-8")


def oczysc_liczbe(wartosc, domyslna="0.00"):
    if wartosc is None:
        return domyslna
    tekst = str(wartosc).strip().replace(",", ".")
    dopasowanie = re.search(r"-?\d+(?:\.\d+)?", tekst)
    return dopasowanie.group(0) if dopasowanie else domyslna


def oczysc_vat(wartosc, domyslna="0"):
    if wartosc is None:
        return domyslna
    tekst = str(wartosc).replace("%", "").replace(",", ".").strip()
    try:
        return str(int(float(tekst)))
    except (ValueError, TypeError):
        return domyslna


def wygeneruj_ikone_aplikacji():
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QBrush(QColor(13, 17, 23)))
    painter.setPen(QPen(QColor(0, 255, 102), 4))
    painter.drawRoundedRect(QRectF(6, 6, 116, 116), 18, 18)

    pen_grid = QPen(QColor(0, 255, 102, 60), 1)
    painter.setPen(pen_grid)
    for i in range(24, 110, 16):
        painter.drawLine(20, i, 108, i)
        painter.drawLine(i, 20, i, 108)

    pen_laser = QPen(QColor(0, 255, 200, 220), 2)
    painter.setPen(pen_laser)
    painter.drawLine(18, 64, 110, 64)

    painter.setPen(QColor(0, 255, 102))
    font_ai = QFont("Consolas", 32, QFont.Weight.Bold)
    painter.setFont(font_ai)
    painter.drawText(QRectF(0, 22, 128, 48), Qt.AlignmentFlag.AlignCenter, "AI")

    painter.setPen(QColor(180, 255, 200))
    font_ocr = QFont("Consolas", 14, QFont.Weight.DemiBold)
    painter.setFont(font_ocr)
    painter.drawText(QRectF(0, 74, 128, 30), Qt.AlignmentFlag.AlignCenter, "OCR")

    painter.end()
    return QIcon(pixmap)


# --- SPLASH SCREEN ---
class CyberSplashScreen(QSplashScreen):
    def __init__(self):
        super().__init__(QPixmap(520, 260), Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.pocisk_x = 40
        self.cel_x = 450
        self.odswiez_klatke(self.pocisk_x)

    def odswiez_klatke(self, x_pos):
        pixmap = QPixmap(520, 260)
        pixmap.fill(QColor(13, 17, 23))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(QPen(QColor(0, 255, 102), 3))
        painter.drawRoundedRect(QRectF(3, 3, 514, 254), 14, 14)

        painter.setPen(QColor(255, 153, 0))
        painter.setFont(QFont("Consolas", 20, QFont.Weight.Bold))
        painter.drawText(QRectF(0, 30, 520, 35), Qt.AlignmentFlag.AlignCenter, "☣️ ocrLmm | PROTOKÓŁ STARTOWY")

        painter.setPen(QColor(139, 148, 158))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(0, 68, 520, 20), Qt.AlignmentFlag.AlignCenter, "Inicjalizacja silnika rozpoznawania...")

        pen_tor = QPen(QColor(0, 255, 102, 70), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen_tor)
        painter.drawLine(40, 150, self.cel_x, 150)

        painter.setPen(QPen(QColor(255, 50, 50), 2))
        painter.drawEllipse(QRectF(self.cel_x - 14, 150 - 14, 28, 28))

        grot = QPolygonF([
            QPointF(x_pos + 15, 150),
            QPointF(x_pos, 144),
            QPointF(x_pos - 12, 146),
            QPointF(x_pos - 8, 150),
            QPointF(x_pos - 12, 154),
            QPointF(x_pos, 156)
        ])
        painter.setBrush(QBrush(QColor(0, 255, 150)))
        painter.drawPolygon(grot)

        painter.setPen(QColor(0, 255, 200))
        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        procent = int(min(100, ((x_pos - 40) / (self.cel_x - 40)) * 100))
        painter.drawText(QRectF(0, 205, 520, 25), Qt.AlignmentFlag.AlignCenter, f"[ PROTOKÓŁ: WINDOWS PC | START: {procent}% ]")

        painter.end()
        self.setPixmap(pixmap)


# --- KONFIGURACJA ---
def wczytaj_konfiguracje():
    domyslne = {
        "silnik": "google",
        "google_api_key": "",
        "google_model": "gemini-3.6-flash",
        "ip_serwera": "192.168.1.154", 
        "port": "1234",
        "mac_serwera": "2C:F0:5D:E4:8E:85",
        "lm_model": "local-model",
        "katalog_zapisu": os.getcwd(),
        "ostatni_katalog_wejsciowy": os.getcwd(),
        "uzywaj_bazy_towarowej": True,
        "sciezka_bazy_txt": BAZA_TOWAROW_TXT
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                dane = json.load(f)
                return {**domyslne, **dane}
        except Exception:
            pass
    return domyslne


def zapisz_konfiguracje(konf):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(konf, f, indent=4)


# --- OKNA DIALOGOWE ---
class BazaTowarowDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("📦 Baza Powiązań Towarów (PC-Market)")
        self.setMinimumSize(720, 540)
        self.setWindowIcon(wygeneruj_ikone_aplikacji())
        self.setStyleSheet("background-color: #0d1117; color: #c9d1d9; font-family: Segoe UI, Consolas;")

        self.mapa = wczytaj_baze_mapowan()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        search_layout = QHBoxLayout()
        lbl_szukaj = QLabel("🔍 Szukaj:")
        lbl_szukaj.setStyleSheet("font-weight: bold; color: #58a6ff;")
        self.input_szukaj = QLineEdit()
        self.input_szukaj.setPlaceholderText("Wpisz fragment nazwy towaru lub kod...")
        self.input_szukaj.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; padding: 6px; border-radius: 5px; color: #c9d1d9;")
        self.input_szukaj.textChanged.connect(self.filtruj_tabele)
        search_layout.addWidget(lbl_szukaj)
        search_layout.addWidget(self.input_szukaj)
        layout.addLayout(search_layout)

        self.tabela_bazy = QTableWidget()
        self.tabela_bazy.setColumnCount(2)
        self.tabela_bazy.setHorizontalHeaderLabels(["Nazwa z faktury (Wzorzec)", "Twój Kod PC-Market"])
        self.tabela_bazy.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabela_bazy.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabela_bazy.setStyleSheet("""
            QTableWidget { background-color: #161b22; gridline-color: #30363d; border: 1px solid #30363d; color: #c9d1d9; font-size: 12px; }
            QHeaderView::section { background-color: #21262d; color: #58a6ff; padding: 6px; font-weight: bold; border: 1px solid #30363d; }
        """)
        layout.addWidget(self.tabela_bazy)

        btn_box = QHBoxLayout()
        self.btn_import_txt = QPushButton("📥 Importuj z NOWA_BAZA.txt")
        self.btn_import_txt.setStyleSheet("background-color: #1f6feb; color: white; padding: 6px 12px; border-radius: 4px; font-weight: bold;")
        self.btn_import_txt.clicked.connect(self.importuj_z_pliku_txt)
        btn_box.addWidget(self.btn_import_txt)

        self.btn_usun = QPushButton("❌ Usuń wpis")
        self.btn_usun.setStyleSheet("background-color: #da3633; color: white; padding: 6px 12px; border-radius: 4px; font-weight: bold;")
        self.btn_usun.clicked.connect(self.usun_wpis)
        btn_box.addWidget(self.btn_usun)

        btn_box.addStretch()

        self.btn_zapisz = QPushButton("💾 Zapisz zmiany")
        self.btn_zapisz.setStyleSheet("background-color: #238636; color: white; padding: 6px 16px; border-radius: 4px; font-weight: bold;")
        self.btn_zapisz.clicked.connect(self.zapisz_zmiany)
        btn_box.addWidget(self.btn_zapisz)

        self.btn_zamknij = QPushButton("Zamknij")
        self.btn_zamknij.setStyleSheet("background-color: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 14px; border-radius: 4px;")
        self.btn_zamknij.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_zamknij)

        layout.addLayout(btn_box)
        self.zaladuj_dane()

    def zaladuj_dane(self):
        self.tabela_bazy.setRowCount(0)
        for r, (nazwa, kod) in enumerate(sorted(self.mapa.items())):
            self.tabela_bazy.insertRow(r)
            self.tabela_bazy.setItem(r, 0, QTableWidgetItem(nazwa))
            self.tabela_bazy.setItem(r, 1, QTableWidgetItem(str(kod)))

    def importuj_z_pliku_txt(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Wybierz plik PC-Market", "", "Pliki tekstowe (*.txt *.csv);;Wszystkie (*.*)")
        if fname:
            baza_dodatkowa = wczytaj_baze_pcmarket(fname)
            if not baza_dodatkowa:
                QMessageBox.warning(self, "Błąd", "Nie znaleziono pozycji w podanym pliku.")
                return
            licznik = 0
            for nazwa, kod in baza_dodatkowa.items():
                if nazwa not in self.mapa:
                    self.mapa[nazwa] = kod
                    licznik += 1
            self.zaladuj_dane()
            QMessageBox.information(self, "Sukces", f"Zaimportowano {licznik} nowych indeksów.")

    def filtruj_tabele(self, tekst):
        tekst = tekst.strip().upper()
        for r in range(self.tabela_bazy.rowCount()):
            it_nazwa = self.tabela_bazy.item(r, 0)
            it_kod = self.tabela_bazy.item(r, 1)
            pasuje = (tekst in (it_nazwa.text() if it_nazwa else "").upper() or 
                      tekst in (it_kod.text() if it_kod else "").upper())
            self.tabela_bazy.setRowHidden(r, not pasuje)

    def usun_wpis(self):
        row = self.tabela_bazy.currentRow()
        if row >= 0:
            it = self.tabela_bazy.item(row, 0)
            nazwa = it.text() if it else ""
            if QMessageBox.question(self, "Potwierdzenie", f"Usunąć powiązanie dla:\n{nazwa}?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.tabela_bazy.removeRow(row)

    def zapisz_zmiany(self):
        nowa_mapa = {}
        for r in range(self.tabela_bazy.rowCount()):
            it_n = self.tabela_bazy.item(r, 0)
            it_k = self.tabela_bazy.item(r, 1)
            if it_n and it_k:
                nazwa = it_n.text().strip().upper()
                kod = it_k.text().strip()
                if nazwa and kod:
                    nowa_mapa[nazwa] = kod
        
        zapisz_baze_mapowan(nowa_mapa)
        if self.parent_window:
            self.parent_window.zaladuj_wszystkie_bazy()
            self.parent_window.log(f"Zaktualizowano bazę powiązań ({len(nowa_mapa)} wpisów).")
        QMessageBox.information(self, "Sukces", "Baza została pomyślnie zaktualizowana.")
        self.accept()


class OProgramieDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("☣️ O programie ocrLmm | Informacje")
        self.setFixedSize(580, 520)
        self.setStyleSheet("background-color: #0d1117; color: #c9d1d9; font-family: Segoe UI, Consolas;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        naglowek = QLabel("☣️ ocrLmm v2.5 — PROTOKÓŁ BIOHAZARD (WINDOWS)")
        naglowek.setStyleSheet("color: #ff9900; font-size: 16px; font-weight: bold; font-family: Consolas;")
        naglowek.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(naglowek)

        autor = QLabel("Twórca: <b style='color: #00ff66;'>Zizi</b>")
        autor.setStyleSheet("font-size: 14px;")
        autor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(autor)

        instrukcja = QTextEdit()
        instrukcja.setReadOnly(True)
        instrukcja.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; color: #c9d1d9; font-size: 13px;")
        instrukcja.setHtml("""
            <h3 style="color: #00ff66; margin-top:0;">Hybrydowy konwerter EDI dla Windows 10/11</h3>
            <p>System konwersji dokumentów (OCR + LLM) na znormalizowany format <b>EDI PC-Market (PZ)</b>. Aplikacja analizuje zrzuty ekranu, wielostronicowe pliki PDF oraz zdjęcia z aparatów, wyodrębniając dane nagłówkowe i asortymentowe.</p>
            <ul>
                <li><b>Architektura Dual-Engine:</b> Praca w chmurze (Google Gemini API - precyzja i szybkość) oraz lokalnie/w sieci LAN poprzez LM Studio (prywatność, akceleracja GPU, WoL).</li>
                <li><b>Obsługa wysokiej rozdzielczości:</b> Wbudowany silnik kompresji optymalizuje ujęcia z aparatów i telefonów do optymalnej wielkości payloadu bez utraty czytelności cyfr.</li>
                <li><b>Inteligentne mapowanie (Fuzzy Matching):</b> Algorytm <i>thefuzz (token_set_ratio)</i> paruje pozycje z lokalną bazą NOWA_BAZA.txt.</li>
                <li><b>Walidacja w locie:</b> Porównywanie sum pozycji z nagłówkiem faktury w czasie rzeczywistym.</li>
                <li><b>Eksport Windows-1250:</b> Pełna obsługa polskich znaków i standardu <i>TypPolskichLiter:LA</i>.</li>
            </ul>
        """)
        layout.addWidget(instrukcja)

        btn_zamknij = QPushButton("Zamknij")
        btn_zamknij.setStyleSheet("background-color: #21262d; border: 1px solid #ff9900; color: #ff9900; font-weight: bold; padding: 8px; border-radius: 5px;")
        btn_zamknij.clicked.connect(self.accept)
        layout.addWidget(btn_zamknij)


class UstawieniaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ocrLmm - Konfiguracja Silnika AI i Bazy")
        self.setFixedSize(580, 620)
        self.setWindowIcon(wygeneruj_ikone_aplikacji())
        self.setStyleSheet("background-color: #0d1117; color: #c9d1d9;")
        
        self.konf = wczytaj_konfiguracje()
        layout = QVBoxLayout(self)

        self.frame_baza = QFrame()
        self.frame_baza.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 8px;")
        fb_layout = QVBoxLayout(self.frame_baza)
        
        self.chk_uzywaj_bazy = QCheckBox("📦 Przeszukuj bazę towarową PC-Market (thefuzz)")
        self.chk_uzywaj_bazy.setChecked(self.konf.get("uzywaj_bazy_towarowej", True))
        self.chk_uzywaj_bazy.setStyleSheet("font-weight: bold; color: #00ff66; font-size: 13px;")
        fb_layout.addWidget(self.chk_uzywaj_bazy)

        baza_plik_layout = QHBoxLayout()
        lbl_baza_plik = QLabel("Plik wzorca (NOWA_BAZA.txt):")
        self.input_sciezka_bazy = QLineEdit(self.konf.get("sciezka_bazy_txt", BAZA_TOWAROW_TXT))
        self.btn_wybierz_baze = QPushButton("Przeglądaj...")
        self.btn_wybierz_baze.clicked.connect(self.wybierz_plik_bazy)
        baza_plik_layout.addWidget(lbl_baza_plik)
        baza_plik_layout.addWidget(self.input_sciezka_bazy)
        baza_plik_layout.addWidget(self.btn_wybierz_baze)
        fb_layout.addLayout(baza_plik_layout)
        layout.addWidget(self.frame_baza)

        self.radio_google = QRadioButton("🚀 Google Gemini API (Szybkie)")
        self.radio_lmstudio = QRadioButton("🖥️ Lokalne LM Studio (LAN / Serwer GPU)")
        
        self.btn_group = QButtonGroup(self)
        self.btn_group.addButton(self.radio_google, 1)
        self.btn_group.addButton(self.radio_lmstudio, 2)

        if self.konf.get("silnik") == "lmstudio":
            self.radio_lmstudio.setChecked(True)
        else:
            self.radio_google.setChecked(True)

        layout.addWidget(self.radio_google)
        layout.addWidget(self.radio_lmstudio)

        self.frame_google = QFrame()
        self.frame_google.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 6px;")
        fg_layout = QFormLayout(self.frame_google)
        self.input_google_key = QLineEdit(self.konf.get("google_api_key", ""))
        self.input_google_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_google_key.setPlaceholderText("Wklej klucz AIzaSy...")
        self.input_google_model = QLineEdit(self.konf.get("google_model", "gemini-3.6-flash"))
        fg_layout.addRow("Google API Key:", self.input_google_key)
        fg_layout.addRow("Model Gemini:", self.input_google_model)
        layout.addWidget(self.frame_google)

        self.frame_lm = QFrame()
        self.frame_lm.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 6px;")
        flm_layout = QFormLayout(self.frame_lm)
        self.input_ip = QLineEdit(self.konf.get("ip_serwera", "192.168.1.154"))
        self.input_port = QLineEdit(self.konf.get("port", "1234"))
        self.input_mac = QLineEdit(self.konf.get("mac_serwera", "2C:F0:5D:E4:8E:85"))
        self.input_lm_model = QLineEdit(self.konf.get("lm_model", "local-model"))
        flm_layout.addRow("IP serwera LAN:", self.input_ip)
        flm_layout.addRow("Port serwera:", self.input_port)
        flm_layout.addRow("Adres MAC (WoL):", self.input_mac)
        flm_layout.addRow("Model LM Studio:", self.input_lm_model)

        self.btn_wol_test = QPushButton("⚡ Wyślij Magic Packet (WoL)")
        self.btn_wol_test.setStyleSheet("background-color: #21262d; border: 1px solid #00ff66; color: #00ff66; padding: 4px;")
        self.btn_wol_test.clicked.connect(self.testuj_wol)
        flm_layout.addRow("", self.btn_wol_test)
        layout.addWidget(self.frame_lm)

        katalog_layout = QHBoxLayout()
        self.input_katalog = QLineEdit(self.konf.get("katalog_zapisu", os.getcwd()))
        self.btn_przegladaj_katalog = QPushButton("Folder EDI...")
        self.btn_przegladaj_katalog.clicked.connect(self.wybierz_katalog_zapisu)
        katalog_layout.addWidget(self.input_katalog)
        katalog_layout.addWidget(self.btn_przegladaj_katalog)
        layout.addLayout(katalog_layout)

        btn_layout = QHBoxLayout()
        self.btn_zapisz = QPushButton("Zapisz")
        self.btn_zapisz.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 8px;")
        self.btn_zapisz.clicked.connect(self.zapisz_i_zamknij)
        
        btn_anuluj = QPushButton("Anuluj")
        btn_anuluj.setStyleSheet("padding: 8px;")
        btn_anuluj.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_zapisz)
        btn_layout.addWidget(btn_anuluj)
        layout.addLayout(btn_layout)

        self.toggle_widoki(self.radio_google.isChecked())
        self.radio_google.toggled.connect(self.toggle_widoki)

    def wybierz_plik_bazy(self):
        fpath, _ = QFileDialog.getOpenFileName(self, "Wybierz plik PC-Market", self.input_sciezka_bazy.text(), "Pliki tekstowe (*.txt *.csv);;Wszystkie (*.*)")
        if fpath:
            self.input_sciezka_bazy.setText(fpath)

    def toggle_widoki(self, google_aktywny):
        self.frame_google.setEnabled(google_aktywny)
        self.frame_lm.setEnabled(not google_aktywny)

    def testuj_wol(self):
        mac = self.input_mac.text().strip()
        try:
            wyslij_magic_packet(mac)
            QMessageBox.information(self, "WoL", f"Pakiet Magic Packet wysłany na MAC: {mac}")
        except Exception as e:
            QMessageBox.warning(self, "Błąd WoL", f"Niepoprawny format MAC:\n{e}")

    def wybierz_katalog_zapisu(self):
        katalog = QFileDialog.getExistingDirectory(self, "Wybierz folder EDI", self.input_katalog.text())
        if katalog:
            self.input_katalog.setText(katalog)

    def zapisz_i_zamknij(self):
        self.konf["uzywaj_bazy_towarowej"] = self.chk_uzywaj_bazy.isChecked()
        self.konf["sciezka_bazy_txt"] = self.input_sciezka_bazy.text().strip()
        self.konf["silnik"] = "google" if self.radio_google.isChecked() else "lmstudio"
        self.konf["google_api_key"] = self.input_google_key.text().strip()
        gmodel = self.input_google_model.text().strip()
        self.konf["google_model"] = gmodel if gmodel else "gemini-3.6-flash"
        self.konf["ip_serwera"] = self.input_ip.text().strip()
        self.konf["port"] = self.input_port.text().strip()
        self.konf["mac_serwera"] = self.input_mac.text().strip()
        lmodel = self.input_lm_model.text().strip()
        self.konf["lm_model"] = lmodel if lmodel else "local-model"
        kat = self.input_katalog.text().strip()
        self.konf["katalog_zapisu"] = kat if kat else os.getcwd()
        zapisz_konfiguracje(self.konf)
        self.accept()


# --- OBSZAR DRAG & DROP ---
class DropZoneArea(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setMinimumSize(400, 180)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.setStyleSheet("""
            QFrame { border: 2px dashed #00ff66; border-radius: 10px; background-color: #161b22; }
            QFrame:hover { border: 2px dashed #39ff14; background-color: #1b222c; }
        """)

        layout = QVBoxLayout(self)
        self.label_info = QLabel("🖨️ Wklej screenshot (Ctrl+V) lub upuść fakturę (PDF, PNG, JPG)")
        self.label_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_info.setStyleSheet("color: #7ee787; font-size: 13px; background: transparent; border: none; font-family: Consolas;")
        layout.addWidget(self.label_info)

    def set_image_pixmap(self, qpixmap):
        scaled = qpixmap.scaled(
            self.width() - 30, self.height() - 30, 
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.label_info.setPixmap(scaled)
        self.label_info.setText("")
        self.setStyleSheet("QFrame { border: 2px solid #00ff66; border-radius: 10px; background-color: #161b22; }")

    def clear_area(self):
        self.label_info.clear()
        self.label_info.setText("🖨️ Wklej screenshot (Ctrl+V) lub upuść fakturę (PDF, PNG, JPG)")
        self.setStyleSheet("QFrame { border: 2px dashed #00ff66; border-radius: 10px; background-color: #161b22; }")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("background-color: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 4px;")
        akcja_wklej = menu.addAction("📋 Wklej obraz ze schowka")
        akcja_wybierz = menu.addAction("📁 Wybierz plik z dysku...")
        
        wybrana = menu.exec(event.globalPos())
        if wybrana == akcja_wklej and self.parent_window:
            self.parent_window.wklej_ze_schowka()
        elif wybrana == akcja_wybierz and self.parent_window:
            self.parent_window.wybierz_plik_klikniecie()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.parent_window:
            self.parent_window.wybierz_plik_klikniecie()
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                self.parent_window.zaladowano_plik_sciezka(urls[0].toLocalFile())
        event.accept()


# --- GŁÓWNE OKNO ---
class OcrLmmMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ocrLmm - Konwerter Faktur PZ do PC-Market")
        self.setMinimumSize(1060, 860)
        self.setWindowIcon(wygeneruj_ikone_aplikacji())

        self.image_data_bytes = None
        self.odczytane_dane_ai = None
        
        self.baza_mapowan = {}
        self.zaladuj_wszystkie_bazy()

        self.komunikacja = KomunikacjaWatek()
        self.komunikacja.sygnal_log.connect(self.log)
        self.komunikacja.sygnal_blad.connect(self.pokaz_blad)
        self.komunikacja.sygnal_dane_ai.connect(self.wypelnij_tabele_pozycjami)
        self.komunikacja.sygnal_zakonczono.connect(self.odblokuj_przyciski)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(16, 16, 16, 16)

        top_layout = QHBoxLayout()
        logo_label = QLabel()
        logo_label.setPixmap(wygeneruj_ikone_aplikacji().pixmap(36, 36))
        top_layout.addWidget(logo_label)

        tytul_layout = QVBoxLayout()
        label_tytul = QLabel("ocrLmm | PC-Market EDI")
        label_tytul.setStyleSheet("font-size: 22px; font-weight: bold; color: #00ff66; font-family: Consolas;")
        tytul_layout.addWidget(label_tytul)
        
        label_podtytul = QLabel("Hybrydowy konwerter AI (Gemini / LM Studio) dla Windows 10/11")
        label_podtytul.setStyleSheet("color: #7ee787; font-size: 11px;")
        tytul_layout.addWidget(label_podtytul)
        top_layout.addLayout(tytul_layout)
        top_layout.addStretch()

        self.btn_baza = QPushButton("📦 Baza towarów")
        self.btn_baza.setStyleSheet("background-color: #21262d; color: #58a6ff; border: 1px solid #58a6ff; padding: 6px 10px; border-radius: 5px; font-weight: bold;")
        self.btn_baza.clicked.connect(self.otworz_baze_towarow)
        top_layout.addWidget(self.btn_baza)

        self.btn_about = QPushButton("☣️ Biohazard")
        self.btn_about.setStyleSheet("background-color: #21262d; color: #ff9900; border: 1px solid #ff9900; padding: 6px 10px; border-radius: 5px; font-weight: bold;")
        self.btn_about.clicked.connect(self.otworz_o_programie)
        top_layout.addWidget(self.btn_about)

        self.btn_open_folder = QPushButton("📂 Folder EDI")
        self.btn_open_folder.setStyleSheet("background-color: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 6px 10px; border-radius: 5px; font-weight: bold;")
        self.btn_open_folder.clicked.connect(self.otworz_folder_zapisu)
        top_layout.addWidget(self.btn_open_folder)

        self.btn_settings = QPushButton("⚙️ Ustawienia")
        self.btn_settings.setStyleSheet("background-color: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 6px 12px; border-radius: 5px; font-weight: bold;")
        self.btn_settings.clicked.connect(self.otworz_ustawienia)
        top_layout.addWidget(self.btn_settings)
        main_layout.addLayout(top_layout)

        self.drop_zone = DropZoneArea(self)
        self.drop_zone.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        main_layout.addWidget(self.drop_zone)

        btn_layout = QHBoxLayout()
        self.btn_wybierz = QPushButton("📁 Wybierz plik (PDF / Obraz)...")
        self.btn_wybierz.setStyleSheet("background-color: #1f6feb; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        self.btn_wybierz.clicked.connect(self.wybierz_plik_klikniecie)
        btn_layout.addWidget(self.btn_wybierz)

        self.btn_reset = QPushButton("🗑️ Wyczyść wszystko")
        self.btn_reset.setStyleSheet("background-color: #da3633; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        self.btn_reset.clicked.connect(self.resetuj_aplikacje)
        btn_layout.addWidget(self.btn_reset)
        main_layout.addLayout(btn_layout)

        self.btn_start = QPushButton("⚡ 1. Rozpoznaj pozycje z faktury")
        self.btn_start.setStyleSheet("background-color: #238636; color: white; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 5px;")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.uruchom_przetwarzanie)
        main_layout.addWidget(self.btn_start)

        table_tools_layout = QHBoxLayout()
        lbl_tabela = QLabel("Tabela pozycji (podwójny klik = edycja):")
        lbl_tabela.setStyleSheet("color: #58a6ff; font-weight: bold;")
        table_tools_layout.addWidget(lbl_tabela)
        table_tools_layout.addStretch()

        self.btn_add_row = QPushButton("➕ Wstaw wiersz")
        self.btn_add_row.setStyleSheet("background-color: #21262d; color: #00ff66; border: 1px solid #00ff66; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_add_row.clicked.connect(self.wstaw_wiersz_w_miejscu)
        table_tools_layout.addWidget(self.btn_add_row)

        self.btn_clean_row = QPushButton("🧹 Wyczyść liczby")
        self.btn_clean_row.setStyleSheet("background-color: #21262d; color: #ff9900; border: 1px solid #ff9900; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_clean_row.clicked.connect(self.wyczysc_wiersz)
        table_tools_layout.addWidget(self.btn_clean_row)

        self.btn_del_row = QPushButton("❌ Usuń wiersz")
        self.btn_del_row.setStyleSheet("background-color: #21262d; color: #ff7b72; border: 1px solid #ff7b72; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.btn_del_row.clicked.connect(self.usun_zaznaczony_wiersz)
        table_tools_layout.addWidget(self.btn_del_row)

        main_layout.addLayout(table_tools_layout)

        self.tabela = QTableWidget()
        self.tabela.setColumnCount(6)
        self.tabela.setHorizontalHeaderLabels([
            "Nazwa z faktury", 
            "Kod dostawcy / CN / EAN", 
            "Twój Kod PC-Market", 
            "Ilość", 
            "Cena Netto", 
            "VAT"
        ])
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabela.itemChanged.connect(self.komorka_zmieniona)
        self.tabela.setStyleSheet("""
            QTableWidget { background-color: #161b22; gridline-color: #30363d; border: 1px solid #30363d; color: #c9d1d9; font-size: 12px; }
            QHeaderView::section { background-color: #21262d; color: #58a6ff; padding: 5px; font-weight: bold; border: 1px solid #30363d; }
        """)
        main_layout.addWidget(self.tabela)

        self.panel_walidacji = QFrame()
        self.panel_walidacji.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 4px;")
        walidacja_layout = QHBoxLayout(self.panel_walidacji)
        walidacja_layout.setContentsMargins(10, 4, 10, 4)

        self.lbl_walidacja = QLabel("Suma pozycji: 0.00 PLN")
        self.lbl_walidacja.setStyleSheet("font-family: Consolas; font-size: 13px; font-weight: bold; color: #8b949e;")
        walidacja_layout.addWidget(self.lbl_walidacja)
        walidacja_layout.addStretch()
        main_layout.addWidget(self.panel_walidacji)

        self.btn_zapisz_edi = QPushButton("💾 2. Zapisz gotowy plik EDI do PC-Market")
        self.btn_zapisz_edi.setStyleSheet("background-color: #1f6feb; color: white; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 5px;")
        self.btn_zapisz_edi.setEnabled(False)
        self.btn_zapisz_edi.clicked.connect(self.zapisz_finalny_plik_edi)
        main_layout.addWidget(self.btn_zapisz_edi)

        self.text_logi = QTextEdit()
        self.text_logi.setReadOnly(True)
        self.text_logi.setMaximumHeight(90)
        self.text_logi.setStyleSheet("background-color: #0d1117; color: #58a6ff; font-family: Consolas; font-size: 11px; border: 1px solid #30363d;")
        main_layout.addWidget(self.text_logi)

        self.setStyleSheet("QMainWindow { background-color: #0d1117; color: #c9d1d9; }")
        self.log("ocrLmm gotowy do pracy na Windows. Bazy załadowane.")

    def zaladuj_wszystkie_bazy(self):
        konf = wczytaj_konfiguracje()
        mapa_reczna = wczytaj_baze_mapowan()
        
        if konf.get("uzywaj_bazy_towarowej", True):
            sciezka_txt = konf.get("sciezka_bazy_txt", BAZA_TOWAROW_TXT)
            baza_txt = wczytaj_baze_pcmarket(sciezka_txt)
            self.baza_mapowan = {**baza_txt, **mapa_reczna}
        else:
            self.baza_mapowan = mapa_reczna

    def log(self, komunikat):
        czas = datetime.now().strftime("%H:%M:%S")
        self.text_logi.append(f"[{czas}] {komunikat}")
        sb = self.text_logi.verticalScrollBar()
        sb.setValue(sb.maximum())

    def pokaz_blad(self, powod):
        QMessageBox.critical(self, "Błąd", str(powod), QMessageBox.StandardButton.Ok)

    def odblokuj_przyciski(self):
        self.btn_start.setEnabled(True)
        self.btn_wybierz.setEnabled(True)
        self.btn_reset.setEnabled(True)

    def closeEvent(self, event):
        odp = QMessageBox.question(
            self, "☣️ Potwierdzenie", "Czy zamknąć program ocrLmm?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if odp == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()

    def otworz_baze_towarow(self):
        dialog = BazaTowarowDialog(self)
        dialog.exec()
        self.zaladuj_wszystkie_bazy()

    def otworz_o_programie(self):
        dialog = OProgramieDialog(self)
        dialog.exec()

    def otworz_ustawienia(self):
        dialog = UstawieniaDialog(self)
        if dialog.exec():
            self.zaladuj_wszystkie_bazy()
            konf = wczytaj_konfiguracje()
            status = "WŁĄCZONE" if konf.get("uzywaj_bazy_towarowej") else "WYŁĄCZONE"
            self.log(f"Zapisano konfigurację. Baza: {status} (Łącznie pozycji: {len(self.baza_mapowan)})")

    def otworz_folder_zapisu(self):
        konf = wczytaj_konfiguracje()
        katalog = konf.get("katalog_zapisu", os.getcwd())
        if not os.path.exists(katalog):
            os.makedirs(katalog, exist_ok=True)
        os.startfile(katalog)

    def resetuj_aplikacje(self):
        self.image_data_bytes = None
        self.odczytane_dane_ai = None
        self.drop_zone.clear_area()
        self.tabela.blockSignals(True)
        self.tabela.setRowCount(0)
        self.tabela.blockSignals(False)
        self.lbl_walidacja.setText("Suma pozycji: 0.00 PLN")
        self.panel_walidacji.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 4px;")
        self.btn_start.setEnabled(False)
        self.btn_zapisz_edi.setEnabled(False)
        self.log("Wyczyszczono obszar roboczy.")

    def przelicz_walidacje_sumy(self):
        suma_tabeli = 0.0
        wiersze = self.tabela.rowCount()

        for r in range(wiersze):
            try:
                ilosc_str = self.tabela.item(r, 3).text() if self.tabela.item(r, 3) else "0"
                cena_str = self.tabela.item(r, 4).text() if self.tabela.item(r, 4) else "0"
                ilosc = float(oczysc_liczbe(ilosc_str, "0"))
                cena = float(oczysc_liczbe(cena_str, "0"))
                suma_tabeli += (ilosc * cena)
            except Exception:
                pass

        suma_faktury_str = (self.odczytane_dane_ai or {}).get("suma_netto", "")
        if suma_faktury_str:
            try:
                suma_faktury = float(oczysc_liczbe(suma_faktury_str, "0"))
                roznica = round(suma_tabeli - suma_faktury, 2)
                if abs(roznica) <= 0.05:
                    self.lbl_walidacja.setText(f"✅ Suma zgodna z fakturą: {suma_tabeli:.2f} PLN (Oryginał: {suma_faktury:.2f} PLN)")
                    self.panel_walidacji.setStyleSheet("background-color: #0d2818; border: 1px solid #00ff66; border-radius: 6px; padding: 4px;")
                    self.lbl_walidacja.setStyleSheet("font-family: Consolas; font-size: 13px; font-weight: bold; color: #00ff66;")
                else:
                    znak = "+" if roznica > 0 else ""
                    self.lbl_walidacja.setText(f"⚠️ Rozbieżność sumy! W tabeli: {suma_tabeli:.2f} PLN | Na fakturze: {suma_faktury:.2f} PLN (Różnica: {znak}{roznica:.2f} PLN)")
                    self.panel_walidacji.setStyleSheet("background-color: #3b1111; border: 1px solid #ff7b72; border-radius: 6px; padding: 4px;")
                    self.lbl_walidacja.setStyleSheet("font-family: Consolas; font-size: 13px; font-weight: bold; color: #ff7b72;")
                return
            except Exception:
                pass

        self.lbl_walidacja.setText(f"Suma netto pozycji: {suma_tabeli:.2f} PLN")
        self.panel_walidacji.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 4px;")
        self.lbl_walidacja.setStyleSheet("font-family: Consolas; font-size: 13px; font-weight: bold; color: #58a6ff;")

    def komorka_zmieniona(self, item):
        col = item.column()
        row = item.row()

        if col == 0:
            konf = wczytaj_konfiguracje()
            if konf.get("uzywaj_bazy_towarowej", True):
                nazwa = item.text().strip().upper()
                kod_item = self.tabela.item(row, 2)
                if kod_item and not kod_item.text().strip():
                    znaleziony_kod = znajdz_kod_fuzzy(nazwa, self.baza_mapowan)
                    if znaleziony_kod:
                        kod_item.setText(znaleziony_kod)
                        kod_item.setBackground(QColor(16, 75, 36))

        elif col == 2:
            kod = item.text().strip()
            if kod and kod != "0":
                item.setBackground(QColor(16, 75, 36))
            else:
                item.setBackground(QColor(95, 25, 25))

        elif col in (3, 4):
            self.przelicz_walidacje_sumy()

    def wstaw_wiersz_w_miejscu(self):
        row = self.tabela.currentRow()
        if row < 0:
            row = self.tabela.rowCount()

        self.tabela.blockSignals(True)
        self.tabela.insertRow(row)
        self.tabela.setItem(row, 0, QTableWidgetItem("NOWA POZYCJA"))
        self.tabela.setItem(row, 1, QTableWidgetItem(""))
        
        item_kod = QTableWidgetItem("0")
        item_kod.setBackground(QColor(95, 25, 25))
        self.tabela.setItem(row, 2, item_kod)
        
        self.tabela.setItem(row, 3, QTableWidgetItem("1.00"))
        self.tabela.setItem(row, 4, QTableWidgetItem("0.00"))
        self.tabela.setItem(row, 5, QTableWidgetItem("5"))
        self.tabela.blockSignals(False)

        self.tabela.selectRow(row)
        self.btn_zapisz_edi.setEnabled(True)
        self.przelicz_walidacje_sumy()
        self.log(f"Wstawiono nowy wiersz na pozycji {row + 1}.")

    def usun_zaznaczony_wiersz(self):
        row = self.tabela.currentRow()
        if row >= 0:
            self.tabela.removeRow(row)
            self.przelicz_walidacje_sumy()
            self.log(f"Usunięto wiersz {row + 1}.")
        else:
            self.log("Zaznacz wiersz do usunięcia.")

    def wyczysc_wiersz(self):
        row = self.tabela.currentRow()
        if row >= 0:
            self.tabela.blockSignals(True)
            self.tabela.item(row, 3).setText("1.00")
            self.tabela.item(row, 4).setText("0.00")
            self.tabela.blockSignals(False)
            self.przelicz_walidacje_sumy()
            self.log(f"Wyzerowano wartości w wierszu {row + 1}.")
        else:
            self.log("Zaznacz wiersz, który chcesz wyczyścić.")

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.wklej_ze_schowka()
        elif event.key() == Qt.Key.Key_Delete and self.tabela.hasFocus():
            self.usun_zaznaczony_wiersz()
        else:
            super().keyPressEvent(event)

    def wklej_ze_schowka(self):
        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                self.drop_zone.set_image_pixmap(pixmap)
                
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.ReadWrite)
                image.save(buffer, "JPEG", 90)
                self.image_data_bytes = bytes(buffer.data())
                buffer.close()

                self.btn_start.setEnabled(True)
                self.log("Wklejono obraz ze schowka systemowego.")
        else:
            self.log("W schowku brak obrazu.")

    def wybierz_plik_klikniecie(self):
        konf = wczytaj_konfiguracje()
        folder_startowy = konf.get("ostatni_katalog_wejsciowy", os.getcwd())
        if not os.path.exists(folder_startowy):
            folder_startowy = os.getcwd()

        fname, _ = QFileDialog.getOpenFileName(
            self, "Wybierz fakturę", folder_startowy, 
            "Wszystkie (*.pdf *.png *.jpg *.jpeg *.bmp);;PDF (*.pdf);;Obrazy (*.png *.jpg *.jpeg *.bmp)"
        )
        if fname:
            konf["ostatni_katalog_wejsciowy"] = os.path.dirname(fname)
            zapisz_konfiguracje(konf)
            self.zaladowano_plik_sciezka(fname)

    def zaladowano_plik_sciezka(self, sciezka):
        try:
            katalog_pliku = os.path.dirname(sciezka)
            if katalog_pliku:
                konf = wczytaj_konfiguracje()
                if konf.get("ostatni_katalog_wejsciowy") != katalog_pliku:
                    konf["ostatni_katalog_wejsciowy"] = katalog_pliku
                    zapisz_konfiguracje(konf)

            if sciezka.lower().endswith(".pdf"):
                self.log(f"Wczytywanie PDF: {os.path.basename(sciezka)}...")
                doc = pymupdf.open(sciezka)
                liczba_stron = len(doc)
                if liczba_stron == 0:
                    raise Exception("Plik PDF jest pusty.")

                lista_pixmap = []
                # Optymalna macierz skalowania (1.5 zamiast 2.0 zapewnia czytelność i mniejszy rozmiar)
                macierz = pymupdf.Matrix(1.5, 1.5)
                for i in range(min(liczba_stron, 4)):  # Ograniczenie do pierwszych 4 stron
                    strona = doc[i]
                    pix = strona.get_pixmap(matrix=macierz)
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                    lista_pixmap.append(QPixmap.fromImage(img.copy()))
                doc.close()

                max_width = max(p.width() for p in lista_pixmap)
                total_height = sum(p.height() for p in lista_pixmap)

                polaczona_pixmap = QPixmap(max_width, total_height)
                polaczona_pixmap.fill(Qt.GlobalColor.white)

                painter = QPainter(polaczona_pixmap)
                cur_y = 0
                for p in lista_pixmap:
                    painter.drawPixmap(0, cur_y, p)
                    cur_y += p.height()
                painter.end()

                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.ReadWrite)
                polaczona_pixmap.save(buffer, "JPEG", 85)
                self.image_data_bytes = bytes(buffer.data())
                buffer.close()

                self.drop_zone.set_image_pixmap(polaczona_pixmap)
                self.btn_start.setEnabled(True)
                self.log(f"Załadowano PDF ({liczba_stron} stron): {os.path.basename(sciezka)}")
            else:
                pixmap = QPixmap(sciezka)
                if pixmap.isNull():
                    raise Exception("Niepoprawny plik graficzny.")
                self.drop_zone.set_image_pixmap(pixmap)
                with open(sciezka, "rb") as f:
                    self.image_data_bytes = f.read()
                    
                self.btn_start.setEnabled(True)
                self.log(f"Wczytano plik: {os.path.basename(sciezka)}")
        except Exception as e:
            self.pokaz_blad(f"Nie udało się załadować dokumentu:\n{e}")

    def uruchom_przetwarzanie(self):
        if not self.image_data_bytes:
            return
        self.btn_start.setEnabled(False)
        self.btn_wybierz.setEnabled(False)
        self.btn_reset.setEnabled(False)
        self.btn_zapisz_edi.setEnabled(False)
        threading.Thread(target=self.przetwarzaj_w_tle, daemon=True).start()

    def przetwarzaj_w_tle(self):
        try:
            konf = wczytaj_konfiguracje()
            silnik = konf.get("silnik", "google")
            base64_img = przygotuj_obraz_do_wysylki(self.image_data_bytes)

            prompt_systemowy = (
                "Jesteś precyzyjnym systemem OCR do dokumentów magazynowych, specyfikacji i faktur.\n"
                "Przeanalizuj obraz i zwróć WYŁĄCZNIE poprawny JSON bez żadnych bloków markdown i bez zbędnych komentarzy.\n"
                "Reguły ekstrakcji:\n"
                "1. NIP: Odczytaj wyłącznie cyfry NIP wystawcy/sprzedawcy z góry dokumentu.\n"
                "2. Kod dostawcy: Pobierz kod CN, indeks lub EAN. Jeśli brak – wpisz \"\".\n"
                "3. Ceny i wartości: Pobieraj wartości NETTO. Używaj kropki jako separatora dziesiętnego, bez symboli walut.\n"
                "4. Przepisz wszystkie pozycje asortymentowe linijka po linijce.\n\n"
                "Format wyjściowy JSON:\n"
                "{\n"
                '  "nr": "numer dokumentu",\n'
                '  "data": "DD.MM.RRRR",\n'
                '  "nip": "same_cyfry",\n'
                '  "suma_netto": "0.00",\n'
                '  "pozycje": [\n'
                '    {"lp": 1, "nazwa": "...", "kod_dostawcy": "...", "vat": "5", "jm": "kg", "ilosc": "0.00", "cena": "0.00", "wartosc": "0.00"}\n'
                "  ]\n"
                "}"
            )

            wiadomosci = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_systemowy},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }]

            if silnik == "google":
                api_key = konf.get("google_api_key", "").strip()
                if not api_key:
                    raise ValueError("Brak klucza Google API Key. Wprowadź go w ⚙️ Ustawienia.")
                
                model_name = konf.get("google_model", "gemini-3.6-flash").strip()
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
                self.komunikacja.sygnal_log.emit(f"Łączenie z Google Gemini API [{model_name}]...")
                client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0)

                call_params = {
                    "model": model_name,
                    "messages": wiadomosci,
                    "temperature": 0.0,
                    "max_tokens": 4096
                }
            else:
                ip = konf.get("ip_serwera", "192.168.1.154").strip()
                port = konf.get("port", "1234").strip()
                mac = konf.get("mac_serwera", "2C:F0:5D:E4:8E:85").strip()
                model_name = konf.get("lm_model", "local-model").strip() or "local-model"
                base_url = f"http://{ip}:{port}/v1"

                self.komunikacja.sygnal_log.emit(f"Sprawdzanie serwera lokalnego {ip}:{port}...")
                if not sprawdz_port(ip, port, timeout=1.5):
                    self.komunikacja.sygnal_log.emit("Wysyłanie sygnału Wake-on-LAN...")
                    try:
                        wyslij_magic_packet(mac)
                    except Exception:
                        pass

                    serwer_wstal = False
                    for _ in range(30):
                        time.sleep(1.0)
                        if sprawdz_port(ip, port, timeout=1.0):
                            serwer_wstal = True
                            break

                    if not serwer_wstal:
                        raise ConnectionError(f"Serwer {ip}:{port} nie odpowiedział na próbę połączenia.")

                self.komunikacja.sygnal_log.emit(f"Łączenie z LM Studio [{model_name}]...")
                client = OpenAI(base_url=base_url, api_key="lm-studio", timeout=120.0)

                call_params = {
                    "model": model_name,
                    "messages": wiadomosci,
                    "temperature": 0.1,
                    "max_tokens": 3000
                }

            max_retries = 3
            delay_base = 2.0
            response = None

            for attempt in range(max_retries):
                try:
                    response = client.chat.completions.create(**call_params)
                    break
                except APIStatusError as e:
                    if e.status_code in (503, 429) and attempt < max_retries - 1:
                        wait_time = delay_base * (2 ** attempt)
                        self.komunikacja.sygnal_log.emit(
                            f"⚠️ Serwer zajęty ({e.status_code}). Ponowienie {attempt + 1}/{max_retries} za {wait_time:.1f}s..."
                        )
                        time.sleep(wait_time)
                    else:
                        raise e
                except Exception as e:
                    raise e

            if not response:
                raise TimeoutError("Wyczerpano limit prób połączenia z modelem AI.")

            odpowiedz_ai = response.choices[0].message.content.strip()
            
            match = re.search(r"\{.*\}", odpowiedz_ai, re.DOTALL)
            if not match:
                raise ValueError("Brak struktury JSON w odpowiedzi silnika AI.")

            final_dane = json.loads(match.group(0))
            pozycje = final_dane.get("pozycje", [])
            if not pozycje:
                raise ValueError("Nie wykryto pozycji asortymentowych na dokumencie.")

            if final_dane.get("nip"):
                final_dane["nip"] = re.sub(r"\D", "", str(final_dane["nip"]))

            self.komunikacja.sygnal_dane_ai.emit(final_dane)
            self.komunikacja.sygnal_log.emit(f"✅ Rozpoznano {len(pozycje)} pozycji.")

        except Exception as e:
            self.komunikacja.sygnal_blad.emit(f"BŁĄD: {str(e)}")
        finally:
            self.komunikacja.sygnal_zakonczono.emit()

    def wypelnij_tabele_pozycjami(self, dane):
        self.odczytane_dane_ai = dane
        self.zaladuj_wszystkie_bazy()
        konf = wczytaj_konfiguracje()
        uzywaj_bazy = konf.get("uzywaj_bazy_towarowej", True)

        pozycje = dane.get("pozycje", [])

        self.tabela.blockSignals(True)
        self.tabela.setRowCount(0)
        for r, poz in enumerate(pozycje):
            nazwa = str(poz.get("nazwa", "")).strip()
            kod_dostawcy = str(poz.get("kod_dostawcy", "")).strip()
            ilosc = oczysc_liczbe(poz.get("ilosc"), "1")
            cena = oczysc_liczbe(poz.get("cena"), "0.00")
            vat = oczysc_vat(poz.get("vat"))

            kod_z_bazy = ""
            if uzywaj_bazy:
                if kod_dostawcy:
                    kod_z_bazy = self.baza_mapowan.get(kod_dostawcy.upper(), "")

                if not kod_z_bazy and nazwa:
                    kod_z_bazy = znajdz_kod_fuzzy(nazwa, self.baza_mapowan)

            self.tabela.insertRow(r)

            item_nazwa = QTableWidgetItem(nazwa)
            item_kod_dostawcy = QTableWidgetItem(kod_dostawcy)
            item_kod_dostawcy.setToolTip("Kod towaru / CN / EAN z dokumentu")
            
            item_kod = QTableWidgetItem(kod_z_bazy if kod_z_bazy else "0")
            item_ilosc = QTableWidgetItem(ilosc)
            item_cena = QTableWidgetItem(cena)
            item_vat = QTableWidgetItem(vat)

            if kod_z_bazy and kod_z_bazy != "0":
                item_kod.setBackground(QColor(16, 75, 36))
            else:
                item_kod.setBackground(QColor(95, 25, 25))

            self.tabela.setItem(r, 0, item_nazwa)
            self.tabela.setItem(r, 1, item_kod_dostawcy)
            self.tabela.setItem(r, 2, item_kod)
            self.tabela.setItem(r, 3, item_ilosc)
            self.tabela.setItem(r, 4, item_cena)
            self.tabela.setItem(r, 5, item_vat)

        self.tabela.blockSignals(False)
        self.przelicz_walidacje_sumy()
        self.btn_zapisz_edi.setEnabled(True)

    def zapisz_finalny_plik_edi(self):
        if not self.odczytane_dane_ai and self.tabela.rowCount() == 0:
            return

        nowe_kody = 0
        wiersze = self.tabela.rowCount()

        poprawne_linie = []
        for r in range(wiersze):
            item_n = self.tabela.item(r, 0)
            item_k = self.tabela.item(r, 2)
            if not item_n:
                continue

            nazwa = item_n.text().strip().replace("{", "").replace("}", "")
            if not nazwa or nazwa == "NOWA POZYCJA":
                continue

            kod = (item_k.text().strip() if item_k else "") or "0"
            ilosc = oczysc_liczbe(self.tabela.item(r, 3).text() if self.tabela.item(r, 3) else "1", "1")
            cena = oczysc_liczbe(self.tabela.item(r, 4).text() if self.tabela.item(r, 4) else "0.00", "0.00")
            vat = oczysc_vat(self.tabela.item(r, 5).text() if self.tabela.item(r, 5) else "0")

            if kod and kod != "0":
                mapa_reczna = wczytaj_baze_mapowan()
                if mapa_reczna.get(nazwa.upper()) != kod:
                    mapa_reczna[nazwa.upper()] = kod
                    zapisz_baze_mapowan(mapa_reczna)
                    nowe_kody += 1

            try:
                wartosc_obliczona = float(ilosc) * float(cena)
                wartosc_str = f"n{wartosc_obliczona:.2f}"
            except Exception:
                wartosc_str = "n0.00"

            cena_fmt = f"n{cena}" if not str(cena).startswith("n") else str(cena)
            linia = f"Linia:Nazwa{{{nazwa}}}Kod{{{kod}}}Vat{{{vat}}}Jm{{kg}}Ilosc{{{ilosc}}}Cena{{{cena_fmt}}}Wartosc{{{wartosc_str}}}"
            poprawne_linie.append(linia)

        if nowe_kody > 0:
            self.zaladuj_wszystkie_bazy()
            self.log(f"Zapisano {nowe_kody} nowych powiązań do bazy podręcznej.")

        konf = wczytaj_konfiguracje()
        katalog = konf.get("katalog_zapisu", os.getcwd())
        os.makedirs(katalog, exist_ok=True)

        dane_dok = self.odczytane_dane_ai or {}
        nr_dok = dane_dok.get("nr", "faktura")
        data_dok = dane_dok.get("data", datetime.now().strftime("%d.%m.%Y"))
        nip_dok = dane_dok.get("nip", "")

        nr_clean = "".join(c for c in str(nr_dok) if c.isalnum() or c in "-_")
        plik_edi = os.path.join(katalog, f"PZ_{nr_clean}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

        linie_edi = [
            "TypPolskichLiter:LA",
            "TypDok:PZ",
            f"NrDok:{nr_dok}",
            f"Data:{data_dok}",
            "Magazyn:MAGAZYN",
            f"NIPWystawcy:{nip_dok}",
            f"IloscLinii:{len(poprawne_linie)}"
        ] + poprawne_linie

        with open(plik_edi, "w", encoding="windows-1250", errors="replace") as f:
            f.write("\n".join(linie_edi) + "\n")

        QMessageBox.information(
            self, "Sukces", 
            f"Gotowy plik PZ został zapisany:\n{plik_edi}\n\nIlość pozycji: {len(poprawne_linie)}"
        )
        self.log(f"✅ Zapisano plik EDI ({len(poprawne_linie)} pozycji): {os.path.basename(plik_edi)}")


if __name__ == "__main__":
    if sys.platform == "win32":
        myappid = "zizi.ocrlmm.edi_converter.2.5"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = QApplication(sys.argv)
    app.setWindowIcon(wygeneruj_ikone_aplikacji())

    splash = CyberSplashScreen()
    splash.show()
    app.processEvents()

    for pozycja in range(40, 455, 8):
        splash.odswiez_klatke(pozycja)
        app.processEvents()
        time.sleep(0.01)

    okno = OcrLmmMainWindow()
    splash.finish(okno)
    okno.show()

    sys.exit(app.exec())
