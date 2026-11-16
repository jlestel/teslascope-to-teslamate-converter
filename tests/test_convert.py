import csv
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import teslascope2teslamate as t2t  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "export")


class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_folder_export(self):
        files, stats = t2t.convert([FIXTURE])
        self.assertEqual(list(files), ["TeslaFi12024.csv"])
        self.assertEqual(stats["drives"], 1)
        self.assertEqual(stats["charges"], 1)
        self.assertEqual(stats["points"], 9)
        # each session gets a "parked" and an "asleep" row
        self.assertEqual(stats["synthetic_rows"], 4)
        rows = files["TeslaFi12024.csv"]
        self.assertEqual([r["Date"] for r in rows], sorted(r["Date"] for r in rows))
        self.assertTrue(all(r["vin"] == "TESTVIN0000000001" for r in rows))

    def test_integer_fields_are_rounded(self):
        files, _ = t2t.convert([FIXTURE])
        rows = files["TeslaFi12024.csv"]
        charging = [r for r in rows if r["charging_state"] == "Charging"]
        self.assertEqual({r["charger_power"] for r in charging}, {"11"})
        self.assertEqual({r["charger_voltage"] for r in charging}, {"230"})
        self.assertEqual(rows[0]["power"], "12")
        self.assertEqual(charging[0]["fast_charger_brand"], "")

    def test_charge_rows_reuse_last_odometer(self):
        files, _ = t2t.convert([FIXTURE])
        charging = [r for r in files["TeslaFi12024.csv"] if r["charging_state"] == "Charging"]
        self.assertEqual(charging[0]["odometer"], "1003.200000")

    def test_session_is_closed(self):
        files, _ = t2t.convert([FIXTURE])
        rows = files["TeslaFi12024.csv"]
        self.assertEqual(rows[-2]["charging_state"], "Disconnected")
        self.assertEqual(rows[-2]["Date"], "2024-01-01 10:04:00")
        self.assertEqual(rows[-1]["state"], "asleep")

    def test_zip_export_and_cli(self):
        zpath = os.path.join(self.tmp, "export.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            for name in os.listdir(FIXTURE):
                zf.write(os.path.join(FIXTURE, name), f"teslascope-export-1/{name}")
        out = os.path.join(self.tmp, "out")
        self.assertEqual(t2t.main([zpath, "-o", out]), 0)
        with open(os.path.join(out, "TeslaFi12024.csv"), newline="") as fh:
            reader = csv.DictReader(fh)
            self.assertEqual(reader.fieldnames, t2t.COLUMNS)
            self.assertEqual(len(list(reader)), 13)

    def test_vin_mismatch(self):
        with self.assertRaises(t2t.ConversionError):
            t2t.convert([FIXTURE], vin="OTHERVIN000000001")

    def test_empty_input(self):
        with self.assertRaises(t2t.ConversionError):
            t2t.convert([self.tmp])


if __name__ == "__main__":
    unittest.main()
