import io
import os
from datetime import datetime
from PIL import Image, ImageOps

import config


def _generuj_sciezke_wyjsciowa(prefiks: str = "img_in", rozszerzenie: str = ".jpg") -> str:
    """Generuje unikalną ścieżkę pliku w katalogu roboczym aplikacji."""
    katalog = getattr(config, "KATALOG_DANYCH", getattr(config, "KATALOG_ROBOCZY", os.getcwd()))
    nazwa_pliku = f"{prefiks}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{rozszerzenie}"
    return os.path.join(katalog, nazwa_pliku)


def konwertuj_obraz_do_rgb_jpeg(sciezka_lub_obraz, prefiks: str = "img_in") -> str:
    """
    Przyjmuje ścieżkę pliku lub obiekt PIL.Image (PNG, WebP, BMP, TIFF, JPEG).
    - Obsługuje kanał alfa/przezroczystość (wypełnia tło czystą bielą).
    - Wyrównuje fizyczną orientację EXIF (np. zdjęcia z telefonów).
    - Zapisuje ujednolicony plik roboczy JPEG o jakości 95%.
    """
    sciezka_wyjsciowa = _generuj_sciezke_wyjsciowa(prefiks=prefiks, rozszerzenie=".jpg")

    if isinstance(sciezka_lub_obraz, str):
        if not os.path.exists(sciezka_lub_obraz):
            raise FileNotFoundError(f"Plik źródłowy nie istnieje: {sciezka_lub_obraz}")
        img = Image.open(sciezka_lub_obraz)
    elif isinstance(sciezka_lub_obraz, Image.Image):
        img = sciezka_lub_obraz
    else:
        raise ValueError("Nieobsługiwany format danych wejściowych.")

    try:
        # 1. Wyrównanie orientacji EXIF (jeśli obecna)
        img = ImageOps.exif_transpose(img)

        # 2. Bezpieczna obsługa przezroczystości (PNG ze schowka Windows, zrzuty, ikony)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            tlo_biale = Image.new("RGB", img.size, (255, 255, 255))
            rgba_img = img.convert("RGBA")
            tlo_biale.paste(rgba_img, mask=rgba_img.split()[3])
            img_rgb = tlo_biale
        elif img.mode != "RGB":
            img_rgb = img.convert("RGB")
        else:
            img_rgb = img

        # 3. Zapis do roboczego pliku JPEG
        img_rgb.save(sciezka_wyjsciowa, format="JPEG", quality=95)
        return sciezka_wyjsciowa
    finally:
        if isinstance(sciezka_lub_obraz, str):
            img.close()


# Minimalny dłuższy bok osadzonej grafiki, aby uznać ją za skan całej strony
# (a nie np. logo w nagłówku faktury).
MIN_BOK_SKANU_PX = 900
# Ile znaków tekstu na stronie oznacza PDF wygenerowany przez program (nie skan).
MIN_ZNAKOW_TEKSTU = 80


def _renderuj_pdf_pypdfium2(sciezka_pdf: str, strony, dpi: int) -> list[str]:
    import pypdfium2 as pdfium

    wynik = []
    pdf = pdfium.PdfDocument(sciezka_pdf)
    try:
        scale = dpi / 72.0
        for nr in strony:
            if nr >= len(pdf):
                break
            pil_image = pdf[nr].render(scale=scale).to_pil()
            wynik.append(konwertuj_obraz_do_rgb_jpeg(pil_image, prefiks=f"img_pdf_p{nr+1}"))
    finally:
        pdf.close()
    return wynik


def _renderuj_pdf_fitz(sciezka_pdf: str, strony, dpi: int) -> list[str]:
    import fitz

    wynik = []
    doc = fitz.open(sciezka_pdf)
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for nr in strony:
            if nr >= len(doc):
                break
            pix = doc[nr].get_pixmap(matrix=mat, alpha=False)
            sciezka_wyjsciowa = _generuj_sciezke_wyjsciowa(prefiks=f"img_pdf_p{nr+1}")
            pix.save(sciezka_wyjsciowa)
            wynik.append(sciezka_wyjsciowa)
    finally:
        doc.close()
    return wynik


