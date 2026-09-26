# CIPHER architecture

## Overview

CIPHER is an offline-first FastAPI application. The browser uses server-rendered
Jinja templates and static JavaScript/CSS. API routers read existing
production analytical artifacts or operate on the SQLite-backed case
workflow. The analytical pipeline is an explicit offline process; application
startup does not run it.

```text
FIR / CDR / financial / social CSVs
        │
        ▼
pipeline/extraction (structured extraction, normalization, entity fusion)
        │
        ▼
pipeline/graph (NetworkX relationships and graph measures)
        │
        ├── centrality / anomalies / communities
        ├── deterministic graph-similarity suggestions
        ├── risk review scores / case summaries
        └── temporal timelines / alerts
                    │
                    ▼
        data/processed + output artifacts
                    │
                    ▼
            FastAPI APIs and UI

SQLite case/access/audit records ── Case Manager / Case Vault APIs

Controlled synthetic events ── isolated ML experiment ── separate demo API/page
```

## FastAPI, authentication, and authorization

`api/main.py` registers routers, mounts static files, serves Jinja pages, and
initializes the application database at startup. Investigation pages and
their APIs use `get_current_user` from `api/security.py`. The dependency
validates a JWT, reloads the user from SQLite, and rejects inactive accounts.
Browser login sets an HTTP-only cookie; API clients can use a bearer token.
Logout clears the cookie and records the event when the user can be resolved.

Case-level access is separate from global investigator authentication.
`core/case_access.py` checks active case membership and view/upload
permissions; Admin has the implemented access bypass. Some administrative
operations additionally require the Admin role.

## Case Manager and Case Vault

`/cases` presents case registration, case selection, metadata, case entities,
document actions, related-case references, and access-request workflows.
Case data is stored in SQLite and per-case directories below `data/cases/`.
Document paths are checked to remain within the configured case directory;
uploads are size/type validated and recorded with metadata and a content hash.
The implementation does not claim encryption at rest.

Documents are listed and downloaded only for an authorized case member or
through a currently valid document-scoped grant. Upload requires case upload
permission. OCR status currently reports unavailable; OCR is not implemented.

## Case Reference Index and controlled access

The case-reference table stores source/referenced case IDs, reference type,
provenance, and minimal context. It indicates that potentially relevant
information may exist; it does not copy or reveal source documents.

An investigator with access to the requesting case can submit a request for
documents from a referenced source case. The source case handler or Admin
reviews it. Self-approval is rejected. Approval scopes the grant to selected
existing document IDs and sets a limited expiry. Each read rechecks requesting
case membership, selected-document scope, expiry, and revocation. Revocation,
decisions, relevant access, and expiry are auditable.

## Ingestion, extraction, and entity resolution

`pipeline/run_pipeline.py` orchestrates source extractors for FIR, CDR,
financial transactions, and social-media records. The FIR/social extractors
use structured columns and limited regular-expression extraction; they do
not perform general semantic NLP. The resolver applies deterministic
normalization and linking rules, and the fusion tagger adds source-count and
rule-based indicators.

## Graph construction and analysis

`pipeline/graph/builder.py` constructs a NetworkX graph using entity tables
and source event rows. Edges retain relationship type, event/source metadata,
and numeric weight. The exporter writes graph JSON/GEXF and relationship CSV
to `output/`.

The graph analytics include:

- weighted degree, betweenness, PageRank, closeness, and a fixed-weight
  influence score;
- greedy-modularity communities;
- threshold/statistical and domain-rule anomaly flags;
- fixed-weight risk/review-priority scores composed from existing analytic
  outputs;
- case summaries assembled from templates and existing structured analysis.

These are deterministic/statistical analyses, not trained ML models.

The global Network Graph visualizes the global artifact. The Case Graph
selects a case-scoped view and applies a Spider-Web center/layout rule. The
center selection and radial arrangement are presentation choices: they do
not change the source relationships or establish new relationships.

## Temporal analysis

The temporal engine creates entity timelines and monthly crime-type trends.
Its alert is a fixed rule based on an entity appearing in at least three
distinct FIRs within a 90-day window. It does not learn a temporal model.

## Deterministic graph-similarity suggestions

`pipeline/intelligence/link_predictor.py` considers non-adjacent node pairs
from two-hop neighborhoods and ranks them using Jaccard and Adamic–Adar with a
fixed combination. These **Graph-Similarity Suggested Relationships** are
deterministic analytical suggestions; they are not source-recorded observed
relationships, confirmed facts, or ML predictions.

## Isolated synthetic ML experiment

`ml_experiment/temporal_link_demo.py` generates controlled synthetic
timestamped network interactions, constructs historical features, and trains
a scikit-learn `StandardScaler` + `LogisticRegression` classifier. Chronological
train/validation/test periods are evaluated against an independent
Adamic–Adar baseline. The current test performance is weak and near baseline.

The dataset and model outputs live under `data/ml_experiment/` and
`models/ml_experiment/`, not in production input or analytical artifact
directories. The authenticated `/ml-demo` page and `/api/ml-demo` expose only
that synthetic run. ML output status is `ML_SUGGESTED_UNCONFIRMED`.

The three concepts must remain distinct:

```text
Observed/source-recorded relationship
    != deterministic graph-similarity suggestion
    != synthetic ML-suggested relationship
```

The synthetic model does not establish real-world predictive validity and is
not evidence about real people or relationships.

## Audit and database

`core/db.py` owns the SQLite schema and connection helpers. `core/audit.py`
records security-relevant actions in a
SHA-256 hash-chained audit table, which can be checked using `verify_chain()`.
Audit details are intended to include action/actor/target metadata, not
passwords, JWTs, access tokens, grant secrets, or raw document contents.

## Data and artifact boundaries

| Location | Role |
|---|---|
| `data/raw/` | Existing source datasets |
| `data/processed/` | Production entity and intelligence tables |
| `output/` | Production graph/relationship exports |
| `data/db/` | SQLite database and backups |
| `data/cases/` | Per-case vault materials |
| `data/ml_experiment/` | Controlled synthetic ML event dataset |
| `models/ml_experiment/` | Synthetic model, metadata, evaluation, predictions |

The production pipeline refreshes production analytical outputs when
explicitly run. The synthetic ML experiment has a separate generation/training
entry point and must not be merged into observed graph relationships, risk,
centrality, communities, anomaly outputs, or Case Vault data.
