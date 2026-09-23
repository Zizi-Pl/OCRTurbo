# ocrTurbo 📱📄

[![Platform: Android](https://img.shields.io/badge/Platform-Android-3DDC84?logo=android&logoColor=white)](#funkcjonalności)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](#budowanie-wersji-desktopowej-windows)
[![Framework: Flet](https://img.shields.io/badge/Framework-Flet-00BCD4?logo=flutter&logoColor=white)](#architektura-interfejsu)
[![AI: Google Gemini / LM Studio](https://img.shields.io/badge/AI-Gemini%20%7C%20LM%20Studio-FF6F00?logo=google&logoColor=white)](#silnik-ocr-i-sztuczna-inteligencja)
[![Integration: PC-Market EDI](https://img.shields.io/badge/Integration-PC--Market%20EDI-4CAF50)](#integracja-z-pc-market)

Aplikacja mobilno-desktopowa przeznaczona do automatycznego odczytu faktur dostawczych i specyfikacji towarowych (branża spożywcza: wędliny, mięso, nabiał, pieczywo), weryfikacji pozycji z lokalną bazą towarową oraz generowania plików wymiany danych EDI dla systemu **PC-Market**.

---

## 📑 Spis treści
- [Główne moduły](#główne-moduły)
- [Architektura interfejsu](#architektura-interfejsu)
- [Silnik OCR i sztuczna inteligencja](#silnik-ocr-i-sztuczna-inteligencja)
- [Integracja z PC-Market](#integracja-z-pc-market)
- [Budowanie aplikacji](#budowanie-aplikacji)
  - [Wersja Android (APK)](#budowanie-wersji-android-apk)
  - [Wersja Desktopowa (Windows)](#budowanie-wersji-desktopowej-windows)
- [Wymagania i uruchomienie](#wymagania-i-uruchomienie)

---

## 🚀 Główne moduły

### 1. Faktura / PZ (Dla PC-Market)
- Odczyt pełnych danych nagłówkowych (numer faktury, daty, dane i NIP kontrahenta).
- Automatyczne parsowanie pozycji tabelarycznych: nazwa, waga/ilość, jednostka miary (`kg`, `szt`, `op`), ceny jednostkowe netto, stawki VAT oraz sumy kontrolne.
- Inteligentne dopasowywanie kodów PLU / EAN na podstawie bazy towarowej oraz reguł użytkownika.
- Weryfikacja sum i różnic netto przed zatwierdzeniem.

### 2. Odczyt Dokumentu (Układ 1:1)
- Przepisywanie pism, specyfikacji i umów z zachowaniem oryginalnego układu przestrzennego, wcięć oraz kolumn.
- Wbudowany edytor z opcją kopiowania do schowka oraz eksportu do pliku tekstowego `.txt`.

### 3. Szybki Skaner Graficzny (Offline)
- Płynne kadrowanie dotykowe z możliwością przesuwania całej strefy roboczej środkiem lub chwytania za narożniki.
- Filtry przetwarzania obrazu: **B&W (High Contrast)**, **Skala szarości**, **Wyostrzanie**.
- Pełna historia operacji z możliwością cofania kroków (`Undo`) oraz odwracania filtrów.
- Niezależny, przewijalny panel narzędziowy zoptymalizowany pod ekrany dotykowe.

---

## 🛠 Architektura interfejsu

- **Silnik UI:** [Flet](https://flet.dev/) (oparty na Google Flutter).
- **Zarządzanie gestami:** Zoptymalizowana strefa dotykowa (`GestureDetector`) z wyłączonym nadrzędnym scrollem ekranu w widoku skanera, eliminująca opóźnienia i konflikty gestów na Androidzie.
- **RWD (Responsive Web Design):** Okna dialogowe weryfikacji i edycji pozycji dostosowane do pełnej szerokości ekranów smartfonów (`ft.Padding`, elastyczne kontenery).

---

## 🧠 Silnik OCR i sztuczna inteligencja

Aplikacja wspiera hybrydowe przetwarzanie obrazu:
- **Chmura:** Google Gemini API (`gemini-2.5-flash`) z wymuszonym schematem JSON.
- **Lokalnie (Offline/LAN):** Serwer [LM Studio](https://lmstudio.ai/) z modelami wizyjnymi (np. Qwen-VL) i obsługą automatycznego wybudzania stacji roboczej przez **Wake-on-LAN (WoL)**.

---

## 💾 Integracja z PC-Market

- Eksport gotowych dokumentów magazynowych do formatu tekstowego **EDI (windows-1250)** akceptowanego przez PC-Market.
- Moduł wyszukiwarki towarów w locie przeszukujący pliki bazy PC-Market.
- Zapis powiązań nazw dostawcy z wewnętrznymi indeksami magazynu.

---

## 📦 Budowanie aplikacji

### Budowanie wersji Android (APK)
Do zachowania możliwości aktualizacji zainstalowanej aplikacji bez konieczności odinstalowywania wymagane jest stałe użycie tego samego pliku keystore oraz podbijanie numeru kompilacji:

## 📦 Wymagania środowiskowe i użyte biblioteki

Do uruchomienia i kompilacji projektu wymagane jest środowisko **Python >= 3.11**.

### 📚 Kluczowe zależności i ich zastosowanie w aplikacji

| Biblioteka | Wersja | Rola w projekcie |
| :--- | :--- | :--- |
| **`flet`** | `0.85.3` | Główny silnik interfejsu graficznego (UI) oparty na silniku Flutter. |
| **`flet-camera`** | najnowsza | Natywna obsługa modułu aparatu fotograficznego na urządzeniach mobilnych (Android). |
| **`httpx`** | najnowsza | Asynchroniczny klient HTTP do zapytań API (Google Gemini oraz lokalne LM Studio). |
| **`pillow`** (PIL) | najnowsza | Kompresja, obracanie, nakładanie filtrów kontrastowych i precyzyjne kadrowanie pikseli. |
| **`python-docx`** | najnowsza | Eksport rozpoznanego tekstu i układów tabelarycznych do formatu Microsoft Word (`.docx`). |
| **`openpyxl`** | najnowsza | Generowanie i formatowanie arkuszy kalkulacyjnych Microsoft Excel (`.xlsx`) z danymi liczbowymi. |
| **`thefuzz`** | najnowsza | Algorytmy wyszukiwania rozmytego (fuzzy matching) do automatycznego łączenia nazw towarów z bazą PC-Market. |

---

### ⚙️ Instalacja środowiska deweloperskiego

1. Sklonuj repozytorium na dysk lokalny:
```bash
git clone https://github.com/Zizi-Pl/OCRTurbo.git
cd OCRTurbo
