import os
import json
import copy

# Katalog roboczy aplikacji (obsługa storage Androida oraz lokalnego katalogu na PC)
KATALOG_DANYCH = os.getenv("FLET_APP_STORAGE_DATA", os.getcwd())
os.makedirs(KATALOG_DANYCH, exist_ok=True)

# Nazwy plików systemowych
CONFIG_FILE = os.path.join(KATALOG_DANYCH, "ocrlmm_mobile_config.json")
KARTOTEKA_FILE = os.path.join(KATALOG_DANYCH, "kartoteka_towarowa.json")
ALIASY_FILE = os.path.join(KATALOG_DANYCH, "aliasy_ocr.json")

# Ścieżki wstecznej kompatybilności
DOMYSLNA_BAZA_FILE = os.path.join(KATALOG_DANYCH, "NOWA_BAZA.txt")
MAPA_FILE = os.path.join(KATALOG_DANYCH, "mapowania_towarow.json")

# Domyślny słownik konfiguracyjny
DOMYSLNA_KONFIGURACJA = {
    "wol_mac": "2C:F0:5D:E4:8E:85",
    "use_cloud": True,
    "use_db_matching": True,
    "baza_file_path": KARTOTEKA_FILE,
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "local_ip": "192.168.1.154",
    "local_port": "1234",
    "local_model": "qwen3-vl-8b-instruct",
    "local_models_list": [
        "qwen3-vl-8b-instruct",
        "qwen/qwen3-vl-8b-instruct",
        "qwen3-vl-4b-instruct",
        "qwen3.5-9b"
    ],
    "local_api_key": "",
    "image_resolution": 1800
}

PUSTY_OBRAZ = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


def wczytaj_konfiguracje() -> dict:
    """Wczytuje konfigurację z pliku JSON lub zwraca domyślną."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                dane = json.load(f)
                konf = copy.deepcopy(DOMYSLNA_KONFIGURACJA)
                konf.update(dane)
                return konf
        except Exception:
            return copy.deepcopy(DOMYSLNA_KONFIGURACJA)
    return copy.deepcopy(DOMYSLNA_KONFIGURACJA)


def zapisz_konfiguracje(konf: dict) -> None:
    """Zapisuje bieżący słownik konfiguracji do pliku JSON."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(konf, f, indent=2)
    except Exception as e:
        print(f"Błąd zapisu konfiguracji: {e}")


def pobierz_aktualna_sciezke_bazy(konf: dict) -> str:
    """
    Zwraca zweryfikowaną ścieżkę do bazy towarowej.
    Priorytet:
    1. Ścieżka zapisana w konfiguracji użytkownika (jeśli istnieje)
    2. Główna kartoteka JSON (kartoteka_towarowa.json)
    3. Starsze pliki TXT (NOWA_BAZA.txt / WĘDLINA.txt)
    """
    sciezka = konf.get("baza_file_path", "")
    if sciezka and os.path.exists(sciezka):
        return sciezka

    if os.path.exists(KARTOTEKA_FILE):
        return KARTOTEKA_FILE

    if os.path.exists(DOMYSLNA_BAZA_FILE):
        return DOMYSLNA_BAZA_FILE

    sciezka_lokalna = os.path.join(os.getcwd(), "WĘDLINA.txt")
    if os.path.exists(sciezka_lokalna):
        return sciezka_lokalna

    return KARTOTEKA_FILE
