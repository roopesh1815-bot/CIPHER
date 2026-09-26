# Project abstract

CIPHER is an offline-first investigative intelligence prototype addressing
the challenge of reviewing relationships across multiple records and data
sources. It ingests structured FIR, call-detail, financial-transaction, and
social-media data; extracts and resolves entities using deterministic
normalization and linking rules; and constructs source-aware relationships
for graph exploration.

The system provides graph visualization and graph analytics, including
centrality measures, community detection, rule/statistical anomaly flags,
review-priority scores, timelines, and fixed-threshold temporal alerts.
Deterministic Jaccard and Adamic–Adar graph-similarity suggestions are
presented separately from source-recorded relationships and require
investigator review.

CIPHER includes a Case Manager and per-case document vault with membership
authorization, a minimal cross-case reference index, and a request-and-approval
workflow for scoped, time-limited document access. Security-relevant actions
are recorded in a hash-chained audit log. Cross-case references indicate
potential relevance without automatically exposing protected source material.

An isolated temporal Logistic Regression experiment demonstrates supervised
training and chronological evaluation using controlled synthetic network
events. It is separate from investigative records and production graph
artifacts. Its current performance is weak and near an Adamic–Adar baseline;
it does not establish real-world predictive validity. CIPHER is designed to
support investigator review, not to determine guilt or criminal intent.
