let currentOffset = 0;
const PAGE_SIZE = 20;
let selectedFirId = null;

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        let message = `Request failed: ${response.status}`;
        try {
            const body = await response.json();
            message = body.detail || message;
        } catch {
            // Keep the HTTP status as the user-facing error.
        }
        throw new Error(message);
    }
    return response.json();
}

function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
}

function setStatus(message, isError = false) {
    const status = document.getElementById("case-action-status");
    status.textContent = message;
    status.classList.toggle("error-banner", isError);
}

async function loadCrimeTypes() {
    const data = await fetchJSON("/api/cases/crime-types");
    const select = document.getElementById("crime-type-filter");
    data.crime_types.forEach(type => {
        const option = node("option", type);
        option.value = type;
        select.appendChild(option);
    });
}

function buildQuery() {
    const params = new URLSearchParams();
    const riskTier = document.getElementById("risk-tier-filter").value;
    const crimeType = document.getElementById("crime-type-filter").value;
    const search = document.getElementById("search-filter").value;
    if (riskTier) params.set("risk_tier", riskTier);
    if (crimeType) params.set("crime_type", crimeType);
    if (search) params.set("search", search);
    params.set("limit", PAGE_SIZE);
    params.set("offset", currentOffset);
    return params.toString();
}

async function loadCases() {
    const data = await fetchJSON(`/api/cases?${buildQuery()}`);
    const stats = document.getElementById("cases-stats");
    stats.replaceChildren(node("div", `Total matching: ${data.total}`));

    const list = document.getElementById("cases-list");
    list.replaceChildren();
    data.cases.forEach(caseItem => {
        const card = node("div", undefined, `case-card${caseItem.fir_id === selectedFirId ? " selected" : ""}`);
        card.dataset.id = caseItem.fir_id;
        const top = node("div", undefined, "case-card-top");
        top.append(node("span", caseItem.fir_id, "case-card-id"));
        const tier = ["Critical", "High", "Medium", "Low"].includes(caseItem.risk_tier)
            ? caseItem.risk_tier
            : null;
        top.append(node(
            "span",
            `${tier || "—"} · ${caseItem.risk_score ?? "—"}`,
            `tier-badge${tier ? ` tier-${tier}` : ""}`
        ));
        card.append(top);
        card.append(node(
            "div",
            `${caseItem.crime_type || "Unknown"} · ${caseItem.district || "—"} · ${caseItem.date || "—"} · ${caseItem.status || "—"}`,
            "case-card-meta"
        ));
        card.append(node("div", caseItem.narrative_preview || "", "case-card-preview"));
        card.addEventListener("click", () => selectCase(caseItem.fir_id));
        list.append(card);
    });

    const start = data.total === 0 ? 0 : currentOffset + 1;
    document.getElementById("page-label").textContent =
        `${start}–${Math.min(currentOffset + PAGE_SIZE, data.total)} of ${data.total}`;
    document.getElementById("prev-page").disabled = currentOffset === 0;
    document.getElementById("next-page").disabled = currentOffset + PAGE_SIZE >= data.total;
}

function addDetailRow(panel, label, value) {
    const row = node("div", undefined, "detail-row");
    row.append(node("strong", `${label}:`), document.createTextNode(` ${value ?? "—"}`));
    panel.append(row);
}

async function loadDocuments(firId, container) {
    const section = node("section", undefined, "case-documents");
    section.append(node("h4", "Protected case documents"));
    let documents = [];
    let canUpload = false;
    try {
        const result = await fetchJSON(`/api/cases/${encodeURIComponent(firId)}/documents`);
        documents = result.documents;
        canUpload = result.can_upload;
    } catch (error) {
        section.append(node("p", error.message));
        container.append(section);
        return;
    }
    if (canUpload) {
        const form = node("form", undefined, "case-form");
        const file = node("input");
        file.type = "file";
        file.required = true;
        file.accept = ".pdf,.jpg,.jpeg,.png,.txt,.docx";
        const type = node("input");
        type.placeholder = "Document type (optional)";
        const source = node("input");
        source.placeholder = "Source / provenance (optional)";
        const submit = node("button", "Upload document");
        submit.type = "submit";
        form.append(file, type, source, submit);
        form.addEventListener("submit", async event => {
            event.preventDefault();
            try {
                const body = new FormData();
                body.append("file", file.files[0]);
                body.append("document_type", type.value);
                body.append("source", source.value);
                await fetchJSON(`/api/cases/${encodeURIComponent(firId)}/documents`, {
                    method: "POST",
                    body
                });
                setStatus("Document stored in the protected case vault. OCR is unavailable.");
                await selectCase(firId);
            } catch (error) {
                setStatus(error.message, true);
            }
        });
        section.append(form);
    }

    if (!documents.length) section.append(node("p", "No documents are available to you."));
    documents.forEach(document => {
        const row = node("div", undefined, "case-action-row");
        row.append(node(
            "span",
            `${document.file_name} · ${document.document_type || document.file_type || "document"} · ${document.ocr_status}`
        ));
        const download = node("a", "Download");
        download.href = `/api/cases/${encodeURIComponent(firId)}/documents/${document.id}`;
        row.append(download);
        section.append(row);
    });
    container.append(section);
}

