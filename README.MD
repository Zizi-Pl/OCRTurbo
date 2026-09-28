# ocrTurbo 📱📄

[![Wersja: 2.4.1](https://img.shields.io/badge/Wersja-2.4.1-blue.svg)](#nowości-w-wersji-241)
[![Platform: Android](https://img.shields.io/badge/Platform-Android-3DDC84?logo=android&logoColor=white)](#budowanie-wersji-android-apk)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](#budowanie-wersji-desktopowej-windows)
[![Framework: Flet](https://img.shields.io/badge/Framework-Flet%200.85.3-00BCD4?logo=flutter&logoColor=white)](#architektura-interfejsu)
[![AI: Google Gemini / LM Studio](https://img.shields.io/badge/AI-Gemini%20%7C%20LM%20Studio-FF6F00?logo=google&logoColor=white)](#silnik-ocr-i-sztuczna-inteligencja)
[![Integration: PC-Market EDI](https://img.shields.io/badge/Integration-PC--Market%20EDI-4CAF50)](#integracja-z-pc-market)

Aplikacja mobilno-desktopowa przeznaczona do automatycznego odczytu faktur dostawczych i specyfikacji towarowych (branża spożywcza: wędliny, mięso, nabiał, pieczywo), weryfikacji pozycji z lokalną bazą towarową oraz generowania plików wymiany danych EDI dla systemu **PC-Market**.

---

## 📑 Spis treści
- [Nowości w wersji 2.4.1](#-nowości-w-wersji-241)
- [Główne moduły](#-główne-moduły)
- [Architektura projektu i opis plików](#-architektura-projektu-i-opis-plików)
- [Silnik OCR i sztuczna inteligencja](#-silnik-ocr-i-sztuczna-inteligencja)
- [Integracja z PC-Market](#-integracja-z-pc-market)
- [Wymagania środowiskowe i użyte biblioteki](#-wymagania-środowiskowe-i-użyte-biblioteki)
- [Budowanie aplikacji](#-budowanie-aplikacji)
  - [Wersja Android (APK)](#budowanie-wersji-android-apk)
  - [Wersja Desktopowa (Windows)](#budowanie-wersji-desktopowej-windows)

---

## 🌟 Nowości w wersji 2.4.1

- **Pancerny bezpiecznik ilości pozycji:** Rozwiązanie problemu odrzucania linii przez PC-Market przy imporcie dokumentu EDI. Jeśli OCR nie rozpozna ilości lub zwróci wartość zerową/nieczytelną, system automatycznie wstawia bezpieczną wartość jednostkową (`1` dla `szt`/`op`, `1.0` dla `kg`) i oznacza pozycję ostrzeżeniem na liście weryfikacyjnej.
- **Kaskada awaryjna wyceny pozycji:** Zabezpieczenie przed zerową ceną zakupu w pliku wymiany:
  1. *Matematyka z faktury:* Automatyczne wyliczenie ceny jednostkowej z ilorazu `Wartość netto / Ilość`.
  2. *Cena z bazy PC-Market:* Pobranie ceny ewidencyjnej (`cena_ew`) z rekordu kartoteki towarowej.
  3. *Twardy bezpiecznik 1 grosza:* Podstawienie `0.01 zł` przy całkowitym braku danych na fakturze i w bazie, co gwarantuje bezbłędny import dokumentu w PC-Market bez wstrzymywania pracy.
- **Dynamiczne zarządzanie widocznością modułów (Role pracownik / administrator):** W oknie Ustawień dodano przełączniki (`ft.Switch`) pozwalające włączać i wyłączać kafelki modułów: **Faktura / PZ**, **Dokument (DOC)** oraz **Skaner**. Umożliwia to skonfigurowanie telefonu pracownika jako prostego skanera graficznego (z ukrytą bazą towarową i rozliczeniami PZ), zachowując pełny kombajn na urządzeniu administratora.
- **Odświeżenie ergonomii przycisku analizy PZ:** Główny przycisk startu analizy otrzymał czytelny, zielony kolor bazowy (`GREEN_800`), większy format (wysokość 52 px) oraz pogrubioną typografię pod kątem szybkiej obsługi jedną ręką w warunkach terenowych.
- **Nowy edytor podglądu (`PełnyEdytorObrazu`):** Całkowita rezygnacja z niestabilnej kontrolki `InteractiveViewer` na rzecz natywnego, dwuosiowego przewijania (`ft.Row` + `ft.Column` ze scrollem `AUTO`). Pełna płynność i brak szarego ekranu na Windows 11 oraz urządzeniach z Androidem.
- **Dopasowanie do pasków systemowych Androida:** Zwiększony dolny margines (48 px) skutecznie unoszący dolny pasek narzędzi ponad systemowy pasek nawigacyjny z trzema przyciskami.
- **Szybki reset zoomu:** Wskaźnik skali pomiędzy lupkami jest klikalny – jedno dotknięcie przywraca natychmiast zoom bazowy `1.0x`.
- **Precyzyjne czyszczenie plików roboczych:** Rozszerzony mechanizm sprzątania katalogu roboczego o pliki eksportu Worda (`.docx`), Excela (`.xlsx`), unikalne pliki podglądu stemplowane czasem `preview_editor_*.jpg` oraz pliki transakcyjne `*.tmp`.

---

## 🚀 Główne moduły

### 1. Faktura / PZ (Dla PC-Market)
- Odczyt pełnych danych nagłówkowych (numer faktury, daty wystawienia/sprzedaży, dane i NIP kontrahenta).
- Automatyczne parsowanie pozycji tabelarycznych: nazwa, waga/ilość, jednostka miary (`kg`, `szt`, `op`), ceny jednostkowe netto, stawki VAT oraz sumy kontrolne.
- Inteligentne dopasowywanie kodów PLU / EAN na podstawie bazy towarowej oraz wyuczonych reguł i aliasów użytkownika.
- Weryfikacja sum i różnic netto przed zatwierdzeniem i wygenerowaniem pliku magazynowego.
- Zabezpieczenie integralności pliku EDI przed brakującymi wartościami ilości i cen.

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
├── config.py               # Konfiguracja, ścieżki systemowe, flagi modułów i persystencja JSON
├── core.py                 # Silnik biznesowy, parsowanie EDI, fuzzy matching, bezpieczniki cen/ilości
├── image_processor.py      # Przetwarzanie obrazu w Pillow (obroty, filtry, kadrowanie)
├── image_viewer.py         # Pełnoekranowy edytor podglądu, zoom, kadrowanie i maski
├── converter.py            # Konwersja formatów wejściowych (schowek, PDF, zrzuty)
├── network.py              # Asynchroniczny klient HTTP (httpx), WoL oraz komunikacja z Gemini/LM Studio
│
├── views.py                # Menedżer widoków aplikacji (ViewsManager - nawigacja i widoczność kafelków)
├── ui.py                   # Menedżer okien dialogowych, Ustawień modułów, edycji pozycji i pickerów
├── module_pz.py            # Logika i interfejs modułu Faktura / Przyjęcie Zewnętrzne (PZ)
├── module_doc.py           # Logika i interfejs modułu Dokument (układ 1:1, Word, Excel)
└── module_scan.py          # Logika i interfejs modułu Szybki Skaner
