# Teslascope to TeslaMate converter

Bring your [Teslascope](https://teslascope.com) history into [TeslaMate](https://github.com/teslamate-org/teslamate).

TeslaMate can only import [TeslaFi](https://docs.teslamate.org/docs/import/teslafi) files. This script turns a Teslascope data export into TeslaFi-format CSV files, one per month. TeslaMate's own importer then rebuilds your drives, charges and positions from them.

It is a single Python file with no dependencies (Python 3.10+).

## What gets imported

| From Teslascope | In TeslaMate |
|---|---|
| Drive progress (one GPS point per minute) | Drives, with their route, speed, power, battery level and temperatures |
| Charge progress + charges | Charging sessions, with energy added, power and voltage curves and location |
| Odometer | Mileage |

**What's lost:**

- charge costs (set a cost per kWh on your geofences in TeslaMate instead);
- the names Teslascope gave to drives, charges and places (recreate Home, Work, etc. as geofences);
- the time the car spent parked or asleep: Teslascope only exports what happens during drives and charges, so TeslaMate shows the car as asleep between sessions;
- reminders and anything else that isn't a drive or a charge.

Gaps already present in your Teslascope history stay gaps.

TeslaMate splits trips its own way, so you will usually see more drives than Teslascope listed (short manoeuvres become drives of their own). The total distance stays the same.

## Usage

### 1. Export from Teslascope

In Teslascope, go to **Account → Data Export** and request at least **Drive Progress**, **Charge Progress**, **Charges** and **Vehicle**. Download the zip from the email (the link expires after 24 hours, and you have to be signed in to Teslascope to open it). Exporting one year at a time is fine.

### 2. Convert

```sh
python3 teslascope2teslamate.py teslascope-2024.zip teslascope-2025.zip -o teslamate-import
```

You can pass zips or extracted folders, several at once. The output looks like this:

```
863 drives, 165 charges, 55650 points from 2024-01-01 21:59:14 to 2025-02-28 18:55:27 (UTC)
wrote 57336 rows (1686 synthetic) in 12 files to teslamate-import/
```

Options:

| Option | Default | Use |
|---|---|---|
| `-o`, `--output` | `teslamate-import` | output folder |
| `--vin` | | pick one car when the export holds several |
| `--vehicle-id` | `1` | if the car already exists in TeslaMate, pass its `vid` (`select vid from cars`), otherwise the import is rejected as a different vehicle |
| `--car-type` | `model3` | model stored when TeslaMate creates the car (`models`, `modelx`, `modely`, `model3`) |

### 3. Import into TeslaMate

Follow [TeslaMate's import guide](https://docs.teslamate.org/docs/import/teslafi):

1. Copy the generated `TeslaFi*.csv` files into the import folder mounted in your TeslaMate container (`/opt/app/import`) and restart TeslaMate.
2. Open the import page in TeslaMate.
3. **Select `UTC` as the time zone.** Teslascope exports times in UTC (see below).
4. Start the import. About 55 000 points took 5 minutes in our test.

When it's done, empty the import folder and restart TeslaMate so it goes back to logging normally.

**Importing next to existing data.** TeslaMate's importer only adds history *older* than the first data already in your database, and stops there. So importing Teslascope into an instance that already holds later TeslaMate data works, and the two never overlap. If you are also restoring a TeslaMate backup, restore it first, then run this import.

## Notes and caveats

- **Time zone.** The export doesn't say which zone its timestamps use. In the export we checked, the first drive of the day moves by about one hour between summer and winter, which points to UTC. Choose UTC on the import page. If your times end up 1 or 2 hours off, rerun the import with your local time zone instead.
- **Units.** Teslascope exports distances and ranges in miles, like the Tesla API and TeslaFi. TeslaMate converts them, nothing to do on your side.
- **Closing sessions.** Teslascope only has points during drives and charges. After each session followed by a gap of more than 3 minutes, the script adds two rows (car parked/unplugged, then asleep), so TeslaMate ends the drive or charge there instead of stretching it to the next one. These are the "synthetic" rows in the output.
- **Charge points** carry no odometer in Teslascope: the script reuses the last odometer reading from the previous drive.
- Rows with a different number of columns than their header are skipped.

This was tested on one real export (a Model 3, 14 months, about 55 000 points) imported into TeslaMate 4.3.0 with zero rejected rows. Other exports may have quirks we haven't seen: please open an issue with the error message and, if you can, a few anonymised lines of the file.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

## Hosted option

If you'd rather not run TeslaMate yourself, [MyTeslaMate](https://www.myteslamate.com) hosts it for you, and we can run this import for you during the trial.

## License

[MIT](LICENSE). Not affiliated with Teslascope, TeslaFi, TeslaMate or Tesla.