def _wyciagnij_skan_pypdf(sciezka_pdf: str, strony) -> list[str]:
    """Wyciąga NAJWIĘKSZĄ osadzoną grafikę ze strony (skan faktury).

    pypdf nie potrafi renderować stron, więc na Androidzie obsłużymy tylko PDF-y
    będące skanami. Dla PDF-ów wygenerowanych przez program fakturujący (tekst
    wektorowy + ewentualnie małe logo) zgłaszamy czytelny błąd zamiast wysyłać
    do OCR samo logo.
    """
    from pypdf import PdfReader

    wynik = []
    reader = PdfReader(sciezka_pdf)
    for nr in strony:
        if nr >= len(reader.pages):
            break
        page = reader.pages[nr]

        najwiekszy = None
        najwieksze_pole = 0
        for img_obj in page.images:
            try:
                pil_img = Image.open(io.BytesIO(img_obj.data))
                pil_img.load()
            except Exception as err:
                print(f"Błąd odczytu grafiki ze strony {nr+1}: {err}")
                continue
            pole = pil_img.width * pil_img.height
            if pole > najwieksze_pole:
                najwiekszy, najwieksze_pole = pil_img, pole

        ma_skan = najwiekszy is not None and max(najwiekszy.size) >= MIN_BOK_SKANU_PX
        if ma_skan:
            wynik.append(konwertuj_obraz_do_rgb_jpeg(najwiekszy, prefiks=f"img_pdf_p{nr+1}"))
            continue

        try:
            tekst = (page.extract_text() or "").strip()
        except Exception:
            tekst = ""
        if len(tekst) >= MIN_ZNAKOW_TEKSTU:
            raise ValueError(
                "Ten PDF został wygenerowany przez program (zawiera tekst, a nie skan), "
                "a na tym urządzeniu nie da się go zamienić na obraz.\n\n"
                "Otwórz PDF, zrób zrzut ekranu faktury i wybierz zrzut w aplikacji."
            )
        if najwiekszy is not None:
            # Mały obraz i brak tekstu - lepsze to niż nic.
            wynik.append(konwertuj_obraz_do_rgb_jpeg(najwiekszy, prefiks=f"img_pdf_p{nr+1}"))
    return wynik


def konwertuj_pdf_do_jpg(sciezka_pdf: str, numer_strony: int = 0, dpi: int = 200) -> list[str]:
    """
    Zamienia strony dokumentu PDF na pliki graficzne JPEG.

    Kolejność:
    1. pypdfium2 / pymupdf - pełne renderowanie strony (komputer stacjonarny),
    2. pypdf - czysty Python (Android): wyciąga skan osadzony na stronie.
    """
    if not os.path.exists(sciezka_pdf):
        raise FileNotFoundError(f"Plik PDF nie istnieje: {sciezka_pdf}")

    def strony(liczba):
        return range(liczba) if numer_strony < 0 else [numer_strony]

    # 1. Pełne renderowanie (działa dla każdego PDF-a)
    for renderer, modul in ((_renderuj_pdf_pypdfium2, "pypdfium2"), (_renderuj_pdf_fitz, "fitz")):
        try:
            __import__(modul)
        except ImportError:
            continue
        # Liczba stron nie jest znana bez otwarcia - renderer sam pomija nadmiarowe.
        return renderer(sciezka_pdf, strony(10_000), dpi)

    # 2. Android: pypdf (bez renderowania)
    try:
        import pypdf  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Do obsługi plików PDF wymagana jest biblioteka 'pypdf' (lub 'pypdfium2' / 'pymupdf'). "
            "Upewnij się, że 'pypdf' znajduje się w pliku pyproject.toml."
        )
    wynik = _wyciagnij_skan_pypdf(sciezka_pdf, strony(10_000))
    if not wynik:
        raise ValueError("W pliku PDF nie znaleziono strony ze skanem dokumentu.")
    return wynik


def standaryzuj_plik_wejsciowy(sciezka_pliku: str) -> str:
    """
    Główny punkt wejścia dla aplikacji:
    Przyjmuje dowolną ścieżkę (PDF, PNG, JPG, WEBP, TIFF itp.)
    i zwraca ścieżkę do czystego, roboczego pliku JPEG gotowego do edytora i OCR.
    """
    if not sciezka_pliku or not os.path.exists(sciezka_pliku):
        return sciezka_pliku

    rozszerzenie = os.path.splitext(sciezka_pliku)[1].lower()

    if rozszerzenie == ".pdf":
        pliki = konwertuj_pdf_do_jpg(sciezka_pliku, numer_strony=0)
        if pliki:
            return pliki[0]
        return sciezka_pliku

    # Wszystkie formaty rastrowe (PNG, JPG, BMP, WEBP, TIFF)
    return konwertuj_obraz_do_rgb_jpeg(sciezka_pliku)
