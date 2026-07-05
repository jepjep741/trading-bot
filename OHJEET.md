# Treidausbotti — käyttöohjeet

Kryptotreidausbotti, joka hakee oikeaa markkinadataa Binancesta (ccxt),
tekee päätökset SMA 12/26 -ristikkosignaalilla ja markkinaregiimillä, ja
treidaa joko paperilla (simuloitu), Binancen testiverkossa tai oikealla
rahalla. Tila tallentuu SQLite-kantaan (`data/tradingbot.db`).

**Tämänhetkinen tila: botti pyörii Binancen TESTIVERKOSSA** (leikkirahaa,
10 000 USDT). Avaimet ovat tiedostossa `.env`.

## Miten botti toimii

- **Regiimi**: BTC:n ja ETH:n 7 päivän muutos luokittelee markkinan:
  - `BULL` (molemmat > +5 %) — kaikki tasot aktiivisia, ostoihin +0.05 luottamusta
  - `BEAR` (molemmat < −5 %) — uudet ostot estetty
  - `RANGING` (±5 %) — ostokynnys tiukempi
  - `DIVERGING` (eri suuntiin) — luottamus katkaistaan 0.50:een → botti odottaa
- **Aikataulu**: täysi skannaus 2 h välein, tier-3 "unicorn"-skanneri 30 min
  välein (vain BULL-regiimissä), ja **30 sekunnin välein** take-profit /
  stop-loss -tarkistus, hätäjarru ja käyttöliittymän toimeksiannot.
- **Tasot** (`config.yaml`): stable-core (kynnys 0.65, positio 5 %),
  momentum-midcap (0.72, 3 %), unicorn-skanneri (0.78, 1.5 %).
- **Hätäjarru**: jos päivän tappio ylittää `max_daily_loss_pct` (oletus 5 %),
  uudet ostot pysähtyvät automaattisesti. Avoimet positiot pitävät
  TP/SL-tasonsa. Jatka kojelaudalta.
- **Claude-analyytikko** (valinnainen): jos `ANTHROPIC_API_KEY` on asetettu,
  Claude arvioi jokaisen signaalin ja perustelut tallennetaan kantaan.

## Käynnistys ja pysäytys

```bash
cd ~/work/trading-bot

podman-compose --env-file .env up -d      # käynnistä botti + kojelauta
podman-compose down                       # pysäytä kaikki
podman logs -f tradingbot                 # seuraa bottia reaaliajassa
podman restart tradingbot                 # käynnistä botti uudelleen
```

Kun muutat koodia tai asetuksia (`config.yaml`), kontit pitää rakentaa ja
luoda uudelleen — pelkkä `up -d --build` EI riitä:

```bash
podman-compose --env-file .env up -d --build --force-recreate
```

**HUOM:** rootless Podman EI käynnistä kontteja koneen uudelleenkäynnistyksen
jälkeen. Buutin jälkeen aja `podman-compose --env-file .env up -d` itse —
muuten avoimet positiot jäävät ilman stop-loss-valvontaa. (Pysyvä ratkaisu:
`loginctl enable-linger sami` + systemd-käyttäjäpalvelut.)

## Kojelauta (selainkäyttöliittymä)

Avaa **http://127.0.0.1:8060** (pasta-verkon takia nimenomaan 127.0.0.1,
ei `localhost`/`::1`). Päivittyy itsestään minuutin välein.

- **Tilamerkki** ylhäällä: sininen **PAPER** = paperitreidaus, keltainen
  **LIVE · testnet** = testiverkko, punainen **LIVE — real funds** = oikea raha.
- **Mittarit**: pääoma, käteinen, avoimet positiot, realisoitunut tulos,
  osumatarkkuus.
- **Controls-kortti**:
  - *Pause new entries / Resume trading* — pysäyttää/jatkaa uudet ostot
    (myynnit ja TP/SL toimivat aina).
  - *Close all positions* — sulkee kaikki positiot markkinahintaan.
  - Positiotaulukon *Close*-nappi sulkee yhden position.
  - Toimeksiannot jonotetaan ja botti toteuttaa ne ~30 sekunnissa —
    kojelaudalla ei ole pörssiavaimia (turvaominaisuus).
- **Käyrät**: pääomakäyrä (piste joka skannauksesta) ja 24 h markkinakatsaus.
- **Taulukot**: avoimet positiot, signaalit perusteluineen, kaupat.

