# CIPHER — AI-Powered Criminal Network Analysis System

CIPHER is an offline-first investigative intelligence prototype for exploring
relationships across FIR, call-detail, financial-transaction, and social-media
records. It combines source-grounded records with deterministic graph and
statistical analysis, and includes a separate controlled synthetic ML
demonstration.

> **Scope:** CIPHER is an investigative intelligence prototype. Analytical
> outputs are intended to support investigator review. They are not proof of
> wrongdoing, guilt, or criminal intent.

## Implemented capabilities

- Multi-source CSV ingestion and structured entity extraction.
- Deterministic entity resolution and source-fusion tags.
- Relationship graph construction with event/source context.
- Graph visualization, centrality/influencer metrics, and community detection.
- Rule/statistical anomaly flags, review-priority scoring, and temporal trends.
- Deterministic hidden-link suggestions using graph similarity (Jaccard and
  Adamic–Adar).
- Case Manager and a per-case protected document vault with membership checks.
- Minimal cross-case reference discovery and handler-approved, scoped,
  time-limited document grants.
- Hash-chained audit events for security-relevant actions.
- An isolated temporal Logistic Regression demonstration trained only on a
  controlled synthetic network dataset.

## Technology

- Python 3.11 (tested environment), FastAPI, Uvicorn, Jinja2.
- SQLite for application, case, access-control, and audit records.
- pandas and NumPy for tabular data; NetworkX and SciPy for graph/statistical
  analysis.
- scikit-learn for the isolated synthetic experiment.
- HTML, CSS, JavaScript, and vis-network for the browser UI and graph views.

## Repository map

```text
api/
  main.py                 FastAPI application, pages, router registration
  routers/                Authentication, cases, vault, graph, and intelligence APIs
  templates/              Server-rendered pages
  static/                 Browser JavaScript and stylesheets
core/                     Configuration, SQLite, auth, case access, audit
pipeline/
  ingestion/              CSV case import
  extraction/             Source extraction, entity resolution, fusion
  graph/                  Graph building, analytics, exports
  intelligence/           Risk, temporal, summaries, link heuristics
generators/               Synthetic production-prototype data generators
data/
  raw/                    Existing source datasets (do not overwrite casually)
  processed/              Production pipeline analytical outputs
  cases/                  Per-case vault material
  db/                     SQLite and backups
  ml_experiment/          Isolated synthetic ML demonstration data
models/ml_experiment/     Isolated versioned ML run artifacts
output/                   Production graph and relationship exports
tests/                    pytest/unittest-compatible regression suite
docs/                     Architecture, operator flow, and project abstract
ml_experiment/            Synthetic-only dataset, training, and evaluation code
```

## Setup (Windows PowerShell)

From the repository root:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `CIPHER_SECRET_KEY` to a unique, private value before
starting the application. The example file contains only a placeholder.
`.env` is ignored by Git; never commit or share it. The application currently
has a development fallback if the variable is absent. Do not use that fallback
for an externally accessible or live demonstration.

Start the local application:

```powershell
.\venv\Scripts\python.exe -m uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000/login`. API documentation is available at
`http://127.0.0.1:8000/docs` while the server is running.

### User prerequisites

There is no documented, dedicated account-provisioning page or guaranteed
demo account. User records are created by `core.auth.create_user`; the login
form requires an existing active user. The `python -m core.auth` module entry
point is a self-test that may create a default Admin account with a known
development password when no such account exists. Do not use that self-test
account for a live or externally accessible demo. Provision a unique local
demo user deliberately and use a non-default password. For example, after
setting `.env`, this prompts for a username/password and creates an Admin user
in the configured local database:

```powershell
.\venv\Scripts\python.exe -c "from getpass import getpass; from core.db import init_db; from core.auth import create_user; init_db(); create_user(input('Username: '), getpass('Password: '), 'Admin')"
```

## Production data and analytical artifacts

The production master pipeline is `pipeline/run_pipeline.py`. It reads the
configured raw datasets, extracts/resolves entities, then writes processed
tables and graph/intelligence outputs under `data/processed/` and `output/`.
Running it refreshes those artifacts. Do not run it as part of ordinary UI
startup or when the integrity of existing output files must be preserved.

