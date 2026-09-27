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


def konwertuj_pdf_do_jpg(sciezka_pdf: str, numer_strony: int = 0, dpi: int = 200) -> list[str]:
    """
    Wyciąga lub renderuje strony dokumentu PDF do plików graficznych JPEG.
    W pierwszej kolejności używa czysto pythonowej biblioteki 'pypdf' (działa na Androidzie).
    Jeśli pypdf nie jest dostępny, próbuje pypdfium2 lub pymupdf (fitz).
    """
    if not os.path.exists(sciezka_pdf):
        raise FileNotFoundError(f"Plik PDF nie istnieje: {sciezka_pdf}")

    wygenerowane_pliki = []

    # 1. Metoda główna dla Androida: pypdf (czysty Python bez bibliotek C++)
    try:
        from pypdf import PdfReader

        reader = PdfReader(sciezka_pdf)
        liczba_stron = len(reader.pages)
        strony_do_obrobki = range(liczba_stron) if numer_strony < 0 else [numer_strony]

        for nr in strony_do_obrobki:
            if nr >= liczba_stron:
                break
            page = reader.pages[nr]

            # Wyciągamy obrazy osadzone na stronie (skany faktur)
            if page.images:
                for img_idx, img_obj in enumerate(page.images):
                    try:
                        pil_img = Image.open(io.BytesIO(img_obj.data))
                        sciezka_zapisu = konwertuj_obraz_do_rgb_jpeg(
                            pil_img, prefiks=f"img_pdf_p{nr+1}_{img_idx+1}"
                        )
                        wygenerowane_pliki.append(sciezka_zapisu)
                    except Exception as err:
                        print(f"Błąd odczytu grafiki ze strony {nr+1}: {err}")

        if wygenerowane_pliki:
            return wygenerowane_pliki
    except ImportError:
        pass

    # 2. Fallback na pypdfium2 (np. na komputerze stacjonarnym)
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(sciezka_pdf)
        liczba_stron = len(pdf)
        strony_do_obrobki = range(liczba_stron) if numer_strony < 0 else [numer_strony]
        scale = dpi / 72.0

        for nr in strony_do_obrobki:
            if nr >= liczba_stron:
                break
            page = pdf[nr]
            pil_image = page.render(scale=scale).to_pil()
            sciezka_zapisu = konwertuj_obraz_do_rgb_jpeg(pil_image, prefiks=f"img_pdf_p{nr+1}")
            wygenerowane_pliki.append(sciezka_zapisu)

        pdf.close()
        return wygenerowane_pliki
    except ImportError:
        pass

    # 3. Fallback na pymupdf/fitz
    try:
        import fitz

        doc = fitz.open(sciezka_pdf)
        strony = range(len(doc)) if numer_strony < 0 else [numer_strony]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        for idx in strony:
            if idx >= len(doc):
                break
            page = doc[idx]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            sciezka_wyjsciowa = _generuj_sciezke_wyjsciowa(prefiks=f"img_pdf_p{idx+1}")
            pix.save(sciezka_wyjsciowa)
            wygenerowane_pliki.append(sciezka_wyjsciowa)
        doc.close()
        return wygenerowane_pliki
    except ImportError:
        pass

    raise RuntimeError(
        "Do obsługi plików PDF wymagana jest biblioteka 'pypdf' (lub 'pypdfium2' / 'pymupdf'). "
        "Upewnij się, że 'pypdf' znajduje się w pliku pyproject.toml."
    )


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