async function loadReferences(firId, container) {
    const section = node("section", undefined, "case-references");
    section.append(node("h4", "Related-case references"));
    try {
        const { references } = await fetchJSON(`/api/cases/${encodeURIComponent(firId)}/references`);
        if (!references.length) section.append(node("p", "No source-declared related-case references."));
        references.forEach(reference => {
            const row = node("div", undefined, "case-action-row");
            row.append(node(
                "span",
                `${reference.related_case_id} · ${reference.provenance} · ${reference.context}`
            ));
            const request = node("button", "Request document access");
            request.type = "button";
            request.addEventListener("click", async () => {
                const reason = window.prompt("Reason for requesting access to this related case:");
                if (!reason) return;
                try {
                    await fetchJSON("/api/case-access/requests", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            requesting_fir_id: firId,
                            source_fir_id: reference.related_case_id,
                            requested_scope: "documents",
                            reason
                        })
                    });
                    setStatus("Access request submitted to the source case handler.");
                    loadAccessRequests();
                } catch (error) {
                    setStatus(error.message, true);
                }
            });
            row.append(request);
            section.append(row);
        });
    } catch (error) {
        section.append(node("p", error.message));
    }
    container.append(section);
}

async function selectCase(firId) {
    selectedFirId = firId;
    document.querySelectorAll(".case-card").forEach(card => {
        card.classList.toggle("selected", card.dataset.id === firId);
    });
    const data = await fetchJSON(`/api/cases/${encodeURIComponent(firId)}`);
    const panel = document.getElementById("case-detail-panel");
    panel.replaceChildren();
    panel.append(node("h3", firId));
    const graphLink = node("a", "Open case spider-web →", "view-graph-btn");
    graphLink.href = `/cases/${encodeURIComponent(firId)}/graph`;
    panel.append(graphLink);
    const networkLink = node("a", "View in Network Graph →", "view-graph-btn");
    networkLink.href = `/network-graph?case=${encodeURIComponent(firId)}`;
    panel.append(networkLink);

    const summary = data.summary || {};
    const item = data.case || {};
    addDetailRow(panel, "Crime type", summary.Crime_Type || item.crime_type);
    addDetailRow(panel, "Location", summary.Location);
    addDetailRow(panel, "District", item.district);
    addDetailRow(panel, "Status", item.status);
    addDetailRow(
        panel,
        "Priority score (for investigator review)",
        `${summary.Lead_Risk_Tier || "—"} (${summary.Lead_Risk_Score ?? "—"})`
    );
    addDetailRow(panel, "Anomalies", summary.Num_Anomalies ?? 0);
    panel.append(node("div", summary.Narrative || "No narrative available.", "detail-narrative"));

    const entities = node("div", undefined, "entity-list");
    entities.append(node(
        "strong",
        `${data.entities.length} entit${data.entities.length === 1 ? "y" : "ies"} on file:`
    ));
    data.entities.forEach(entity => {
        const itemRow = node("div", undefined, "entity-item");
        itemRow.append(
            document.createTextNode(entity.entity_label || ""),
            node("span", ` (${entity.entity_type}${entity.role ? `, ${entity.role}` : ""})`, "role-tag")
        );
        entities.append(itemRow);
    });
    panel.append(entities);
    if (window.CIPHER_IS_ADMIN) {
        const assignment = node("form", undefined, "case-form case-references");
        assignment.append(node("h4", "Assign case access"));
        const userId = node("input");
        userId.type = "number";
        userId.min = "1";
        userId.required = true;
        userId.placeholder = "Existing user ID";
        const role = node("select");
        [["handler", "Handler"], ["investigator", "Investigator"]].forEach(([value, label]) => {
            const option = node("option", label);
            option.value = value;
            role.append(option);
        });
        const submit = node("button", "Assign");
        submit.type = "submit";
        assignment.append(userId, role, submit);
        assignment.addEventListener("submit", async event => {
            event.preventDefault();
            try {
                await fetchJSON(`/api/cases/${encodeURIComponent(firId)}/members`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: Number(userId.value), role: role.value })
                });
                setStatus("Case access assigned.");
                assignment.reset();
            } catch (error) {
                setStatus(error.message, true);
            }
        });
        panel.append(assignment);
    }
    await loadDocuments(firId, panel);
    await loadReferences(firId, panel);
}

