# OCRlmm 📄⚡

**Wyspecjalizowany konwerter dokumentów handlowych (Faktury / PZ) do formatu EDI PC-Market**  
*Specialized trade document converter (Invoices / Goods Received PZ) to PC-Market EDI format*

---

## 🇵🇱 Wersja Polska

### O projekcie
**OCRlmm** to narzędzie stworzone z myślą o pełnej automatyzacji wprowadzania towarów do systemów magazynowo-sklepowych (ze szczególnym uwzględnieniem programu **PC-Market**). Program przetwarza dokumenty dostaw i faktury do gotowego pliku tekstowego w standardzie **EDI (dokument PZ)** z kodowaniem znaków **Windows-1250 (`TypPolskichLiter:LA`)**.

> [!WARNING]
> ### ⚠️ Ważna uwaga dotycząca przeznaczenia
> Aplikacja jest **ściśle wyspecjalizowana** do pracy z dokumentacją handlową i magazynową (**faktury VAT, specyfikacje dostaw, dokumenty PZ / przyjęcia zewnętrzne**).  
> Program celowo **odrzuca i nie odczytuje** tekstu ogólnego, notatek ani pism niespełniających struktury dokumentu magazynowo-fakturowego.

---

### Kluczowe funkcje

* **Wąska specjalizacja dokumentowa:**  
  Analiza tabel pozycji, stawek VAT, kwot netto/brutto oraz danych kontrahentów wyłącznie z faktur i przyjęć zewnętrznych (PZ).

* **Elastyczność i prywatność przetwarzania:**  
  * **Tryb chmurowy:** Szybkie i precyzyjne przetwarzanie za pośrednictwem zaawansowanych modeli wizyjnych w chmurze (np. Google Gemini API).  
  * **Tryb lokalny (Prywatność danych):** Obsługa lokalnych serwerów LLM (np. LM Studio). Dokumenty wrażliwe biznesowo nie opuszczają Twojej sieci lokalnej.

* **Pełnoekranowy aparat fotograficzny:**  
  Zintegrowany, pełnoekranowy moduł aparatu pozwalający na precyzyjne kadrowanie dokumentów bezpośrednio na stanowisku dostawy (wraz z filtrami kontrastu i wyostrzania dla druku igłowego).

* **Inteligentne dobieranie kodów (Mapowanie i Fuzzy Matching):**  
  * Integracja z własną bazą wzorcową towarów PC-Market (`WĘDLINA.txt` / `NOWA_BAZA.txt`).  
  * Samouczący się słownik podręczny (`mapowania_towarow.json` / `baza_kodow.json`), zapamiętujący ręcznie przypisane powiązania.  
  * Zaawansowany algorytm dopasowania rozmytego (`thefuzz` / `token_set_ratio`), radzący sobie ze skrótami, uciętymi końcówkami, przestawionymi słowami oraz liczbą pojedynczą/mnogą (np. *BANAN* ➔ *BANANY LUZ.*).

* **Weryfikacja matematyczna:**  
  Automatyczne sprawdzanie sumy pozycji tabeli z kwotą łączną dokumentu w celu eliminacji pomyłek.

* **Wsparcie dla wielu platform:**  
  * **Wersja desktopowa (PyQt6):** z wklejaniem zrzutów ekranu bezpośrednio ze schowka (`Ctrl+V`) oraz obsługą plików PDF.  
  * **Wersja mobilna (Flet):** z obsługą wybudzania domowego serwera GPU przez sieć (**Wake-on-LAN / WoL**).

---

### Twórca
Projekt stworzony i rozwijany przez: **Zizi**
