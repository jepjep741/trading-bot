# Kojelauta v3 — valvonta ja hallinta

> In English: [README.md](README.md)

Paikallinen web-kojelauta treidausbotille: FastAPI-taustapalvelu (JSON-API +
WebSocket) ja React + Tailwind + Recharts -käyttöliittymä, tumma teema.
Kojelauta on **erillinen prosessi** — jos käyttöliittymä kaatuu, treidaus
jatkuu häiriöttä, ja toisinpäin.

## Käynnistys

**Podman (suositeltu):**
```bash
podman-compose --env-file .env up -d --build dashboard-v3
# → http://127.0.0.1:8070
```

**Kehitys:**
```bash
DASHBOARD_ADMIN_PASSWORD=... .venv/bin/python -m uvicorn app.main:app \
    --app-dir dashboard-v3/backend --port 8070
cd dashboard-v3/frontend && npm install && npm run dev   # → :5173
```

**Testit:**
```bash
cd dashboard-v3/backend && ../../.venv/bin/python -m pytest tests/
```

## Ylläpitäjän salasana

Aseta `DASHBOARD_ADMIN_PASSWORD` `.env`-tiedostoon. Ilman sitä hallintapaneeli
on pois käytöstä — lukusivut toimivat silti. Kirjautuminen on rajoitettu
(5 yritystä/min), istunto on HMAC-allekirjoitettu eväste, ja salasana ei
koskaan päädy koodiin, lokeihin eikä tietokantaan.

## Turvamalli

- Sidotaan **vain osoitteeseen 127.0.0.1**. Muun verkkoliitännän käyttö
  vaatii sekä asetusmuutoksen että salasanan — muuten palvelin kieltäytyy
  käynnistymästä.
- Kojelaudalla **ei ole pörssin API-avaimia.** Hallintatoimet kirjoitetaan
  SQLite-kantaan; bottiprosessi toteuttaa ne ~30 sekunnissa.
- Jokainen hallintatoimi vaatii vahvistuksen ja kirjautuu audit-lokiin.

## Mitä hallintapaneelista EI voi tehdä (tahallaan)

Rajat toteutuvat rakenteellisesti botin asetusten yhdistämisessä
(`apply_overrides`) joka syklillä — eivät pelkässä käyttöliittymässä:

| Asetus | Sääntö |
|---|---|
| Positiokoko (per taso) | saa laskea vapaasti; nosto katkaistaan `config.yaml`-arvoon |
| Luottamuskynnykset | saa nostaa (varovaisempi); lasku katkaistaan tiedostoarvoon |
| Avoimet positiot enintään | vain alaspäin |
| Päivätappion hätäjarru | vain alaspäin — tiedostoarvo on katto |
| Take-profit / stop-loss | ei muokattavissa lainkaan |
| Stopien poiskytkentä | sellaista säädintä ei ole |
| Vipu | botti on spot-only, aina 1x |
| **Live-tila** | **ei koskaan nappi** — vaatii `config.yaml`-muutoksen, API-avaimet JA `LIVE_TRADING_ACK`-ympäristömuuttujan bottiprosessille |

## Sivut

- **Overview** — tilabanneri (RUNNING / HALTED / KILL SWITCH / BOT OFFLINE +
  PAPER/TESTNET/LIVE), päivän tulos, ohitettujen signaalien syyt, jäljellä
  oleva päivätappiobudjetti, tappioputki, pääoma vs. osta-ja-pidä-BTC.
- **Sources** — tilastot lähteittäin (taso × päätöksen alkuperä): raaka ja
  **kutistettu** osumatarkkuus rinnakkain (Beta-posteriori, 20 kaupan priori
  kohti 50 %, ~90 % uskottavuusväli palkkina), profit factor, max drawdown,
  aikapainotettu osumatarkkuus; päivätulosten korrelaatiolämpökartta;
  pääomakäyrät pienoiskuvina. Kaikki luvut lasketaan taustapalvelussa —
  käyttöliittymä ei laske mitään itse.
- **Signals & Trades** — reaaliaikainen syöte (WebSocket, automaattinen
  uudelleenyhdistys): jokainen päätös Clauden perusteluineen; kauppapäiväkirja
  R-kertoimineen, pitoaikoineen ja suodattimineen; CSV-vienti.
- **Reports** — päiväraportit uusin ensin, jokaisessa selkokielinen rivi:
  voittiko botti pelkän Bitcoinin pitämisen kulujen jälkeen.
- **Admin** — tauko/jatka, hätäkatkaisin (pysäyttää skannauksen ja ostot;
  TP/SL-myynnit jatkuvat), kaikkien positioiden sulkeminen, rajattu
  asetuseditori, paperitilin nollaus kirjoittamalla `RESET PAPER ACCOUNT`,
  audit-loki.
