"""
CrimeNet AI — Social Media Posts Generator
Generates synthetic social media activity mentioning suspects/locations
Output: data/raw/social_media.csv
"""

import pandas as pd
import random
from datetime import datetime, timedelta

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

FIR_FILE    = "data/raw/fir_500.csv"
OUTPUT_FILE = "data/raw/social_media.csv"
POST_COUNT  = 1000

START_DATE  = datetime(2025, 1, 1)
END_DATE    = datetime(2026, 9, 15)

PLATFORMS   = ["Twitter/X", "Facebook", "Instagram", "Telegram", "WhatsApp Group", "YouTube Comment"]
PLATFORM_W  = [25, 30, 15, 15, 10, 5]

HANDLE_PREFIXES = [
    "user_", "real_", "the_", "only_", "official_",
    "shadow_", "dark_", "anon_", "xyz_", "temp_",
]

POST_TEMPLATES = [
    "Heard that {name} was spotted near {loc} last night. Anyone know more?",
    "Alert: suspicious activity reported near {loc}. Stay safe everyone.",
    "People are saying {name} is involved in the {loc} incident. Not confirmed.",
    "Watch out for a {vehicle} near {loc}. Looked very suspicious.",
    "Someone using number {mobile} has been harassing people in {loc}.",
    "Big money movement spotted from {loc} accounts. Something is off.",
    "The group operating near {loc} is getting bolder. Someone needs to act.",
    "Rumour: {name} and associates were seen leaving {loc} late at night.",
    "Anyone else getting calls from {mobile}? Feels like a scam.",
    "New gang activity in {loc}. Be careful near {landmark}.",
    "Financial irregularities linked to {loc} area. Multiple accounts flagged.",
    "{name} mentioned in connection with recent incidents. People are talking.",
    "Suspicious vehicle {vehicle} seen circling {loc} multiple times.",
    "Our community group got a threat message from {mobile}. Reporting this.",
    "Something big happened near {loc} — police cars everywhere last night.",
    "Word on the street: {name} controls the operation in {loc} area.",
    "Multiple complaints about {mobile} in our locality. Scam alert!",
    "The {vehicle} linked to that incident was seen near {loc} again today.",
    "Posting this for awareness: fraud calls coming from {mobile}.",
    "Residents of {loc} be careful — strangers asking suspicious questions.",
]

LANDMARKS = [
    "the main bus stand", "the market junction", "the railway crossing",
    "the old warehouse", "the industrial estate", "the petrol bunk",
    "the highway flyover", "the shopping complex", "the college gate",
    "the ATM near the post office",
]

SENTIMENT = ["Neutral", "Concerned", "Alarmed", "Informational", "Suspicious"]
SENT_W    = [30, 30, 15, 15, 10]


def random_datetime(start, end):
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def make_handle(name):
    parts = name.lower().split()
    base  = parts[0] if parts else "user"
    prefix = random.choice(HANDLE_PREFIXES)
    suffix = random.randint(10, 999)
    return f"@{prefix}{base}{suffix}"


def load_fir_entities(fir_file):
    try:
        df = pd.read_csv(fir_file)
    except FileNotFoundError:
        print(f"[WARN] {fir_file} not found — using fallback data")
        names    = ["Ravi Kumar", "Senthil Krishnan", "Murugan Pandian"]
        mobiles  = [str(9000000001 + i) for i in range(100)]
        vehicles = [f"TN-38-XX-{1001+i}" for i in range(50)]
        locs     = ["Market Road", "Bus Stand Area", "Industrial Area"]
        return names, mobiles, vehicles, locs

    names, mobiles, vehicles, locs = set(), set(), set(), set()
    for _, row in df.iterrows():
        for col in ["Suspect_Name", "Associate_Name"]:
            n = str(row.get(col, "NULL")).strip()
            if n not in ("NULL", "Unknown", "nan", ""):
                names.add(n)
        for col in ["Suspect_Mobile", "Associate_Mobile"]:
            m = str(row.get(col, "NULL")).strip()
            if m not in ("NULL", "nan", ""):
                mobiles.add(m)
        vn = str(row.get("Vehicle_Number", "NULL")).strip()
        if vn not in ("NULL", "nan", ""):
            vehicles.add(vn)
        loc = str(row.get("Incident_Location", "NULL")).strip()
        if loc not in ("NULL", "nan", ""):
            locs.add(loc)

    return list(names), list(mobiles), list(vehicles), list(locs)


def generate_posts(names, mobiles, vehicles, locs, count):
    records = []
    post_id = 1

    # High-activity users — post multiple times (like informants / gossip accounts)
    num_active = max(10, count // 20)
    active_handles = [make_handle(random.choice(names)) for _ in range(num_active)]

    while len(records) < count:
        template = random.choice(POST_TEMPLATES)

        name    = random.choice(names)    if names    else "Unknown"
        mobile  = random.choice(mobiles)  if mobiles  else "9000000000"
        vehicle = random.choice(vehicles) if vehicles else "TN-00-XX-0000"
        loc     = random.choice(locs)     if locs     else "Market Area"
        landmark = random.choice(LANDMARKS)

        text = template.format(
            name=name, mobile=mobile,
            vehicle=vehicle, loc=loc, landmark=landmark
        )

        # 30% from active handles, 70% random new
        if random.random() < 0.30:
            handle = random.choice(active_handles)
        else:
            handle = make_handle(random.choice(names))

        platform  = random.choices(PLATFORMS, weights=PLATFORM_W, k=1)[0]
        ts        = random_datetime(START_DATE, END_DATE)
        sentiment = random.choices(SENTIMENT, weights=SENT_W, k=1)[0]

        # Extract mentioned entities for later linking
        mentions_name    = name    if name    in text else "NULL"
        mentions_mobile  = mobile  if mobile  in text else "NULL"
        mentions_vehicle = vehicle if vehicle in text else "NULL"

        records.append({
            "POST_ID":           f"POST-{post_id:05d}",
            "Platform":          platform,
            "Handle":            handle,
            "Post_Text":         text,
            "Post_DateTime":     ts.strftime("%Y-%m-%d %H:%M:%S"),
            "Sentiment":         sentiment,
            "Mentioned_Name":    mentions_name,
            "Mentioned_Mobile":  mentions_mobile,
            "Mentioned_Vehicle": mentions_vehicle,
            "Mentioned_Location": loc,
            "Source":            "SocialMedia",
        })
        post_id += 1

    return records


def main():
    print("[Social Media Generator] Starting...")
    names, mobiles, vehicles, locs = load_fir_entities(FIR_FILE)
    print(f"[Social Media Generator] Entities — Names:{len(names)} Mobiles:{len(mobiles)} Vehicles:{len(vehicles)} Locs:{len(locs)}")

    records = generate_posts(names, mobiles, vehicles, locs, POST_COUNT)
    df = pd.DataFrame(records)
    df.to_csv(OUTPUT_FILE, index=False)

    print(f"[Social Media Generator] Generated {len(df)} posts")
    print(f"[Social Media Generator] Saved to {OUTPUT_FILE}")
    print(f"[Social Media Generator] Platforms:\n{df['Platform'].value_counts().to_string()}")


if __name__ == "__main__":
    main()