The `generators/` scripts create prototype synthetic source data and may
overwrite files under `data/raw/`; they are not required to start the UI when
the configured data and artifacts already exist. Do not run
`generators/gen_all.py` unless you intentionally intend to regenerate inputs.

## Main routes

| Route | Purpose |
|---|---|
| `/login`, `/auth/login` | Browser login |
| `/` | Investigation dashboard |
| `/cases` | Case Manager and access workflow |
| `/network-graph` | Global network visualization |
| `/cases/{fir_id}/graph` | Authorized case-scoped Spider-Web graph |
| `/key-influencers` | Centrality/influencer view |
| `/risk-scoring` | Review-priority scores |
| `/communities` | Graph communities |
| `/alerts` | Anomaly and temporal alerts |
| `/hidden-links` | Deterministic graph-similarity suggestions |
| `/ml-demo` | Isolated synthetic ML demonstration |
| `/auth/logout` | Logout and cookie clearing |

See [docs/demo_flow.md](docs/demo_flow.md) for an operator sequence and
[docs/architecture.md](docs/architecture.md) for data flow and trust boundaries.

## Authentication and case security

Browser sessions use an HTTP-only JWT cookie; authenticated API clients may
use a bearer token. The active-user check consults the SQLite user record.
Case views and protected document operations apply case membership checks;
Admin-specific actions are separately restricted.

Related-case references disclose only minimal reference metadata. They do not
automatically grant access to the source case's documents. Access requests are
reviewed by the source case handler (or Admin); approval grants selected
documents for a limited period, and grant use checks current requester
membership, scope, expiry, and revocation. Security-relevant actions are
recorded in a hash-chained audit table.

The vault uses per-case filesystem paths and authorization checks. This
prototype does not claim encryption at rest. Document upload is implemented,
but OCR currently reports unavailable; no OCR processing capability should be
assumed.

## Analytical outputs and the synthetic ML experiment

Observed/source-recorded relationships are built from source event records.
Centrality, communities, risk priorities, anomaly flags, temporal alerts, and
hidden-link suggestions are deterministic graph/statistical analyses. Hidden
links use Jaccard and Adamic–Adar graph similarity; they are not a trained ML
model and are not confirmed relationships.

The `/ml-demo` experiment has its own generated synthetic event dataset under
`data/ml_experiment/` and model runs under `models/ml_experiment/`. It trains a
scikit-learn `StandardScaler` + `LogisticRegression` model on synthetic
temporal network examples and evaluates chronologically against a separate
Adamic–Adar baseline. Its outputs use synthetic IDs and status
`ML_SUGGESTED_UNCONFIRMED`; they are not inserted into the observed graph or
production scores.

The current synthetic test results are weak and near the Adamic–Adar baseline.
This experiment demonstrates a genuine training/inference/evaluation workflow
on controlled synthetic data; it does not establish real-world predictive
validity, and it does not predict criminality or guilt.

## SIH capability mapping (implemented scope)

- **AI/ML:** isolated synthetic supervised ML experiment only; no claim of
  real-case ML predictive validity.
- **NLP/text:** limited regex extraction and structured text/source fields;
  no semantic NLP model is implemented.
- **Graph analytics:** graph construction, centrality, modularity communities,
  and graph-similarity candidate generation.
- **Multi-source analysis:** FIR, CDR, financial, and social-media source tables.
- **Pattern and temporal review:** deterministic anomaly rules, review scores,
  timelines, and fixed-threshold alerts.
- **Visualization and investigative workflow:** dashboard, global graph,
  case-scoped graph, and Case Manager.
- **Secure case handling:** membership-controlled vault and auditable,
  approved cross-case document grants.

## Limitations

- Prototype, with synthetic/example data; not a production adjudication system.
- No guilt, criminality, or intent prediction.
- Synthetic ML performance is weak/near baseline and does not establish
  real-world predictive validity.
- Deterministic graph-similarity suggestions are not ML and are unconfirmed.
- OCR is unavailable.
- The development JWT secret fallback must not be used for a live or
  externally accessible deployment.
- No license information is provided here because no project license
  declaration was identified in the repository.
