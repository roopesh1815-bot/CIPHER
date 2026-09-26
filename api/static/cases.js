let currentOffset = 0;
const PAGE_SIZE = 20;
let selectedFirId = null;

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return res.json();
}

async function loadCrimeTypes() {
    const data = await fetchJSON("/api/cases/crime-types");
    const select = document.getElementById("crime-type-filter");
    data.crime_types.forEach(t => {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        select.appendChild(opt);
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
    const query = buildQuery();
    const data = await fetchJSON(`/api/cases?${query}`);

    document.getElementById("cases-stats").innerHTML = `
        <div>Total matching: <strong>${data.total}</strong></div>
    `;

    const list = document.getElementById("cases-list");
    list.innerHTML = data.cases.map(c => `
        <div class="case-card${c.fir_id === selectedFirId ? " selected" : ""}" data-id="${c.fir_id}">
            <div class="case-card-top">
                <span class="case-card-id">${c.fir_id}</span>
                <span class="tier-badge tier-${c.risk_tier || "Low"}">${c.risk_tier || "—"} · ${c.risk_score ?? "—"}</span>
            </div>
            <div class="case-card-meta">${c.crime_type || "Unknown"} · ${c.district || "—"} · ${c.date || "—"} · ${c.status}</div>
            <div class="case-card-preview">${c.narrative_preview || ""}</div>
        </div>
    `).join("");

    list.querySelectorAll(".case-card").forEach(el => {
        el.addEventListener("click", () => selectCase(el.dataset.id));
    });

    document.getElementById("page-label").textContent =
        `${currentOffset + 1}–${Math.min(currentOffset + PAGE_SIZE, data.total)} of ${data.total}`;
    document.getElementById("prev-page").disabled = currentOffset === 0;
    document.getElementById("next-page").disabled = currentOffset + PAGE_SIZE >= data.total;
}

async function selectCase(firId) {
    selectedFirId = firId;
    document.querySelectorAll(".case-card").forEach(el => {
        el.classList.toggle("selected", el.dataset.id === firId);
    });

    const data = await fetchJSON(`/api/cases/${encodeURIComponent(firId)}`);
    const c = data.case;
    const s = data.summary;
    const panel = document.getElementById("case-detail-panel");

    panel.innerHTML = `
        <h3>${firId}</h3>
        <a class="view-graph-btn" href="/network-graph?case=${encodeURIComponent(firId)}">View in graph →</a>
        <div class="detail-row"><strong>Crime type:</strong> ${s.Crime_Type || "—"}</div>
        <div class="detail-row"><strong>Location:</strong> ${s.Location || "—"}</div>
        <div class="detail-row"><strong>District:</strong> ${c.district || "—"}</div>
        <div class="detail-row"><strong>Status:</strong> ${c.status || "—"}</div>
        <div class="detail-row"><strong>Risk:</strong> ${s.Lead_Risk_Tier || "—"} (${s.Lead_Risk_Score ?? "—"})</div>
        <div class="detail-row"><strong>Anomalies:</strong> ${s.Num_Anomalies ?? 0}</div>
        <div class="detail-narrative">${s.Narrative || "No narrative available."}</div>
        <div class="entity-list">
            <strong>${data.entities.length} entit${data.entities.length === 1 ? "y" : "ies"} on file:</strong>
            ${data.entities.map(e => `
                <div class="entity-item">${e.entity_label} <span class="role-tag">(${e.entity_type}${e.role ? ", " + e.role : ""})</span></div>
            `).join("")}
        </div>
    `;
}

document.getElementById("apply-filters").addEventListener("click", () => {
    currentOffset = 0;
    loadCases();
});
document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("risk-tier-filter").value = "";
    document.getElementById("crime-type-filter").value = "";
    document.getElementById("search-filter").value = "";
    currentOffset = 0;
    loadCases();
});
document.getElementById("prev-page").addEventListener("click", () => {
    currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
    loadCases();
});
document.getElementById("next-page").addEventListener("click", () => {
    currentOffset += PAGE_SIZE;
    loadCases();
});

loadCrimeTypes();
loadCases();