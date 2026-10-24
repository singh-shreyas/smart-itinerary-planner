"""Convert the team's destination spreadsheet into data/catalog/destinations.csv.

    python scripts/import_catalog.py ~/Downloads/India_200_Tourist_Destinations_Attractions.xlsx

The spreadsheet lists 200 Indian destinations and their famous attractions by
NAME only (no coordinates, hours or fees). The app shows it on the Cities page
as the catalog the four fully modelled cities were chosen from.

Uses only the standard library: an .xlsx file is a zip of XML documents.
"""

import csv
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "catalog", "destinations.csv")


def read_sheet(path, sheet="xl/worksheets/sheet1.xml"):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        rows = []
        for row in ET.fromstring(z.read(sheet)).find("m:sheetData", NS).findall("m:row", NS):
            values = []
            for cell in row.findall("m:c", NS):
                v = cell.find("m:v", NS)
                if v is None:
                    inline = cell.find("m:is", NS)
                    values.append("".join(t.text or "" for t in inline.iter(f"{{{NS['m']}}}t")) if inline is not None else "")
                elif cell.get("t") == "s":
                    values.append(shared[int(v.text)])
                else:
                    values.append(v.text)
            rows.append(values)
        return rows


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 1
    rows = read_sheet(os.path.expanduser(argv[1]))
    header, body = rows[0], rows[1:]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["destination_id", "region", "state_ut", "destination", "attractions",
                         "attraction_count", "state_rank_domestic_visits_2024"])
        for r in body:
            r = (r + [""] * len(header))[:len(header)]
            if not r[0]:
                continue
            attractions = [a.strip() for a in r[4].split(";") if a.strip()]
            writer.writerow([int(float(r[0])), r[1], r[2], r[3], "; ".join(attractions), len(attractions),
                             int(float(r[5])) if r[5].replace(".", "").isdigit() else ""])
    print(f"wrote {len(body)} destinations to {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
