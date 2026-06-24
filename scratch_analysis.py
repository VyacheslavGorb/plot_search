import json
from pathlib import Path

geocoded_dir = Path("data/geocoded")
files = list(geocoded_dir.glob("*.json"))

total = len(files)
success = 0
subdivided = 0
unsubdivided = 0
unknown = 0
failures = 0

for f in files:
    with open(f, 'r') as fp:
        data = json.load(fp)
        
    if data.get("geocoding_successful"):
        success += 1
        is_unsub = data.get("is_unsubdivided")
        if is_unsub is False:
            subdivided += 1
        elif is_unsub is True:
            unsubdivided += 1
        else:
            unknown += 1
    else:
        failures += 1

print(f"Total processed: {total}")
print(f"Geocoding Successful (Polygon Found): {success} ({(success/total)*100:.1f}%)")
if success > 0:
    print(f"  - Perfect Match (Subdivided): {subdivided} ({(subdivided/total)*100:.1f}% of total, {(subdivided/success)*100:.1f}% of successes)")
    print(f"  - Area Mismatch (Unsubdivided): {unsubdivided} ({(unsubdivided/total)*100:.1f}% of total, {(unsubdivided/success)*100:.1f}% of successes)")
    print(f"  - Unknown area match: {unknown}")
print(f"Geocoding Failed (No Polygon): {failures} ({(failures/total)*100:.1f}%)")
