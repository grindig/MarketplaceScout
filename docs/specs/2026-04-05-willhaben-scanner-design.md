# Willhaben Defekte Grafikkarten Scanner — Design Spec

## Zweck

Ein Bot der jede Minute willhaben.at nach defekten Grafikkarten scannt und neue Treffer per Discord-Webhook meldet. Keywords und Maximalpreis sind per `config.json` konfigurierbar.

## Projektstruktur

```
Willhaben-Bot/
├── main.py          # Einstiegspunkt, Scan-Loop
├── config.json      # Keywords, Maximalpreis, Discord-Webhook, Intervall
├── scanner.py       # Willhaben-API abfragen & parsen
├── notifier.py      # Discord-Webhook Nachrichten senden
├── seen.json        # Automatisch generiert — bereits gesehene Inserat-IDs
└── requirements.txt # requests
```

## Config (`config.json`)

```json
{
  "keywords": ["RTX", "4090", "5090", "defekt", "kaputt", "broken"],
  "max_price": 200,
  "scan_interval_seconds": 60,
  "discord_webhook_url": "https://discord.com/api/webhooks/DEIN_WEBHOOK",
  "willhaben_category": "grafikkarten"
}
```

- **keywords**: ODER-Verknuepfung — ein Treffer reicht
- **max_price**: Inserate ueber diesem Preis werden ignoriert
- **scan_interval_seconds**: Scan-Intervall in Sekunden (default 60)
- **discord_webhook_url**: Discord-Webhook URL
- **willhaben_category**: Willhaben-Kategorie fuer die Suche

## Scanner (`scanner.py`)

- Nutzt Willhaben's interne JSON-API: `https://www.willhaben.at/webapi/iad/search/atz/stp/grafikkarten`
- GET-Request mit Query-Parametern (Keyword, Sortierung nach "neueste zuerst")
- Parst JSON-Response und extrahiert pro Inserat:
  - **ID** (zum Tracken von "bereits gesehen")
  - **Titel**
  - **Preis**
  - **Link**
  - **Standort**
- Filter: Preis <= `max_price`, mindestens ein Keyword im Titel (case-insensitive)
- Vergleicht gegen `seen.json` — nur neue IDs werden weitergegeben
- Neue IDs werden in `seen.json` gespeichert

### Keyword-Matching

Der Titel des Inserats wird lowercase gegen jedes Keyword geprueft. Ein Match reicht (ODER-Verknuepfung).

## Notifier (`notifier.py`)

- POST-Request an den Discord-Webhook
- Discord Embeds pro Inserat:
  - **Titel** als Embed-Title (verlinkt zum Inserat)
  - **Preis**
  - **Standort**
  - **Timestamp** wann gefunden
- Eine Nachricht pro Inserat

## Main Loop (`main.py`)

```
Start
  -> Config laden
  -> seen.json laden (oder leer initialisieren)
  -> Loop:
      1. Scanner: Willhaben abfragen
      2. Neue Inserate filtern (Keywords, Preis, seen)
      3. Fuer jedes neue Inserat -> Notifier: Discord-Nachricht senden
      4. seen.json aktualisieren
      5. Console-Log: "Scan #X — Y neue Treffer gefunden"
      6. sleep(scan_interval_seconds)
```

- Ctrl+C stoppt den Bot sauber
- Bei Netzwerkfehlern: Warnung loggen, weiter zum naechsten Scan (kein Crash)

## Technische Entscheidungen

- **Datenquelle**: Willhaben interne JSON-API (stabiler als HTML-Scraping)
- **Architektur**: Einfaches Python-Script mit `time.sleep` Loop (KISS)
- **Persistence**: `seen.json` fuer bereits gesehene Inserat-IDs
- **Dependencies**: Nur `requests`
- **Benachrichtigung**: Discord-Webhook mit Embeds
