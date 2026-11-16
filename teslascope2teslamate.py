#!/usr/bin/env python3
"""Convert a Teslascope data export into TeslaFi-format CSV files that
TeslaMate's built-in importer can read.

Usage:
    python3 teslascope2teslamate.py EXPORT [EXPORT ...] -o OUTPUT_DIR

EXPORT is a Teslascope export, either the downloaded .zip or an extracted
folder. Several exports (one per year, for example) can be passed at once.
Only the Python standard library is needed.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta

__version__ = "0.1.0"

# Columns written to every TeslaFi file. TeslaMate's importer ignores the
# columns it does not know and reads these ones by name.
COLUMNS = [
    "Date", "vin", "vehicle_id", "id", "display_name", "car_type", "state",
    "shift_state", "latitude", "longitude", "heading", "speed", "power",
    "odometer", "battery_level", "usable_battery_level", "battery_range",
    "ideal_battery_range", "est_battery_range", "inside_temp", "outside_temp",
    "fan_status", "is_climate_on", "charging_state", "charge_energy_added",
    "charge_limit_soc", "charger_power", "charger_voltage", "charge_rate",
    "conn_charge_cable", "fast_charger_present", "fast_charger_brand",
    "fast_charger_type", "charge_port_door_open", "charge_port_latch",
    "time_to_full_charge",
]

DATE_FMT = "%Y-%m-%d %H:%M:%S"

# A session (drive or charge) followed by a gap longer than this gets two
# synthetic rows (unplugged/parked, then asleep) so TeslaMate closes it
# instead of stretching it across the gap.
CLOSE_GAP = timedelta(seconds=180)


class ConversionError(Exception):
    pass


# --------------------------------------------------------------------------
# Reading the export
# --------------------------------------------------------------------------

def _rows(text: str) -> list[dict]:
    """Parse one Teslascope CSV; rows with a wrong column count are dropped."""
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    try:
        header = next(reader)
    except StopIteration:
        return []
    out = []
    for line in reader:
        if len(line) == len(header):
            out.append(dict(zip(header, line)))
    return out


def _find_exports(paths: list[str]) -> list[dict[str, str]]:
    """Return one {file name: CSV text} mapping per Teslascope export folder
    found in the given zips/folders, in a stable order."""
    wanted = {"vehicle.csv", "drive-progress.csv", "charges.csv", "charge-progress.csv"}
    groups: dict[str, dict[str, str]] = {}

    def add(key: str, name: str, read):
        if name in wanted:
            groups.setdefault(key, {})[name] = read().decode("utf-8")

    for path in paths:
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for name in files:
                    full = os.path.join(root, name)
                    add(root, name, lambda f=full: open(f, "rb").read())
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    folder, name = os.path.split(info.filename)
                    add(f"{path}!{folder}", name, lambda i=info: zf.read(i))
        else:
            raise ConversionError(f"{path}: not a folder or a zip file")

    exports = [groups[k] for k in sorted(groups)]
    exports = [g for g in exports if "drive-progress.csv" in g or "charge-progress.csv" in g]
    if not exports:
        raise ConversionError(
            "no Teslascope export found (expected drive-progress.csv and/or "
            "charge-progress.csv). Export the 'Drive Progress' and 'Charge "
            "Progress' data types from Teslascope.")
    return exports


def _vehicle(exports: list[dict[str, str]], vin: str | None) -> dict:
    vehicles = {}
    for files in exports:
        for v in _rows(files.get("vehicle.csv", "")):
            if v.get("VIN"):
                vehicles.setdefault(v["VIN"], v)
    if vin:
        if vehicles and vin not in vehicles:
            raise ConversionError(f"VIN {vin} not found in vehicle.csv ({', '.join(vehicles)})")
        return vehicles.get(vin, {"VIN": vin, "Name": ""})
    if not vehicles:
        raise ConversionError("no vehicle.csv with a VIN in the export: pass --vin")
    if len(vehicles) > 1:
        raise ConversionError(
            f"the export holds several vehicles ({', '.join(vehicles)}): "
            "export one vehicle at a time or pass --vin")
    return next(iter(vehicles.values()))


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def _int(value: str) -> str:
    """TeslaMate rejects '3.0' in integer columns: round to an integer."""
    try:
        return str(int(round(float(value))))
    except ValueError:
        return "0"


def _valid(value: str) -> str:
    return "" if value == "<invalid>" else value


def convert(paths: list[str], vin: str | None = None, vehicle_id: str = "1",
            car_type: str = "model3") -> tuple[dict[str, list[dict]], dict]:
    """Return ({TeslaFi file name: rows}, stats)."""
    exports = _find_exports(paths)
    vehicle = _vehicle(exports, vin)
    vin = vehicle["VIN"]

    def base(ts: str) -> dict:
        return {"Date": ts, "vin": vin, "vehicle_id": vehicle_id, "id": "1",
                "display_name": vehicle.get("Name", ""), "car_type": car_type,
                "state": "online"}

    events = []  # (timestamp, group, kind, row)
    for files in exports:
        for p in _rows(files.get("drive-progress.csv", "")):
            row = base(p["Created At"])
            row.update({
                "shift_state": p["Shift State"], "latitude": p["Latitude"],
                "longitude": p["Longitude"], "heading": p["Heading"],
                "speed": p["Speed"], "power": _int(p["Power"]),
                "odometer": p["Odometer"], "battery_level": p["Battery Level"],
                "usable_battery_level": p["Usable Battery Level"],
                "battery_range": p["Battery Range"],
                "ideal_battery_range": p["Battery Range"],
                "est_battery_range": p["Estimated Battery Range"],
                "inside_temp": p["Inside Temperature"],
                "outside_temp": p["Outside Temperature"],
                "fan_status": _int(p["Fan Status"]),
                "is_climate_on": p["Is Climate On?"],
                "charging_state": "Disconnected",
            })
            events.append((p["Created At"], "d" + p["Drive ID"], "d", row))

        charges = {c["ID"]: c for c in _rows(files.get("charges.csv", ""))}
        for p in _rows(files.get("charge-progress.csv", "")):
            c = charges.get(p["Charge ID"], {})
            row = base(p["Created At"])
            row.update({
                "shift_state": "", "latitude": c.get("Latitude", ""),
                "longitude": c.get("Longitude", ""), "speed": "", "power": "0",
                "battery_level": p["Battery Level"],
                "usable_battery_level": p["Usable Battery Level"],
                "battery_range": p["Battery Range"],
                "ideal_battery_range": p["Battery Range"],
                "est_battery_range": p["Estimated Battery Range"],
                "charging_state": p["Charging State"],
                "charge_energy_added": p["Charge Energy Added"],
                "charge_limit_soc": p["Charge Limit (SoC)"],
                "charger_power": _int(p["Charger Power"]),
                "charger_voltage": _int(p["Charger Voltage"]),
                "charge_rate": p["Charge Rate"],
                "conn_charge_cable": p["Connection Cable"],
                "fast_charger_present": p["Fast Charger Present?"],
                "fast_charger_brand": _valid(p["Fast Charger Brand"]),
                "fast_charger_type": _valid(p["Fast Charger Type"]),
                "charge_port_door_open": p["Charge Port Door Open"],
                "charge_port_latch": p["Charge Port Latch"],
                "time_to_full_charge": p["Time To Full Charge"],
            })
            events.append((p["Created At"], "c" + p["Charge ID"], "c", row))

    if not events:
        raise ConversionError("the export holds no drive or charge points")
    events.sort(key=lambda e: (e[0], e[1]))

    out: list[dict] = []
    odometer = ""
    sessions = set()
    synthetic = 0
    for i, (ts, group, kind, row) in enumerate(events):
        # Charge points carry no odometer: reuse the last one seen on a drive.
        if kind == "d":
            odometer = row["odometer"]
        else:
            row = dict(row, odometer=odometer)
        sessions.add(group)
        out.append(row)

        nxt = events[i + 1] if i + 1 < len(events) else None
        if nxt is not None and nxt[1] == group:
            continue
        t = datetime.strptime(ts, DATE_FMT)
        if nxt is not None and datetime.strptime(nxt[0], DATE_FMT) <= t + CLOSE_GAP:
            continue
        parked = dict(row, shift_state="", speed="", power="0",
                      charging_state="Disconnected", charger_power="0",
                      charge_rate="", charge_port_latch="",
                      charge_port_door_open="0",
                      Date=(t + timedelta(seconds=60)).strftime(DATE_FMT))
        asleep = dict(parked, state="asleep",
                      Date=(t + timedelta(seconds=120)).strftime(DATE_FMT))
        out += [parked, asleep]
        synthetic += 2

    files: dict[str, list[dict]] = defaultdict(list)
    for row in out:
        year, month = row["Date"][0:4], int(row["Date"][5:7])
        files[f"TeslaFi{month}{year}.csv"].append(row)

    stats = {
        "vin": vin, "points": len(events), "rows": len(out),
        "synthetic_rows": synthetic,
        "drives": sum(1 for s in sessions if s.startswith("d")),
        "charges": sum(1 for s in sessions if s.startswith("c")),
        "first": events[0][0], "last": events[-1][0], "files": len(files),
    }
    return dict(files), stats


def write(files: dict[str, list[dict]], outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for name, rows in files.items():
        with open(os.path.join(outdir, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Convert a Teslascope export into TeslaFi CSV files for TeslaMate's importer.")
    ap.add_argument("exports", nargs="+", help="Teslascope export .zip files or extracted folders")
    ap.add_argument("-o", "--output", default="teslamate-import",
                    help="output folder (default: teslamate-import)")
    ap.add_argument("--vin", help="vehicle to convert when the export holds several")
    ap.add_argument("--vehicle-id", default="1",
                    help="value of the vehicle_id column (default: 1). If the car already "
                         "exists in TeslaMate, use its cars.vid")
    ap.add_argument("--car-type", default="model3",
                    help="model written to TeslaMate when it creates the car (default: model3)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    try:
        files, stats = convert(args.exports, args.vin, args.vehicle_id, args.car_type)
    except (ConversionError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    write(files, args.output)
    print(f"{stats['drives']} drives, {stats['charges']} charges, "
          f"{stats['points']} points from {stats['first']} to {stats['last']} (UTC)")
    print(f"wrote {stats['rows']} rows ({stats['synthetic_rows']} synthetic) "
          f"in {stats['files']} files to {args.output}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
