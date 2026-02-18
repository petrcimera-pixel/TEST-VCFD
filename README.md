# Denní tipy na sázení (fotbal + hokej)

Aplikace generuje a ukládá tipy do SQLite databáze, umožňuje ručně nastavovat výsledky tipů (výhra/prohra), filtrovat tipy, zobrazovat historii a poskytuje detailní statistiky přes grafy.

## Funkce
- minimálně 20 tipů při prvním spuštění,
- zobrazení data a času začátku zápasu,
- filtrování podle ligy a minimální důvěryhodnosti,
- tlačítko pro generování dalších tipů,
- ruční aktualizace výsledků tipů,
- automaticky přepočítané souhrnné statistiky,
- stránka detailních statistik (grafy podle sportu, ligy a měsíce),
- denní email s tipy přes Resend API na `petrcimera@gmail.com` v 08:00 + ruční odeslání tlačítkem.

## Spuštění
```bash
python3 app.py
```

## Konfigurace (volitelné přes ENV)
- `PORT` (default `3000`)
- `RESEND_API_KEY`
- `RESEND_FROM_EMAIL`
- `TARGET_EMAIL`
