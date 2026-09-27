import os
import io
import base64
from datetime import datetime
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
import tempfile

import config


def konwertuj_do_rgb(img: Image.Image) -> Image.Image:
    """
    Bezpiecznie przekształca każdy obraz (RGBA, LA, P z przezroczystością) na czysty RGB.
    Przezroczyste tło (np. zrzuty ekranu, grafiki z WhatsApp) zostaje wypełnione bielą.
    """
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        tlo = Image.new("RGB", img.size, (255, 255, 255))
        rgba_img = img.convert("RGBA")
        tlo.paste(rgba_img, mask=rgba_img.split()[3])
        return tlo
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def przygotuj_obraz_wejsciowy(sciezka_zrodlowa: str, prefiks: str = "img_in") -> str:
    """
    Normalizuje dowolny plik graficzny (aparat, galeria, WhatsApp, PNG, WebP):
    - Wyrównuje fizycznie orientację EXIF
    - Wypełnia przezroczystości białym tłem
    - Zapisuje jednolity, roboczy plik JPEG w katalogu aplikacji
    """
    nowa_sciezka = os.path.join(
        config.KATALOG_DANYCH,
        f"{prefiks}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    )
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        img_rgb = konwertuj_do_rgb(img)
        img_rgb.save(nowa_sciezka, format="JPEG", quality=95)

    return nowa_sciezka


def obroc_obraz(sciezka_zrodlowa: str, kat: int, prefiks: str = "rot") -> str:
    """Obraca fizycznie obraz o zadany kąt (np. 90 lub -90 stopni)."""
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        obrocony = img.rotate(kat, expand=True)
        nowa_sciezka = os.path.join(
            config.KATALOG_DANYCH,
            f"{prefiks}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        )
        konwertuj_do_rgb(obrocony).save(nowa_sciezka, format="JPEG", quality=95)

    if sciezka_zrodlowa and os.path.exists(sciezka_zrodlowa):
        try:
            os.remove(sciezka_zrodlowa)
        except Exception:
            pass

    return nowa_sciezka


def kadruj_obraz(sciezka_zrodlowa: str, l_proc: float, t_proc: float,
                 r_proc: float, b_proc: float, prefiks: str = "crop") -> str:
    """Wycina kadr na podstawie procentowych wartości marginesów (lewo, góra, prawo, dół)."""
    nowa_sciezka = os.path.join(
        config.KATALOG_DANYCH,
        f"{prefiks}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    )
    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        l = max(0, int(w * (l_proc / 100.0)))
        t = max(0, int(h * (t_proc / 100.0)))
        r = min(w, int(w * (1.0 - (r_proc / 100.0))))
        b = min(h, int(h * (1.0 - (b_proc / 100.0))))

        if r > l and b > t:
            c = img.crop((l, t, r, b))
        else:
            c = img

        konwertuj_do_rgb(c).save(nowa_sciezka, format="JPEG", quality=95)

    return nowa_sciezka


def zastosuj_korekcje(
    sciezka_zrodlowa: str,
    kontrast: float = 1.0,
    jasnosc: float = 1.0,
    ostrosc: float = 1.0,
    tryb_koloru: str = "kolor",
    prog_bw: int = 135,
    prefiks: str = "adj"
) -> str:
    """
    Aplikuje parametry suwaków na żywo:
    - kontrast: float (1.0 = brak zmian, zakres np. 0.5 - 2.2)
    - jasnosc: float (1.0 = brak zmian, zakres np. 0.5 - 1.6)
    - ostrosc: float (1.0 = brak zmian, zakres 1.0 - 3.5, podbita maską splotową)
    - tryb_koloru: 'kolor', 'szary', 'bw'
    - prog_bw: próg binaryzacji dla trybu 'bw' (0 - 255)
    """
    nowa_sciezka = os.path.join(
        config.KATALOG_DANYCH,
        f"{prefiks}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    )

    with Image.open(sciezka_zrodlowa) as img:
        img = ImageOps.exif_transpose(img)
        wynik = konwertuj_do_rgb(img)

        # 1. Tryb koloru
        if tryb_koloru == "szary":
            wynik = ImageOps.grayscale(wynik).convert("RGB")
        elif tryb_koloru == "bw":
            szary = ImageOps.grayscale(wynik)
            wynik = szary.point(lambda p: 255 if p > prog_bw else 0).convert("RGB")

        # 2. Jasność
        if jasnosc != 1.0:
            wynik = ImageEnhance.Brightness(wynik).enhance(jasnosc)

        # 3. Kontrast
        if kontrast != 1.0:
            wynik = ImageEnhance.Contrast(wynik).enhance(kontrast)

        # 4. Ostrość (hybrydowa maska wyostrzająca pod drobny druk)
        if ostrosc > 1.0:
            procent_maski = int((ostrosc - 1.0) * 140)
            wynik = wynik.filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=procent_maski, threshold=2)
            )
            mnoznik_sharp = 1.0 + (ostrosc - 1.0) * 0.9
            wynik = ImageEnhance.Sharpness(wynik).enhance(mnoznik_sharp)

        wynik.save(nowa_sciezka, format="JPEG", quality=95)

    return nowa_sciezka


def pobierz_wymiary_obrazu(sciezka_pliku: str) -> tuple[int, int]:
    """Zwraca wymiary (szerokość, wysokość) pliku z uwzględnieniem obrotu EXIF."""
    try:
        with Image.open(sciezka_pliku) as img:
            img = ImageOps.exif_transpose(img)
            return img.size
    except Exception:
        return 0, 0


def kompresuj_do_wysylki(sciezka_pliku: str, rozdzielczosc: int = 1800, jakosc: int = 92) -> str:
    """
    Przygotowuje zatwierdzony kadr do wysłania do modelu AI:
    - Skaluje metodą Lanczos z zachowaniem proporcji
    - Zapisuje do bufora JPEG o zadanej jakości
    - Zwraca ciąg znaków Base64 bez narzucania sztucznych filtrów
    """
    with Image.open(sciezka_pliku) as img:
        img = ImageOps.exif_transpose(img)
        img = konwertuj_do_rgb(img)

        img.thumbnail((rozdzielczosc, rozdzielczosc), Image.Resampling.LANCZOS)

        bufor = io.BytesIO()
        img.save(bufor, format="JPEG", quality=jakosc)
        return base64.b64encode(bufor.getvalue()).decode("utf-8")


def przygotuj_kopie_podgladowa(sciezka_zrodlowa: str, max_bok: int = 1000) -> str:
    """Tworzy zoptymalizowaną, lekką kopię obrazu do natychmiastowego podglądu suwaków."""
    if not os.path.exists(sciezka_zrodlowa):
        return sciezka_zrodlowa

    katalog = getattr(config, "KATALOG_DANYCH", getattr(config, "KATALOG_ROBOCZY", tempfile.gettempdir()))
    sciezka_podgladu = os.path.join(katalog, "preview_editor.jpg")
    try:
        with Image.open(sciezka_zrodlowa) as img:
            img = ImageOps.exif_transpose(img)
            img = konwertuj_do_rgb(img)
            img.thumbnail((max_bok, max_bok), Image.Resampling.BILINEAR)
            img.save(sciezka_podgladu, "JPEG", quality=80)
        return sciezka_podgladu
    except Exception:
        return sciezka_zrodlowa
