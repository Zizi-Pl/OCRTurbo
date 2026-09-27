import socket
import asyncio
import re
import time
import httpx


# --- WAKE-ON-LAN I SPRAWDZANIE PORTÓW ---

def wyslij_wol(mac_address: str, docelowe_ip: str = "255.255.255.255") -> None:
    """Wysyła pakiet Magic Packet (Wake-on-LAN) na podany adres MAC."""
    czysty_mac = re.sub(r'[^0-9A-Fa-f]', '', mac_address)
    if len(czysty_mac) != 12:
        raise ValueError("Nieprawidłowy format adresu MAC.")

    dane_mac = bytes.fromhex(czysty_mac)
    magic_packet = b"\xff" * 6 + dane_mac * 16

    wyslano = False
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.sendto(magic_packet, ("255.255.255.255", 9))
            wyslano = True
        except Exception:
            pass
        try:
            czesci = docelowe_ip.split(".")
            if len(czesci) == 4:
                subnet_broadcast = f"{czesci[0]}.{czesci[1]}.{czesci[2]}.255"
                s.sendto(magic_packet, (subnet_broadcast, 9))
                s.sendto(magic_packet, (docelowe_ip, 9))
                wyslano = True
        except Exception:
            pass

    if not wyslano:
        raise RuntimeError("Nie udało się wysłać pakietu WoL. Sprawdź połączenie z siecią Wi-Fi.")


async def sprawdz_port_tcp(ip: str, port: int, timeout: float = 2.0) -> bool:
    """Asynchronicznie sprawdza dostępność portu TCP na wskazanym IP."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


async def upewnij_sie_ze_serwer_zyje(
    ip: str,
    port: int,
    mac_adres: str = "",
    maks_czas_oczekiwania: int = 150,
    interwal: int = 10,
    on_status=None,
    on_log=None
) -> bool:
    """
    Sprawdza stan serwera lokalnego. Jeśli nie odpowiada, wysyła WoL i oczekuje
    na jego uruchomienie, raportując postęp przez callbacki on_status i on_log.
    """
    loop = asyncio.get_running_loop()

    if on_log:
        on_log(f"Sprawdzanie stanu serwera LM Studio ({ip}:{port})...")

    if await sprawdz_port_tcp(ip, port, timeout=3.0):
        return True

    if on_log:
        on_log("Serwer lokalny nie odpowiada. Wysyłanie WoL...", "AMBER")

    if mac_adres:
        try:
            await loop.run_in_executor(None, wyslij_wol, mac_adres, ip)
            if on_log:
                on_log("Pakiet WoL wysłany. Czekam na załadowanie LM Studio...", "CYAN")
        except Exception as e_wol:
            if on_log:
                on_log(f"Błąd wysyłania WoL: {e_wol}", "RED")

    czas_miniony = 0
    while czas_miniony < maks_czas_oczekiwania:
        if on_status:
            on_status(f"Oczekiwanie na uruchomienie LM Studio... ({czas_miniony}/{maks_czas_oczekiwania}s)")

        await asyncio.sleep(interwal)
        czas_miniony += interwal

        # Ponawianie pakietu WoL co 30 sekund
        if mac_adres and czas_miniony % 30 == 0:
            try:
                await loop.run_in_executor(None, wyslij_wol, mac_adres, ip)
            except Exception:
                pass

        if await sprawdz_port_tcp(ip, port, timeout=3.0):
            if on_log:
                on_log(f"Serwer LM Studio gotowy po {czas_miniony}s!", "GREEN")
            return True

    raise TimeoutError(f"Serwer pod adresem {ip}:{port} nie uruchomił się w czasie {maks_czas_oczekiwania}s.")


# --- WYSYŁKA ZAPYTAŃ DO AI (HTTPX) ---

async def wyslij_zadanie_ai(
    url: str,
    headers: dict,
    payload: dict,
    cel_logu: str = "AI",
    max_prob: int = 4,
    opoznienie_poczatkowe: float = 2.0,
    timeout_read: float = 300.0,
    on_status=None,
    on_log=None
) -> tuple[str, dict, dict]:
    """
    Wysyła żądanie do API modelu AI (Gemini lub LM Studio).
    Automatycznie ponawia próby przy przeciążeniu (błędy 429 i 503) z wykładniczym czasem oczekiwania.
    
    Zwraca krotkę:
    (tresc_odpowiedzi, pelne_dane_json, statystyki_wydajnosci)
    """
    if on_log:
        on_log(f"🌐 Wysyłanie zapytania do: {cel_logu}...")

    timeout_cfg = httpx.Timeout(10.0, read=timeout_read)
    odpowiedz = None
    start_siec = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout_cfg, verify=True) as client:
        for proba in range(max_prob):
            if proba > 0 and on_log:
                on_log(f"Ponawianie zapytania (próba {proba + 1}/{max_prob})...", "AMBER")

            odpowiedz = await client.post(url, headers=headers, json=payload)

            if odpowiedz.status_code in (503, 429):
                if proba < max_prob - 1:
                    czas_oczekiwania = opoznienie_poczatkowe * (2 ** proba)
                    if on_status:
                        on_status(f"Serwer zajęty ({odpowiedz.status_code}). Ponawianie za {czas_oczekiwania:.1f}s...")
                    if on_log:
                        on_log(f"Serwer zwrócił kod {odpowiedz.status_code}. Oczekiwanie {czas_oczekiwania:.1f}s...", "AMBER")
                    await asyncio.sleep(czas_oczekiwania)
                    continue

            odpowiedz.raise_for_status()
            break

    czas_siec = time.perf_counter() - start_siec
    dane_odp = odpowiedz.json()

    wybor = dane_odp.get("choices", [{}])[0]
    odp_tekst = (wybor.get("message", {}).get("content") or "").strip()
    powod_konca = wybor.get("finish_reason")

    uzycie = dane_odp.get("usage") or {}
    in_tok = uzycie.get("prompt_tokens", 0)
    out_tok = uzycie.get("completion_tokens", 0)
    detale_out = uzycie.get("completion_tokens_details") or {}
    think_tok = detale_out.get("reasoning_tokens")
    predkosc = (out_tok / czas_siec) if (czas_siec > 0 and out_tok > 0) else 0.0

    statystyki = {
        "czas_s": czas_siec,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "think_tok": think_tok,
        "predkosc": predkosc,
        "finish_reason": powod_konca
    }

    if on_log:
        log_wydajnosc = f"⏱️ Czas AI: {czas_siec:.2f}s | Tokeny: {in_tok} wejście / {out_tok} wyjście"
        if think_tok:
            log_wydajnosc += f" (myślenie: {think_tok})"
        if predkosc > 0:
            log_wydajnosc += f" | Prędkość: {predkosc:.1f} tok/s"
        on_log(log_wydajnosc, "CYAN")

        if powod_konca == "length":
            on_log("⚠️ OSTRZEŻENIE: Odpowiedź modelu została ucięta (limit tokenów)!", "RED")

    return odp_tekst, dane_odp, statystyki
