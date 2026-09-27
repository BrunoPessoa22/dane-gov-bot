# dane-gov-bot

Daily publication of **Apartamenty Matejki** (TREND INWESTYCJE s.c.) offer prices to
[dane.gov.pl](https://dane.gov.pl/pl/dataset/16658), as required by art. 19b of the
developer act (*ustawa o ochronie praw nabywcy lokalu mieszkalnego…*).

## How it works

```
WordPress / TablePress (public pages)          the only place prices are edited
  #1 /mieszkania/            apartments
  #3 /technologia-budynku/   parking spaces
  #4 /technologia-budynku/   storage rooms
        │  python -m danegov build
        ▼
public/csv/Ceny-ofertowe-…-YYYY-MM-DD.csv      58-column ministry structure
public/dane-gov.xml + dane-gov.md5             XML harvester feed (schema 1.13)
state/prices.json                              since when each price applies
        │  deliver                             browser upload until the harvester is active,
        │                                      then record the harvester's import
        ▼
dane.gov.pl  ──  python -m danegov verify      downloads the published file and
                                               compares it byte-for-byte
        │  notify
        ▼
e-mail to NOTIFY_EMAILS (success once a day, every failure)
```

- **Source of truth is the website.** The pipeline reads the public TablePress tables,
  so dane.gov.pl always shows what buyers see and nobody edits a CSV by hand.
- **Structure:** *Wzorcowy zakres danych dotyczących cen mieszkań* (22.07.2025), vendored
  in `reference/`, headers copied verbatim. One row per unit on offer (free or reserved;
  sold units are left out, see `INCLUDE_SOLD` in `danegov/config.py`). Apartments fill
  columns 36-43, parking 44-47, storage 48-51; everything that does not apply is `X`.
  From **2026-11-11** the minister's structure is mandatory (Dz.U. 2026 poz. 1077);
  check for the implementing regulation and update `reference/` when it is published.
- **Price dates:** the website shows no history, so "Data od której obowiązuje cena" is the
  first day the pipeline saw a price (`state/prices.json`, committed daily). The initial
  state was seeded from the old hand-maintained `data.csv`.
- **Schedule:** `.github/workflows/daily.yml` runs six times a day (23:17, 02:17, 05:17,
  09:17, 13:17, 17:17 UTC). The first run of a Warsaw day builds and publishes; the others
  retry if something failed and otherwise do nothing.
- **Delivery:** `DELIVERY_MODE` repository variable, default `auto`: the browser bot
  uploads until dane.gov.pl lists an XML-harvested dataset for the institution, then the
  harvester takes over and the bot only uploads as a fallback if the day's import is not
  in the admin panel by 09:00 UTC. `bot` / `harvester` force one path.
- **Verification by id:** dane.gov.pl's public listings come from a search index that lags
  new resources by many hours, so they are never used. The bot takes the day's resource id
  from the admin panel (after its own upload, or after the harvester's import), records it
  in `state/published.json`, verifies that resource directly, and never delivers a
  recorded day twice.
- **Checks that stop publication** (and send a failure e-mail): a table missing or
  renamed column, a table shrinking below its minimum size, an unparseable price or
  status, a duplicate unit number, a file on dane.gov.pl that differs from the day's file.

## Dla osoby edytującej ceny (WordPress)

- Ceny zmieniasz **tylko** w tabelach TablePress, tak jak dotąd. Resztę robi automat:
  następnej nocy ceny trafiają na dane.gov.pl, a data zmiany jest zapisywana automatycznie.
- **Nie zmieniaj nazw ani kolejności kolumn** i nie usuwaj wierszy. Status wpisuj jako
  `wolne`, `rezerwacja` albo `sprzedane`.
- Codziennie rano przychodzi e-mail „[dane.gov.pl] OK”. Jeśli przyjdzie „BŁĄD”, w treści
  jest opis problemu; po poprawieniu tabeli kolejna próba wykona się automatycznie.
  Jeśli do 10:00 nie przyszedł żaden e-mail, coś jest nie tak – daj znać.

## Włączenie automatycznego importu XML (harwester)

Jednorazowo wyślij z adresu konta Edytora na dane.gov.pl wiadomość na
**kontakt@dane.gov.pl**:

> Temat: Wniosek o włączenie automatycznego zasilania danych – TREND INWESTYCJE S.C.
>
> Szanowni Państwo,
>
> w imieniu „TREND INWESTYCJE” S.C. Iwona Merchel, Iwona Sobiecka (NIP 5691893901,
> instytucja na dane.gov.pl: id 5568) składam wniosek o włączenie automatycznego
> zasilania danych o cenach ofertowych mieszkań z pliku XML:
>
> - plik XML: https://brunopessoa22.github.io/dane-gov-bot/dane-gov.xml
> - suma kontrolna MD5: https://brunopessoa22.github.io/dane-gov-bot/dane-gov.md5
> - częstotliwość: codziennie
> - konto Edytora: [adres e-mail konta]
>
> Dotychczas zasoby dodawaliśmy ręcznie do zbioru „Ceny ofertowe mieszkań dewelopera
> Trend Inwestycje w 2025r.” (id 16658). Po uruchomieniu importu zaprzestaniemy dodawania
> ręcznego. Prosimy o informację, czy import może zasilać istniejący zbiór.
>
> Z poważaniem,
> [imię i nazwisko]

Nothing else changes when they activate it: `auto` mode notices the harvested dataset and
stops the browser uploads.

## Operations

| What | How |
| --- | --- |
| Run now | Actions → *Daily dane.gov.pl publication* → Run workflow |
| Re-publish today after fixing the website | same, with **force** ticked |
| Secrets | `DANE_GOV_EMAIL`, `DANE_GOV_PASSWORD` (admin login), `RESEND_API_KEY`, `NOTIFY_EMAILS` (comma-separated) |
| Variables | `DELIVERY_MODE` = `auto` (default), `bot` or `harvester` |
| Published files | https://brunopessoa22.github.io/dane-gov-bot/ (never rename the repository: the harvester URLs depend on it) |

## Development

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt && playwright install chromium
pytest -q
black --check . && isort --check-only .
python -m danegov build            # writes today's files from the live website
python -m danegov notify --outcome success --dry-run
```
