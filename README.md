OCRlmm 📄⚡
Wyspecjalizowany konwerter dokumentów handlowych (Faktury / PZ) do formatu EDI PC-Market
Specialized trade document converter (Invoices / Goods Received PZ) to PC-Market EDI format

🇵🇱 Wersja Polska

O projekcie
OCRlmm to narzędzie stworzone z myślą o pełnej automatyzacji wprowadzania towarów do systemów magazynowo-sklepowych (ze szczególnym uwzględnieniem PC-Market). Program przetwarza dokumenty dostaw i faktury do gotowego pliku tekstowego w standardzie EDI (dokument PZ) z kodowaniem znaków Windows-1250 (TypPolskichLiter:LA).

⚠️ Ważna uwaga dotycząca przeznaczenia:
Aplikacja jest ściśle wyspecjalizowana do pracy z dokumentacją handlową i magazynową (faktury VAT, specyfikacje dostaw, dokumenty PZ / przyjęcia zewnętrzne). Program celowo odrzuca i nie odczytuje tekstu ogólnego, notatek ani pism niespełniających struktury dokumentu magazynowo-fakturowego.

Kluczowe funkcje
Wąska specjalizacja dokumentowa: Analiza tabel pozycji, stawek VAT, kwot netto/brutto oraz danych kontrahentów wyłącznie z faktur i przyjęć zewnętrznych (PZ).
Elastyczność i prywatność przetwarzania:
  Tryb chmurowy: Szybkie i precyzyjne przetwarzanie za pośrednictwem zaawansowanych modeli wizyjnych w chmurze (np. Google Gemini API).
  Tryb lokalny (Prywatność danych): Obsługa lokalnych serwerów LLM (np. LM Studio). Dokumenty wrażliwe biznesowo nie opuszczają Twojej sieci lokalnej.
Pełnoekranowy aparat fotograficzny: Zintegrowany, pełnoekranowy moduł aparatu pozwalający na precyzyjne kadrowanie dokumentów bezpośrednio na stanowisku dostawy (wraz z filtrami kontrastu i wyostrzania dla druku igłowego).
Inteligentne dobieranie kodów (Mapowanie i Fuzzy Matching):
Integracja z własną bazą wzorcową towarów PC-Market (WĘDLINA.txt / NOWA_BAZA.txt).
Samouczący się słownik podręczny (mapowania_towarow.json / baza_kodow.json), zapamiętujący ręcznie przypisane powiązania.
Zaawansowany algorytm dopasowania rozmytego (thefuzz / token_set_ratio), radzący sobie ze skrótami, uciętymi końcówkami, przestawionymi słowami oraz liczbą pojedynczą/mnogą (np. BANAN ➔ BANANY LUZ.).
Weryfikacja matematyczna: Automatyczne sprawdzanie sumy pozycji tabeli z kwotą łączną dokumentu w celu eliminacji pomyłek.
Wsparcie dla wielu platform: Wersja desktopowa (PyQt6) z wklejaniem zrzutów ekranu ze schowka (Ctrl+V) oraz wersja mobilna (Flet) z obsługą wybudzania serwera GPU przez Wake-on-LAN (WoL).

Twórca

Projekt stworzony i rozwijany przez: Zizi

🇬🇧 English Version

About The Project

OCRlmm is a dedicated software solution built to automate the ingestion of trade and warehouse documentation into inventory control systems (specifically PC-Market). It converts incoming delivery specifications and invoices into standard PC-Market EDI text files (PZ goods receipt) encoded in Windows-1250 (TypPolskichLiter:LA).
  ⚠️ Scope & Document Restriction Notice:
The system is strictly engineered for commercial trade and inventory records (VAT invoices, delivery notes, PZ / external goods received notes). It is designed to ignore or reject general non-document text, arbitrary notes, and documents lacking standard invoice/trade line-item tables.

Key Features
Strict Document-Centric Processing: Extracts itemized rows, tax rates, net/gross values, and contractor information exclusively from invoices and external intake sheets (PZ).

Cloud & Privacy Modes:
    Cloud Mode: High-speed inference using cloud vision models (e.g., Google Gemini API).
    Local Engine (Data Privacy): Direct integration local vision LLMs (e.g., LM Studio). Commercial data remains fully confidential within the private network.
Fullscreen Camera Interface: Integrated fullscreen capture view designed for field operations, supporting instant document snapping, rotation, and custom contrast/sharpening enhancements optimized for legacy dot-matrix printouts.
Smart Code Matching & Learning Mapping Base:
Built-in indexing against master item directories (WĘDLINA.txt / NOWA_BAZA.txt).
Dynamic dictionary (mapowania_towarow.json / baza_kodow.json) that learns user overrides and saves custom vendor-to-internal code bindings.
Resilient fuzzy matching algorithm (thefuzz / token_set_ratio), handling supplier abbreviations, reordered terms, and plural/singular forms (e.g., BANAN ➔ BANANY LUZ.).
Mathematical Cross-Validation: Real-time reconciliation comparing computed line-item totals with the printed document summary to catch discrepancy errors before import.
Multi-Platform Ecosystem: Desktop interface (PyQt6) with instant clipboard screenshot pasting (Ctrl+V) and mobile client (Flet) equipped with Wake-on-LAN (WoL) to power up local processing nodes remotely.
Author & Credits

Created and developed by: Zizi
