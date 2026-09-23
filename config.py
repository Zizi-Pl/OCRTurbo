import os
import json
import copy

# Katalog roboczy aplikacji (obsługa storage Androida oraz lokalnego katalogu na PC)
KATALOG_DANYCH = os.getenv("FLET_APP_STORAGE_DATA", os.getcwd())
os.makedirs(KATALOG_DANYCH, exist_ok=True)

# Nazwy plików systemowych
CONFIG_FILE = os.path.join(KATALOG_DANYCH, "ocrlmm_mobile_config.json")
DOMYSLNA_BAZA_FILE = os.path.join(KATALOG_DANYCH, "NOWA_BAZA.txt")
MAPA_FILE = os.path.join(KATALOG_DANYCH, "mapowania_towarow.json")

# Domyślny słownik konfiguracyjny
DOMYSLNA_KONFIGURACJA = {
    "wol_mac": "2C:F0:5D:E4:8E:85",
    "use_cloud": True,
    "use_db_matching": True,
    "baza_file_path": DOMYSLNA_BAZA_FILE,
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "local_ip": "192.168.1.154",
    "local_port": "1234",
    "local_model": "qwen3.5-9b",
    "local_models_list": [
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
    """Zwraca zweryfikowaną ścieżkę do pliku bazy towarowej PC-Market."""
    sciezka = konf.get("baza_file_path", DOMYSLNA_BAZA_FILE)
    if os.path.exists(sciezka):
        return sciezka
    sciezka_lokalna = os.path.join(os.getcwd(), "WĘDLINA.txt")
    if os.path.exists(sciezka_lokalna):
        return sciezka_lokalna
    return sciezka
