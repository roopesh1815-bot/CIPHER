# Operator demo flow

## Before the presentation

1. Create and activate the project virtual environment and install
   `requirements.txt` as described in the README.
2. Set a unique `CIPHER_SECRET_KEY` in a local `.env` file. Never use the
   development fallback for a live or externally accessible demo.
3. Provision a unique active demo account and confirm its role and case
   memberships. No guaranteed demo credentials are documented.
4. Start the app with:

   ```powershell
   .\venv\Scripts\python.exe -m uvicorn api.main:app --reload
   ```

5. Confirm the configured production data/artifacts and synthetic ML run
   already exist. Do not run data generators or the production pipeline
   during the presentation.

## Click-through

1. Open `/login` and authenticate using the provisioned account.
2. Open the Dashboard at `/`. Explain that global analytic signals support
   review and do not determine guilt or intent.
3. Open Case Manager at `/cases`.
4. Register a case or select a pre-existing case to which the account has
   access. For a prepared demo, prefer a pre-existing case with authorized
   records rather than creating production data during the presentation.
5. Show case membership/protection: case details and documents are not
   available to an investigator without appropriate membership or a scoped
   grant.
6. Show the Case Vault document list and, if prepared, an upload/download.
   The UI reports OCR unavailable; do not claim OCR processing.
7. Show a minimal related-case reference. Explain that it indicates possible
   relevance but does not disclose the source document. A requester submits
   an access request; the source handler/Admin approves or rejects it.
8. If the demo account is the source handler/Admin, show selection of
   individual documents, the time-limited grant, and revocation controls.
9. Open the case Spider-Web from the selected case. Explain that the central
   node and radial arrangement are visualization choices, not changes to the
   underlying relationship records.
10. Open `/network-graph` for the global graph and explain that the displayed
    edges are built from source records.
11. Open `/key-influencers` and describe centrality/influence metrics as
    deterministic graph measures.
12. Open `/communities` and describe the graph-theoretic community output.
13. Open `/risk-scoring` and `/alerts`. Explain that risk tiers and anomaly
    alerts are fixed-weight/rule/statistical review signals. The temporal
    alert uses the implemented three-distinct-FIRs-in-90-days rule.
14. Open `/hidden-links`. Describe results as **deterministic
    graph-similarity suggestions** using Jaccard and Adamic–Adar. They are
    not ML, are not observed source relationships, and require review.
15. Open `/ml-demo` directly. Explain:
    - the dataset and IDs are controlled and synthetic;
    - the model is supervised `StandardScaler` + `LogisticRegression`;
    - the test period is chronologically held out;
    - evaluation is compared with an independent Adamic–Adar baseline;
    - current results are weak and near baseline;
    - each result uses `ML_SUGGESTED_UNCONFIRMED`;
    - synthetic performance does not establish real-world predictive validity.
16. Use `/auth/logout` and verify the browser is returned to the login page.

## Recommended presentation narrative

“CIPHER brings multiple investigative record types into a source-aware
relationship graph and presents graph, community, temporal, and rule-based
signals for investigator review. Case records remain protected by membership
checks, and cross-case discovery exposes a minimal reference before any
document access request is reviewed. Separately, CIPHER includes a controlled
synthetic ML experiment. Its predictions remain isolated from observed
relationships, and its current performance is weak and close to the
Adamic–Adar baseline.”

## Claims to avoid

- Do not claim guilt, criminality, intent, or wrongdoing prediction.
- Do not claim the synthetic ML results establish real-world predictive
  validity.
- Do not call deterministic Jaccard/Adamic–Adar suggestions machine learning.
- Do not present suggested pairs as observed, proven, or confirmed links.
- Do not claim working OCR; document uploads currently report OCR unavailable.
- Do not claim automatic cross-case exposure; document access requires an
  approved, scoped grant.
- Do not claim encryption at rest.