async function loadAccessRequests() {
    const container = document.getElementById("access-request-list");
    container.replaceChildren();
    try {
        const inbox = await fetchJSON("/api/case-access/requests?role=inbox");
        const outbox = await fetchJSON("/api/case-access/requests?role=outbox");
        if (!inbox.requests.length && !outbox.requests.length) {
            container.append(node("p", "No access requests."));
        }
        inbox.requests.forEach(request => {
            const card = node("div", undefined, "request-item");
            card.append(node(
                "strong",
                `${request.source_fir_id}: request from ${request.requesting_fir_id} · ${request.status}`
            ));
            card.append(node("p", request.reason));
            if (
                request.grant_id
                && !request.grant_revoked_at
                && !request.grant_expired_at
                && Date.parse(request.grant_expires_at) > Date.now()
            ) {
                const revoke = node("button", "Revoke access");
                revoke.type = "button";
                revoke.addEventListener("click", async () => {
                    try {
                        await fetchJSON(`/api/case-access/grants/${encodeURIComponent(request.grant_id)}/revoke`, {
                            method: "POST"
                        });
                        setStatus("Access grant revoked.");
                        loadAccessRequests();
                    } catch (error) {
                        setStatus(error.message, true);
                    }
                });
                card.append(revoke);
            }
            if (request.status === "PENDING") {
                const selected = [];
                request.documents.forEach(document => {
                    const label = node("label");
                    const checkbox = node("input");
                    checkbox.type = "checkbox";
                    checkbox.value = document.id;
                    label.append(checkbox, document.createTextNode(
                        `${document.file_name} (${document.document_type || document.file_type})`
                    ));
                    card.append(label);
                    selected.push(checkbox);
                });
                const approve = node("button", "Approve selected documents");
                approve.type = "button";
                approve.addEventListener("click", async () => {
                    try {
                        await submitDecision(request.id, "approve", selected
                            .filter(checkbox => checkbox.checked)
                            .map(checkbox => Number(checkbox.value)));
                        setStatus("Scoped, time-limited access granted.");
                        loadAccessRequests();
                    } catch (error) {
                        setStatus(error.message, true);
                    }
                });
                const reject = node("button", "Reject request");
                reject.type = "button";
                reject.addEventListener("click", async () => {
                    try {
                        await submitDecision(request.id, "reject", []);
                        loadAccessRequests();
                    } catch (error) {
                        setStatus(error.message, true);
                    }
                });
                card.append(approve, reject);
            }
            container.append(card);
        });
        outbox.requests.forEach(request => {
            const card = node(
                "div",
                `Request for ${request.source_fir_id} · ${request.status}`,
                "request-item"
            );
            if (
                request.status === "APPROVED"
                && request.grant_id
                && !request.grant_revoked_at
                && !request.grant_expired_at
                && Date.parse(request.grant_expires_at) > Date.now()
            ) {
                const access = node("button", "View approved documents");
                access.type = "button";
                access.addEventListener("click", async () => {
                    try {
                        const result = await fetchJSON(
                            `/api/cases/${encodeURIComponent(request.source_fir_id)}/documents`
                        );
                        card.replaceChildren(node("strong", `Approved documents · ${request.source_fir_id}`));
                        result.documents.forEach(document => {
                            const link = node("a", document.file_name);
                            link.href = `/api/cases/${encodeURIComponent(request.source_fir_id)}/documents/${document.id}`;
                            link.className = "view-graph-btn";
                            card.append(link);
                        });
                    } catch (error) {
                        setStatus(error.message, true);
                    }
                });
                card.append(access);
            }
            container.append(card);
        });
    } catch (error) {
        container.append(node("p", error.message));
    }
}

async function submitDecision(requestId, decision, documentIds) {
    return fetchJSON(`/api/case-access/requests/${encodeURIComponent(requestId)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, document_ids: documentIds })
    });
}

document.getElementById("case-registration-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
        await fetchJSON("/api/cases", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(Object.fromEntries(form.entries()))
        });
        setStatus("Case registered. You are its initial handler.");
        currentOffset = 0;
        await loadCases();
    } catch (error) {
        setStatus(error.message, true);
    }
});

document.getElementById("apply-filters").addEventListener("click", () => {
    currentOffset = 0;
    loadCases().catch(error => setStatus(error.message, true));
});
document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("risk-tier-filter").value = "";
    document.getElementById("crime-type-filter").value = "";
    document.getElementById("search-filter").value = "";
    currentOffset = 0;
    loadCases().catch(error => setStatus(error.message, true));
});
document.getElementById("prev-page").addEventListener("click", () => {
    currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
    loadCases().catch(error => setStatus(error.message, true));
});
document.getElementById("next-page").addEventListener("click", () => {
    currentOffset += PAGE_SIZE;
    loadCases().catch(error => setStatus(error.message, true));
});

Promise.all([loadCrimeTypes(), loadCases(), loadAccessRequests()])
    .catch(error => setStatus(error.message, true));