Kojelaudassa ei ole kirjautumista — älä avaa porttia 8060 ulospäin ilman
autentikoivaa välityspalvelinta.

## Komentorivi

```bash
cd ~/work/trading-bot
.venv/bin/python -m tradingbot status     # käteinen, pääoma, positiot
.venv/bin/python -m tradingbot signals    # viimeisimmät signaalit perusteluineen
.venv/bin/python -m tradingbot trades     # kauppahistoria
.venv/bin/python -m tradingbot scan       # aja yksi skannaus heti
.venv/bin/python -m tradingbot reset      # tyhjennä tietokanta (kysyy varmistuksen)
```

Samat komennot toimivat kontin sisällä:
`podman exec tradingbot python -m tradingbot status`

## Treidaustilat

| Tila | `config.yaml` | Lisäksi tarvitaan |
|---|---|---|
| Paperi | `trading: mode: paper` | ei mitään |
| Testiverkko | `mode: live`, `testnet: true` | testiverkon avaimet `.env`-tiedostossa |
| Oikea raha | `mode: live`, `testnet: false` | oikeat avaimet **ja** `LIVE_TRADING_ACK=I-ACCEPT-FULL-LOSS` |

**Tilaa vaihtaessa nollaa tietokanta** (tai ota talteen:
`mv data/tradingbot.db data/tradingbot.vanha.db`) — muuten hätäjarru ja
mittarit laskevat väärin vanhan tilan pääomahistoriasta. Paperihistoria on
tallessa: `data/tradingbot.paper-backup.db`. Aseta myös `starting_cash`
vastaamaan uuden tilan saldoa.

## Siirtyminen oikeaan rahaan — lue tämä kokonaan

**Botti voi hävitä rahaa nopeasti. SMA-ristikko on perusstrategia, ei
todistettu etu. Älä koskaan treidaa rahalla, jonka menetystä et kestä.**

1. **Luo API-avaimet turvallisesti** (Binance):
   - Oma avain vain botille, **vain spot-treidaus käyttöön**.
   - **Nostot (withdrawals) POIS PÄÄLTÄ** — vuotanut avain ei voi viedä varoja.
   - Rajaa avain palvelimen IP-osoitteeseen.
   - Käytä alitiliä, jolla on vain botin käyttöön tarkoitettu summa.
2. **Aja ensin testiverkossa** (nykyinen tila) kunnes olet omin silmin
   nähnyt: automaattisen oston, TP/SL-myynnin, käsin sulkemisen
   kojelaudalta ja hätäjarrun/tauon toiminnan.
3. **Aloita pienellä**: laske `position_pct` (esim. 5 → 1),
   `max_open_positions: 2–3`, pidä `max_daily_loss_pct` tiukkana.
   Binancen minimiosto on ~10 USDT — tilillä pitää olla tarpeeksi, että
   positiokoko ylittää sen.
4. Avaimet vain `.env`-tiedostoon (`chmod 600`, ei versionhallintaan) ja
   vain **tradingbot**-kontille — ei koskaan kojelaudalle.
5. Muista: stop-lossit ovat **botin** valvomia, eivät pörssin. Jos botti on
   sammuksissa, stopit eivät laukea. Pidä `restart: unless-stopped` päällä,
   seuraa kojelautaa ja käynnistä kontit buutin jälkeen.

## Vianetsintä

- **Kojelauta ei aukea** → käytä `http://127.0.0.1:8060`, tarkista
  `podman ps` ja `podman logs tradingbot-dashboard`.
- **Botti ei käynnisty live-tilassa** → puuttuvat avaimet tai
  `LIVE_TRADING_ACK`. Virheilmoitus kertoo kumpi: `podman logs tradingbot`.
- **"skip ... below exchange min"** → positiokoko alle pörssin minimin;
  kasvata `position_pct`-arvoa tai talletusta.
- **Hätäjarru lauennut** → kojelaudan banneri kertoo syyn; *Resume trading*
  jatkaa, kun olet katsonut tilanteen.
- **Ei yhtään kauppaa** → normaalia: botti ostaa vain tuoreesta
  SMA-ristikosta, jonka luottamus ylittää tason kynnyksen, eikä koskaan
  BEAR-regiimissä. Katso signaalit ja perustelut kojelaudalta.
