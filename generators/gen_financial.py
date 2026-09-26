"""
CrimeNet AI — Financial Transactions Generator
Generates synthetic financial transactions linked to FIR accounts & mobiles
Output: data/raw/financial_txns.csv
"""

import pandas as pd
import random
from datetime import datetime, timedelta

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

FIR_FILE    = "data/raw/fir_500.csv"
OUTPUT_FILE = "data/raw/financial_txns.csv"
TXN_COUNT   = 2000

START_DATE  = datetime(2025, 1, 1)
END_DATE    = datetime(2026, 9, 15)

TXN_TYPES   = ["UPI", "NEFT", "RTGS", "IMPS", "Cash Deposit", "Cash Withdrawal", "Cheque"]
TXN_W       = [35, 20, 10, 15, 8, 8, 4]

BANKS = [
    "SBI", "Canara Bank", "Indian Bank", "UCO Bank",
    "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Bank",
    "Federal Bank", "South Indian Bank", "Karnataka Bank",
]

SUSPICIOUS_FLAGS = [
    "Multiple small transfers (structuring)",
    "Round-number transaction",
    "Rapid in-out movement",
    "Cross-state transfer",
    "Unusual hours transfer",
    "New account high value",
    None, None, None, None, None, None,   # majority unflagged
]

AMT_PROFILES = {
    "small":  (500,    15000),
    "medium": (15001,  150000),
    "large":  (150001, 2000000),
}
AMT_W = [50, 35, 15]


def random_datetime(start, end):
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def random_amount():
    profile = random.choices(["small", "medium", "large"], weights=AMT_W, k=1)[0]
    lo, hi = AMT_PROFILES[profile]
    amt = random.randint(lo, hi)
    # 20% chance of round number (suspicious)
    if random.random() < 0.20:
        amt = round(amt, -3)
    return amt


def load_fir_entities(fir_file):
    try:
        df = pd.read_csv(fir_file)
    except FileNotFoundError:
        print(f"[WARN] {fir_file} not found — using fallback pools")
        accounts = [f"SYN-ACC-{100001 + i}" for i in range(150)]
        mobiles  = [str(9000000001 + i) for i in range(300)]
        return accounts, mobiles

    accounts = set()
    mobiles  = set()
    for _, row in df.iterrows():
        acc = str(row.get("Account_Number", "NULL")).strip()
        if acc not in ("NULL", "nan", ""):
            accounts.add(acc)
        for col in ["Suspect_Mobile", "Associate_Mobile", "Complainant_Mobile"]:
            m = str(row.get(col, "NULL")).strip()
            if m not in ("NULL", "nan", ""):
                mobiles.add(m)

    return list(accounts), list(mobiles)


def generate_transactions(accounts, mobiles, count):
    records = []

    # Weight accounts — some are mule accounts (high frequency)
    mule_accounts = random.sample(accounts, min(30, len(accounts)))
    acc_weights = [5 if a in mule_accounts else 1 for a in accounts]

    txn_id = 1
    while len(records) < count:
        # Sender
        if random.random() < 0.65 and accounts:
            sender_acc = random.choices(accounts, weights=acc_weights, k=1)[0]
        else:
            sender_acc = f"EXT-ACC-{random.randint(200000, 299999)}"

        # Receiver
        if random.random() < 0.65 and accounts:
            receiver_acc = random.choices(accounts, weights=acc_weights, k=1)[0]
            while receiver_acc == sender_acc:
                receiver_acc = random.choices(accounts, weights=acc_weights, k=1)[0]
        else:
            receiver_acc = f"EXT-ACC-{random.randint(300000, 399999)}"

        txn_type  = random.choices(TXN_TYPES, weights=TXN_W, k=1)[0]
        amount    = random_amount()
        ts        = random_datetime(START_DATE, END_DATE)
        bank      = random.choice(BANKS)
        mobile    = random.choice(mobiles) if (mobiles and random.random() < 0.75) else "NULL"
        flag      = random.choice(SUSPICIOUS_FLAGS)

        # Force suspicious flag for mule accounts
        if sender_acc in mule_accounts or receiver_acc in mule_accounts:
            if random.random() < 0.45:
                flag = random.choice([f for f in SUSPICIOUS_FLAGS if f])

        records.append({
            "TXN_ID":            f"TXN-{txn_id:05d}",
            "Sender_Account":    sender_acc,
            "Receiver_Account":  receiver_acc,
            "Transaction_Type":  txn_type,
            "Amount_INR":        amount,
            "Transaction_DateTime": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "Bank":              bank,
            "Mobile_Ref":        mobile,
            "Suspicious_Flag":   flag if flag else "None",
            "Source":            "Financial",
        })
        txn_id += 1

    return records


def main():
    print("[Financial Generator] Starting...")
    accounts, mobiles = load_fir_entities(FIR_FILE)
    print(f"[Financial Generator] Loaded {len(accounts)} accounts, {len(mobiles)} mobiles from FIR")

    records = generate_transactions(accounts, mobiles, TXN_COUNT)
    df = pd.DataFrame(records)
    df.to_csv(OUTPUT_FILE, index=False)

    flagged = df[df["Suspicious_Flag"] != "None"]
    print(f"[Financial Generator] Generated {len(df)} transactions")
    print(f"[Financial Generator] Suspicious transactions: {len(flagged)}")
    print(f"[Financial Generator] Saved to {OUTPUT_FILE}")
    print(f"[Financial Generator] Sample:\n{df.head(3).to_string()}")


if __name__ == "__main__":
    main()
