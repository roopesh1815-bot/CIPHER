"""
CrimeNet AI — Graph Builder
Builds a NetworkX graph from extracted entities + relationships
Nodes = entities, Edges = relationships between them
"""

import pandas as pd
import networkx as nx


def build_graph(entities_path: str, fir_path: str,
                cdr_path: str, fin_path: str) -> nx.Graph:

    G = nx.Graph()
    entities = pd.read_csv(entities_path)

    # ── 1. Add all entities as nodes ──────────────────────────
    for _, row in entities.iterrows():
        cid   = row["Canonical_ID"]
        etype = row["Entity_Type"]
        val   = row["Entity_Value"]
        G.add_node(cid,
            label        = val,
            entity_type  = etype,
            mobile       = str(row.get("Mobile", "NULL")),
            sources      = str(row.get("Sources", "")),
            source_count = int(row.get("Source_Count", 1)),
            cross_verified = bool(row.get("Cross_Verified", False)),
            fusion_badge = str(row.get("Fusion_Badge", "📄 Single-Source")),
            risk_hint    = str(row.get("Risk_Hint", "")),
            roles        = str(row.get("Roles", "")),
            fir_count    = int(row.get("FIR_Count", 0)),
            cdr_count    = int(row.get("CDR_Count", 0)),
            fin_count    = int(row.get("Fin_Count", 0)),
            soc_count    = int(row.get("Soc_Count", 0)),
            first_seen   = str(row.get("First_Seen", "")),
            last_seen    = str(row.get("Last_Seen", "")),
        )

    # Helper: canonical_id lookup by value
    val_to_cid = {}
    for _, row in entities.iterrows():
        val_to_cid[str(row["Entity_Value"]).strip().title()] = row["Canonical_ID"]
        mob = str(row.get("Mobile", "NULL")).strip()
        if mob not in ("NULL", "nan", ""):
            val_to_cid[mob] = row["Canonical_ID"]

    def get_cid(val):
        return val_to_cid.get(str(val).strip().title()) or val_to_cid.get(str(val).strip())

    related_firs = []

    def add_edge(a, b, rel_type, weight=1.0, source="FIR", date="", event_id=None):
        if a and b and a != b and G.has_node(a) and G.has_node(b):
            event = {"rel_type": rel_type, "source": source}
            if date and str(date).strip().casefold() not in {"nan", "none"}:
                event["date"] = str(date)
            if event_id and str(event_id).strip().casefold() not in {"nan", "none"}:
                event["source_event_id"] = str(event_id)
            if G.has_edge(a, b):
                G[a][b]["weight"]   += weight
                G[a][b]["sources"]   = G[a][b].get("sources","") + "|" + source
                G[a][b]["events"].append(event)
                if rel_type not in G[a][b]["rel_types"]:
                    G[a][b]["rel_types"].append(rel_type)
            else:
                G.add_edge(a, b,
                    rel_type = rel_type,
                    weight   = weight,
                    source   = source,
                    date     = date,
                    sources  = source,
                    rel_types = [rel_type],
                    events   = [event],
                )

    # ── 2. FIR-based edges ────────────────────────────────────
    fir = pd.read_csv(fir_path)
    for _, row in fir.iterrows():
        date = str(row.get("Incident_Date", ""))
        fir_id = row.get("FIR_ID")

        def fir_cid(col_name, col_mob=None):
            name = str(row.get(col_name, "NULL")).strip().title()
            mob  = str(row.get(col_mob,  "NULL")).strip() if col_mob else None
            if name not in ("Null","Nan","","Unknown"):
                c = get_cid(name)
                if c: return c
            if mob and mob not in ("NULL","Nan",""):
                c = get_cid(mob)
                if c: return c
            return None

        comp_cid  = fir_cid("Complainant_Name", "Complainant_Mobile")
        vic_cid   = fir_cid("Victim_Name",      "Victim_Mobile")
        susp_cid  = fir_cid("Suspect_Name",     "Suspect_Mobile")
        assoc_cid = fir_cid("Associate_Name",   "Associate_Mobile")
        wit_cid   = fir_cid("Witness_Name",     "Witness_Mobile")

        loc  = str(row.get("Incident_Location","")).strip().title()
        vn   = str(row.get("Vehicle_Number","NULL")).strip().title()
        acc  = str(row.get("Account_Number","NULL")).strip()

        loc_cid  = get_cid(loc)  if loc  not in ("Null","Nan","") else None
        veh_cid  = get_cid(vn)   if vn   not in ("Null","Nan","None","Null") else None
        acc_cid  = get_cid(acc)  if acc  not in ("NULL","nan","") else None

        # Person ↔ Person edges
        add_edge(comp_cid, vic_cid,   "Complainant-Victim",    2.0, "FIR", date, fir_id)
        add_edge(comp_cid, susp_cid,  "Reported-Suspect",      3.0, "FIR", date, fir_id)
        add_edge(susp_cid, assoc_cid, "Suspect-Associate",     3.5, "FIR", date, fir_id)
        add_edge(susp_cid, wit_cid,   "Suspect-Witness",       1.5, "FIR", date, fir_id)
        add_edge(vic_cid,  susp_cid,  "Victim-Suspect",        3.0, "FIR", date, fir_id)
        add_edge(assoc_cid,wit_cid,   "Associate-Witness",     1.0, "FIR", date, fir_id)

        # Person ↔ Location
        for person_cid in [susp_cid, vic_cid, comp_cid]:
            add_edge(person_cid, loc_cid, "Located-At", 1.0, "FIR", date, fir_id)

        # Person ↔ Vehicle
        add_edge(susp_cid,  veh_cid, "Used-Vehicle",    2.0, "FIR", date, fir_id)
        add_edge(assoc_cid, veh_cid, "Used-Vehicle",    1.5, "FIR", date, fir_id)

        # Person ↔ Account
        add_edge(susp_cid, acc_cid, "Linked-Account",   2.5, "FIR", date, fir_id)
        add_edge(vic_cid,  acc_cid, "Victim-Account",   1.5, "FIR", date, fir_id)

        rid = str(row.get("Related_FIR_ID","NULL")).strip()
        if rid.casefold() not in ("null", "nan", "none", ""):
            related_firs.append({
                "fir_id": str(fir_id),
                "related_fir_id": rid,
            })

    G.graph["related_firs"] = related_firs

    # ── 3. CDR-based edges (Mobile ↔ Mobile) ─────────────────
    cdr = pd.read_csv(cdr_path)
    for _, row in cdr.iterrows():
        date    = str(row.get("Call_DateTime",""))
        cdr_id  = row.get("CDR_ID")
        caller  = str(row.get("Caller_Mobile","")).strip()
        callee  = str(row.get("Callee_Mobile","")).strip()
        dur     = int(row.get("Duration_Sec", 0))
        ctype   = str(row.get("Call_Type",""))

        if ctype == "Missed" or dur == 0:
            w = 0.5
        else:
            w = min(3.0, 0.5 + dur / 300)

        a = get_cid(caller)
        b = get_cid(callee)
        add_edge(a, b, "Called", w, "CDR", date, cdr_id)

    # ── 4. Financial-based edges (Account ↔ Account) ─────────
    fin = pd.read_csv(fin_path)
    for _, row in fin.iterrows():
        date   = str(row.get("Transaction_DateTime",""))
        txn_id = row.get("TXN_ID")
        sender = str(row.get("Sender_Account","")).strip()
        recvr  = str(row.get("Receiver_Account","")).strip()
        amt    = float(row.get("Amount_INR", 0))
        flag   = str(row.get("Suspicious_Flag","None"))

        w = min(5.0, 0.5 + amt / 100000)
        if flag != "None":
            w *= 1.5   # boost suspicious transactions

        a = get_cid(sender)
        b = get_cid(recvr)
        add_edge(a, b, "Transferred-To", w, "Financial", date, txn_id)

        # Mobile ↔ Account
        mob = str(row.get("Mobile_Ref","NULL")).strip()
        if mob not in ("NULL","nan",""):
            m_cid = get_cid(mob)
            a_cid = get_cid(sender)
            add_edge(m_cid, a_cid, "Mobile-Account", 1.0, "Financial", date, txn_id)

    # ── 5. Remove self-loops and isolates ─────────────────────
    G.remove_edges_from(nx.selfloop_edges(G))

    print(f"  Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"  Connected components: {nx.number_connected_components(G)}")
    return G


if __name__ == "__main__":
    G = build_graph(
        "data/processed/entities.csv",
        "data/raw/fir_500.csv",
        "data/raw/cdr_logs.csv",
        "data/raw/financial_txns.csv",
    )
    print(f"\nTop 5 nodes by degree:")
    deg = sorted(G.degree(), key=lambda x: x[1], reverse=True)[:5]
    for node, d in deg:
        print(f"  {G.nodes[node].get('label','?')[:30]:<30} degree={d}")
