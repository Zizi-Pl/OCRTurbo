# ocrTurbo 📱📄

[![Wersja: 2.4.0](https://img.shields.io/badge/Wersja-2.4.0-blue.svg)](#nowości-w-wersji-240)
[![Platform: Android](https://img.shields.io/badge/Platform-Android-3DDC84?logo=android&logoColor=white)](#budowanie-wersji-android-apk)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](#budowanie-wersji-desktopowej-windows)
[![Framework: Flet](https://img.shields.io/badge/Framework-Flet%200.85.3-00BCD4?logo=flutter&logoColor=white)](#architektura-interfejsu)
[![AI: Google Gemini / LM Studio](https://img.shields.io/badge/AI-Gemini%20%7C%20LM%20Studio-FF6F00?logo=google&logoColor=white)](#silnik-ocr-i-sztuczna-inteligencja)
[![Integration: PC-Market EDI](https://img.shields.io/badge/Integration-PC--Market%20EDI-4CAF50)](#integracja-z-pc-market)

Aplikacja mobilno-desktopowa przeznaczona do automatycznego odczytu faktur dostawczych i specyfikacji towarowych (branża spożywcza: wędliny, mięso, nabiał, pieczywo), weryfikacji pozycji z lokalną bazą towarową oraz generowania plików wymiany danych EDI dla systemu **PC-Market**.

---

## 📑 Spis treści
- [Nowości w wersji 2.4.0](#-nowości-w-wersji-240)
- [Główne moduły](#-główne-moduły)
- [Architektura projektu i opis plików](#-architektura-projektu-i-opis-plików)
- [Silnik OCR i sztuczna inteligencja](#-silnik-ocr-i-sztuczna-inteligencja)
- [Integracja z PC-Market](#-integracja-z-pc-market)
- [Wymagania środowiskowe i użyte biblioteki](#-wymagania-środowiskowe-i-użyte-biblioteki)
- [Budowanie aplikacji](#-budowanie-aplikacji)
  - [Wersja Android (APK)](#budowanie-wersji-android-apk)
  - [Wersja Desktopowa (Windows)](#budowanie-wersji-desktopowej-windows)

---

## 🌟 Nowości w wersji 2.4.0

- **Nowy edytor podglądu (`PełnyEdytorObrazu`):** Całkowita rezygnacja z niestabilnej kontrolki `InteractiveViewer` na rzecz natywnego, dwuosiowego przewijania (`ft.Row` + `ft.Column` ze scrollem `AUTO`). Pełna płynność i brak szarego ekranu na Windows 11 oraz urządzeniach z Androidem.
- **Dopasowanie do pasków systemowych Androida:** Zwiększony dolny margines (48 px) skutecznie unoszący dolny pasek narzędzi ponad systemowy pasek nawigacyjny z trzema przyciskami.
- **Dolna belka z ergonomicznymi ikonami:** Zastąpienie szerokich przycisków tekstowych dotykowymi kafelkami z ikonami (Anuluj, Cofnij, Kadruj/Zatwierdź, Wyślij), co zapobiega łamaniu wierszy i ucinkom na wąskich ekranach smartfonów.
- **Szybki reset zoomu:** Wskaźnik skali pomiędzy lupkami jest teraz klikalny – jedno dotknięcie przywraca natychmiast zoom bazowy `1.0x`.
- **Precyzyjne czyszczenie plików roboczych:** Rozszerzony mechanizm sprzątania katalogu roboczego o pliki eksportu Worda (`.docx`), Excela (`.xlsx`), unikalne pliki podglądu stemplowane czasem `preview_editor_*.jpg` oraz pliki transakcyjne `*.tmp`.
- **Czysta kompilacja mobilna:** Usunięcie zależności kompilowanych ze źródeł C/C++ (`python-Levenshtein`, `pypdfium2`), co zapewnia bezproblemowe budowanie paczek APK przez GitHub Actions z silnikiem `serious-python`.

---

## 🚀 Główne moduły

### 1. Faktura / PZ (Dla PC-Market)
- Odczyt pełnych danych nagłówkowych (numer faktury, daty wystawienia/sprzedaży, dane i NIP kontrahenta).
- Automatyczne parsowanie pozycji tabelarycznych: nazwa, waga/ilość, jednostka miary (`kg`, `szt`, `op`), ceny jednostkowe netto, stawki VAT oraz sumy kontrolne.
- Inteligentne dopasowywanie kodów PLU / EAN na podstawie bazy towarowej oraz wyuczonych reguł i aliasów użytkownika.
- Weryfikacja sum i różnic netto przed zatwierdzeniem i wygenerowaniem pliku magazynowego.

### 2. Odczyt Dokumentu (Układ 1:1)
- Przepisywanie pism, specyfikacji i umów z zachowaniem oryginalnego układu przestrzennego, wcięć oraz kolumn.
- Wbudowany edytor z opcją kopiowania do schowka oraz natychmiastowego eksportu do formatów `.txt`, `.docx` (Microsoft Word) i `.xlsx` (Microsoft Excel).

### 3. Szybki Skaner Graficzny (Offline)
- Płynne kadrowanie dotykowe z możliwością przesuwania całej strefy roboczej środkiem lub chwytania za 4 niezależne narożniki.
- Filtry przetwarzania obrazu w locie: **B&W (High Contrast)**, **Skala szarości**, **Wyostrzanie**.
- Pełna historia operacji z możliwością cofania kroków (`Undo`) oraz odwracania filtrów.
- Niezależny, przewijalny panel narzędziowy zoptymalizowany pod dotyk.

---

## 📂 Architektura projektu i opis plików

Struktura projektu została podzielona modularnie, rozdzielając logikę przetwarzania danych, interfejs graficzny i komunikację z modelami AI:

```text
OCRTurbo/
│
├── main.py                 # Punkt wejścia aplikacji, konfiguracja okna i cyklu życia
├── config.py               # Konfiguracja, ścieżki systemowe, profile i persystencja JSON
├── core.py                 # Silnik biznesowy, parsowanie EDI, fuzzy matching, czyszczenie
├── image_processor.py      # Przetwarzanie obrazu w Pillow (obroty, filtry, kadrowanie)
├── image_viewer.py         # Pełnoekranowy edytor podglądu, zoom, kadrowanie i maski
├── converter.py            # Konwersja formatów wejściowych (schowek, PDF, zrzuty)
├── ai_service.py           # Integracja z Google Gemini API oraz lokalnym LM Studio
│
├── views.py                # Menedżer widoków aplikacji (ViewsManager - nawigacja)
├── ui.py                   # Menedżer okien dialogowych, powiadomień i pickerów (UIManager)
├── module_pz.py            # Logika i interfejs modułu Faktura / Przyjęcie Zewnętrzne (PZ)
├── module_doc.py           # Logika i interfejs modułu Dokument (układ 1:1, Word, Excel)
└── module_scan.py          # Logika i interfejs modułu Szybki Skaner
```

### 🔍 Szczegółowy zakres odpowiedzialności plików:

#### `main.py`
- Inicjalizuje aplikację Flet, konfiguruje motyw ciemny (`DARK`) oraz zerowy padding okna.
- Rejestruje systemowy serwis udostępniania (`ft.Share`).
- Inicjalizuje instancje `FilePicker` (niezbędne w nowszych wersjach Flet poza `page.overlay`).
- Monitoruje zdarzenie zmiany rozmiaru okna (`on_resized`), dynamicznie dopasowując kadr edytora obrazów bez zniekształcania proporcji.
- Przed startem automatycznie uruchamia procedurę sprzątania pozostałości po poprzednich sesjach roboczych.

#### `config.py`
- Zarządza ścieżkami katalogu roboczego (`KATALOG_DANYCH`) odpowiednio dla systemów Windows oraz Android.
- Wczytuje i zapisuje konfigurację aplikacji (`ocrlmm_mobile_config.json`): adresy IP LM Studio, klucze API Gemini, parametry Wake-on-LAN (MAC adres) oraz domyślne profile kontrastu/ostrości.

#### `core.py`
- **Fuzzy matching towarów:** Dwustopniowy algorytm łączenia pozycji z faktury z bazą PC-Market (`kartoteka_towarowa.json`). Błyskawiczne dopasowanie 1:1 słownikiem w RAM + rozmyte dopasowanie tokenowe (`thefuzz`) z progiem podobieństwa.
- **Generowanie EDI:** Tworzy pliki wymiany magazynowej w standardzie kodowania `windows-1250` z zachowaniem specyficznych dla PC-Market nagłówków, kodów stawek VAT i sum kontrolnych.
- **Sprzątanie (`wyczysc_pliki_robocze`):** Usuwa pliki tymczasowe zdjęć (`img_*`, `rot_*`, `crop_*`, `flt_*`, `preview_editor*`), dokumenty wyjściowe (`dok_*.docx`, `dok_*.xlsx`, `dok_*.txt`), pliki wymiany oraz pliki transakcyjne `.tmp`.

#### `image_processor.py`
- Operacje graficzne niskiego poziomu za pomocą biblioteki Pillow (PIL).
- Skalowanie i tworzenie lekkich kopii podglądowych w celu zachowania maksymalnej płynności interfejsu.
- Precyzyjne wycinanie fragmentów kadrów na podstawie procentowych koordynatów z interfejsu.
- Filtry korekcyjne (kontrast, jasność, ostrość, progi czerni/bieli dla trybu dokumentowego).

#### `image_viewer.py`
- Komponent `PełnyEdytorObrazu` – pełnoekranowy widok manipulacji dokumentem przed wysłaniem do analizy.
- Dwuosiowy kontener ze scrollem (`AUTO`), gwarantujący stabilne powiększanie bez błędów renderowania.
- Własna implementacja gestów kadrowania (`GestureDetector`) z 4 narożnymi uchwytami i strefą przeciągania całego zaznaczenia.
- Pasek kontroli zoomu z klikalnym napisem resetującym skalę do `1.0x` oraz dolna belka z dużymi przyciskami dotykowymi.

#### `converter.py`
- Normalizacja plików graficznych wprowadzanych do programu.
- Obsługa wklejania obrazów bezpośrednio ze schowka systemowego (Windows/Android).
- Bezpieczny mechanizm konwersji stron PDF na pliki graficzne JPG (jeśli w środowisku dostępna jest biblioteka renderująca).

#### `ai_service.py`
- Obsługa hybrydowego backendu sztucznej inteligencji:
  - **Google Gemini API:** Obsługa modeli wizyjnych z wymuszeniem schematu odpowiedzi JSON (`response_schema`).
  - **Lokalne LM Studio:** Obsługa modeli typu Qwen-VL po protokole kompatybilnym z OpenAI API.
- Wysyłanie pakietów Magic Packet (Wake-on-LAN) do zdalnego uruchamiania stacji roboczej z modelami lokalnymi.

#### `views.py`, `ui.py` oraz moduły funkcyjne (`module_*.py`)
- **`views.py`:** Centralna nawigacja pomiędzy ekranami (Hub główny, Moduł PZ, Moduł Dokument, Skaner).
- **`ui.py`:** Obsługa wyskakujących okien dialogowych (ustawienia, mapowanie kodów towarowych, postęp OCR).
- **`module_pz.py`:** Tabela weryfikacji pozycji faktury, edycja cen, stawek VAT, ręczne przypisywanie towarów z bazy.
- **`module_doc.py`:** Odczyt struktury pism urzędowych, eksport do `.docx` i `.xlsx`.
- **`module_scan.py`:** Szybki notatnik graficzny i archiwizator dokumentów bez konieczności parsowania tekstu.

---

## 🧠 Silnik OCR i sztuczna inteligencja

Aplikacja wspiera hybrydowe przetwarzanie obrazu:
- **Chmura:** Google Gemini API (`gemini-2.5-flash`) z precyzyjnym wymuszeniem schematu JSON, co eliminuje halucynacje i błędy formatowania.
- **Lokalnie (Offline/LAN):** Serwer [LM Studio](https://lmstudio.ai/) z modelami wizyjnymi (np. Qwen-VL) i obsługą automatycznego wybudzania stacji roboczej przez **Wake-on-LAN (WoL)**.

---

## 💾 Integracja z PC-Market

- Eksport gotowych dokumentów magazynowych do formatu tekstowego **EDI (windows-1250)** akceptowanego przez PC-Market.
- Moduł wyszukiwarki towarów w locie przeszukujący pliki bazy PC-Market.
- Zapis powiązań nazw dostawcy z wewnętrznymi indeksami magazynu (`aliasy_ocr.json`).

---

## 📦 Wymagania środowiskowe i użyte biblioteki

Do uruchomienia i kompilacji projektu wymagane jest środowisko **Python >= 3.11**.

### 📚 Kluczowe zależności i ich zastosowanie w aplikacji

| Biblioteka | Wersja | Rola w projekcie |
| :--- | :--- | :--- |
| **`flet`** | `0.85.3` | Główny silnik interfejsu graficznego (UI) oparty na Flutterze. |
| **`flet-camera`** | najnowsza | Natywna obsługa modułu aparatu fotograficznego na urządzeniach mobilnych (Android). |
| **`httpx`** | najnowsza | Asynchroniczny klient HTTP do zapytań API (Google Gemini oraz lokalne LM Studio). |
| **`pillow`** (PIL) | najnowsza | Kompresja, obracanie, nakładanie filtrów kontrastowych i precyzyjne kadrowanie pikseli. |
| **`python-docx`** | najnowsza | Eksport rozpoznanego tekstu i układów tabelarycznych do formatu Microsoft Word (`.docx`). |
| **`openpyxl`** | najnowsza | Generowanie i formatowanie arkuszy kalkulacyjnych Microsoft Excel (`.xlsx`). |
| **`thefuzz`** | najnowsza | Algorytmy wyszukiwania rozmytego (fuzzy matching w czystym Pythonie) do łączenia nazw towarów z bazą PC-Market. |

---

## 📦 Budowanie aplikacji

### Budowanie wersji Android (APK)

Projekt wykorzystuje narzędzie Flet CLI z silnikiem `serious-python`. Aby zachować możliwość aktualizacji zainstalowanej aplikacji bez konieczności jej odinstalowywania, należy zachować stały plik klucza (`keystore`) oraz sukcesywnie podbijać wersję w pliku konfiguracyjnym:

1. Konfiguracja pliku `pyproject.toml`:
```toml
[project]
name = "OCRTurbo"
version = "2.4.0"
description = "Skaner PZ do EDI i inne"
requires-python = ">=3.11"
dependencies = [
    "flet==0.85.3",
    "flet-camera",
    "httpx",
    "pillow",
    "thefuzz",
    "python-docx",
    "openpyxl",
]

[tool.flet]
org = "com.ocrlmm"
product = "ocrLmm"
company = "ocrLmm"
copyright = "Copyright (C) 2026"

[tool.flet.app]
path = "."

[tool.flet.android.permission]
"android.permission.INTERNET" = true
"android.permission.ACCESS_NETWORK_STATE" = true
"android.permission.CAMERA" = true
"android.permission.READ_MEDIA_IMAGES" = true
"android.permission.READ_EXTERNAL_STORAGE" = true
"android.permission.WRITE_EXTERNAL_STORAGE" = true
```

2. Kompilacja pakietu APK:
```bash
flet build apk --release
```

### Budowanie wersji Desktopowej (Windows)

Aplikację można spakować do samodzielnego pliku wykonywalnego `.exe` przy użyciu Fleta lub PyInstallera:

```bash
flet build windows
```
lub za pomocą PyInstallera:
```bash
pyinstaller --noconsole --onefile --name "ocrTurbo" main.py
```
