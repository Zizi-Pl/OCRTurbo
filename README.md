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
- [Wymagania środowiskowe i zależności](#-wymagania-środowiskowe-i-użyte-biblioteki)
- [Budowanie aplikacji](#-budowanie-aplikacji)
  - [Wersja Android (APK)](#budowanie-wersji-android-apk)
  - [Wersja Desktopowa (Windows)](#budowanie-wersji-desktopowej-windows)

---

## 🌟 Nowości w wersji 2.4.0

- **Nowy edytor podglądu (`PełnyEdytorObrazu`):** Całkowita rezygnacja z niestabilnej kontrolki `InteractiveViewer` na rzecz natywnego, dwuosiowego przewijania (`ft.Row` + `ft.Column` ze scrollem `AUTO`). Pełna płynność na Windows 11 i urządzeniach z Androidem.
- **Dopasowanie do pasków systemowych Androida:** Zwiększony dolny margines chroniący przyciski przed przysłonięciem przez systemowy pasek nawigacyjny z trzema przyciskami.
- **Dolna belka z ikonami:** Zastąpienie szerokich przycisków tekstowych poręcznymi ikonami dotykowymi (Anuluj, Cofnij, Kadruj, Wyślij), co zapobiega łamaniu wierszy na wąskich ekranach.
- **Szybki reset zoomu:** Wskaźnik skali pomiędzy lupkami jest teraz klikalny – jedno dotknięcie przywraca natychmiast zoom bazowy `1.0x`.
- **Precyzyjne czyszczenie plików roboczych:** Rozszerzony mechanizm sprzątania katalogu roboczego o pliki eksportu Worda (`.docx`), Excela (`.xlsx`), unikalne pliki stemplowane czasem `preview_editor_*.jpg` oraz pliki transakcyjne `*.tmp`.
- **Czysta kompilacja mobilna:** Usunięcie zależności wymagających kompilatorów C/C++ (`python-Levenshtein`, `pypdfium2`), co zapewnia bezproblemowe budowanie paczek APK przez GitHub Actions.

---

## 🚀 Główne moduły

### 1. Faktura / PZ (Dla PC-Market)
- Odczyt pełnych danych nagłówkowych (numer faktury, daty, dane i NIP kontrahenta).
- Automatyczne parsowanie pozycji tabelarycznych: nazwa, waga/ilość, jednostka miary (`kg`, `szt`, `op`), ceny jednostkowe netto, stawki VAT oraz sumy kontrolne.
- Inteligentne dopasowywanie kodów PLU / EAN na podstawie bazy towarowej oraz reguł użytkownika.
- Weryfikacja sum i różnic netto przed zatwierdzeniem.

### 2. Odczyt Dokumentu (Układ 1:1)
- Przepisywanie pism, specyfikacji i umów z zachowaniem oryginalnego układu przestrzennego, wcięć oraz kolumn.
- Wbudowany edytor z opcją kopiowania do schowka oraz eksportu do formatów `.txt`, `.docx` (Word) i `.xlsx` (Excel).

### 3. Szybki Skaner Graficzny (Offline)
- Płynne kadrowanie dotykowe z możliwością przesuwania całej strefy roboczej środkiem lub chwytania za narożniki.
- Filtry przetwarzania obrazu: **B&W (High Contrast)**, **Skala szarości**, **Wyostrzanie**.
- Pełna historia operacji z możliwością cofania kroków (`Undo`) oraz ponawiania filtrów.
- Niezależny, przewijalny panel narzędziowy zoptymalizowany pod ekrany dotykowe.

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
