"""
CrimeNet AI — CDR (Call Detail Records) Generator
Generates synthetic call logs linked to FIR mobile numbers
Output: data/raw/cdr_logs.csv
"""

import pandas as pd
import random
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

FIR_FILE      = "data/raw/fir_500.csv"
OUTPUT_FILE   = "data/raw/cdr_logs.csv"
CDR_COUNT     = 3000   # total call records to generate

START_DATE    = datetime(2025, 1, 1)
END_DATE      = datetime(2026, 9, 15)

CALL_TYPES    = ["Incoming", "Outgoing", "Missed"]
CALL_W        = [35, 45, 20]

TOWERS = [
    "TOWER-ERD-001", "TOWER-ERD-002", "TOWER-CBE-001", "TOWER-CBE-002",
    "TOWER-CHN-001", "TOWER-CHN-002", "TOWER-SLM-001", "TOWER-MDU-001",
    "TOWER-TUP-001", "TOWER-TRY-001", "TOWER-VLR-001", "TOWER-NKL-001",
    "TOWER-KRR-001", "TOWER-DGL-001", "TOWER-TNJ-001", "TOWER-TVL-001",
]

DISTRICT_TOWER = {
    "Erode": ["TOWER-ERD-001", "TOWER-ERD-002"],
    "Coimbatore": ["TOWER-CBE-001", "TOWER-CBE-002"],
    "Chennai": ["TOWER-CHN-001", "TOWER-CHN-002"],
    "Salem": ["TOWER-SLM-001"],
    "Madurai": ["TOWER-MDU-001"],
    "Tiruppur": ["TOWER-TUP-001"],
    "Trichy": ["TOWER-TRY-001"],
    "Vellore": ["TOWER-VLR-001"],
    "Namakkal": ["TOWER-NKL-001"],
    "Karur": ["TOWER-KRR-001"],
    "Dindigul": ["TOWER-DGL-001"],
    "Thanjavur": ["TOWER-TNJ-001"],
    "Tirunelveli": ["TOWER-TVL-001"],
}


def random_datetime(start, end):
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def random_duration(call_type):
    if call_type == "Missed":
        return 0
    if call_type == "Incoming":
        return random.randint(10, 900)
    return random.randint(15, 1200)


def load_fir_mobiles(fir_file):
    try:
        df = pd.read_csv(fir_file)
    except FileNotFoundError:
        print(f"[WARN] {fir_file} not found — using fallback mobile pool")
        return [str(n) for n in range(9000000001, 9000000201)]

    mobile_cols = [
        "Complainant_Mobile", "Victim_Mobile",
        "Suspect_Mobile", "Associate_Mobile", "Witness_Mobile"
    ]
    mobiles = set()
    district_map = {}
    for _, row in df.iterrows():
        dist = row.get("District", "Erode")
        for col in mobile_cols:
            m = str(row.get(col, "NULL")).strip()
            if m not in ("NULL", "nan", ""):
                mobiles.add(m)
                district_map[m] = dist
    return list(mobiles), district_map


def get_tower(mobile, district_map):
    dist = district_map.get(mobile, "Erode")
    towers = DISTRICT_TOWER.get(dist, TOWERS)
    # 80% same tower, 20% random roaming
    if random.random() < 0.8:
        return random.choice(towers)
    return random.choice(TOWERS)


def generate_cdrs(mobiles, district_map, count):
    records = []

    # Build a weighted pool — suspects call more
    pool = mobiles[:]
    weights = []
    for m in pool:
        # Numbers in higher range appear more (suspects in gen_fir use 9000000300+)
        n = int(m)
        if n > 9000000300:
            weights.append(4)
        elif n > 9000000200:
            weights.append(2)
        else:
            weights.append(1)

    cdr_id = 1
    while len(records) < count:
        # Pick caller
        caller = random.choices(pool, weights=weights, k=1)[0]

        # 70% call within mobile pool, 30% call unknown external
        if random.random() < 0.70:
            callee = random.choices(pool, weights=weights, k=1)[0]
            while callee == caller:
                callee = random.choices(pool, weights=weights, k=1)[0]
        else:
            callee = str(random.randint(7000000000, 9999999999))

        call_type = random.choices(CALL_TYPES, weights=CALL_W, k=1)[0]
        duration  = random_duration(call_type)
        ts        = random_datetime(START_DATE, END_DATE)
        tower     = get_tower(caller, district_map)

        records.append({
            "CDR_ID":         f"CDR-{cdr_id:05d}",
            "Caller_Mobile":  caller,
            "Callee_Mobile":  callee,
            "Call_Type":      call_type,
            "Call_DateTime":  ts.strftime("%Y-%m-%d %H:%M:%S"),
            "Duration_Sec":   duration,
            "Cell_Tower":     tower,
            "Source":         "CDR",
        })
        cdr_id += 1

    return records


def main():
    print("[CDR Generator] Starting...")
    result = load_fir_mobiles(FIR_FILE)
    if isinstance(result, tuple):
        mobiles, district_map = result
    else:
        mobiles, district_map = result, {}

    print(f"[CDR Generator] Loaded {len(mobiles)} unique mobiles from FIR dataset")

    records = generate_cdrs(mobiles, district_map, CDR_COUNT)
    df = pd.DataFrame(records)
    df.to_csv(OUTPUT_FILE, index=False)

    print(f"[CDR Generator] Generated {len(df)} CDR records")
    print(f"[CDR Generator] Saved to {OUTPUT_FILE}")
    print(f"[CDR Generator] Sample:\n{df.head(3).to_string()}")


if __name__ == "__main__":
    main()
