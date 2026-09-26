let currentOffset = 0;
const PAGE_SIZE = 20;
let selectedId = null;

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return res.json();
}

function buildQuery() {
    const params = new URLSearchParams();
    const entityType = document.getElementById("entity-type-filter").value;
    const riskTier = document.getElementById("risk-tier-filter").value;
    const minScore = document.getElementById("min-score-filter").value;
    const search = document.getElementById("search-filter").value;

    if (entityType) params.set("entity_type", entityType);
    if (riskTier) params.set("risk_tier", riskTier);
    if (minScore) params.set("min_score", minScore);
    if (search) params.set("search", search);
    params.set("limit", PAGE_SIZE);
    params.set("offset", currentOffset);
    return params.toString();
}

async function loadRiskScores() {
    const query = buildQuery();
    const data = await fetchJSON(`/api/risk?${query}`);

    const tierRows = Object.entries(data.tier_distribution)
        .map(([tier, count]) => `<div class="tier-dist-row"><span>${tier}</span><strong>${count}</strong></div>`)
        .join("");
    document.getElementById("risk-stats").innerHTML = `
        <div>Total matching: <strong>${data.total}</strong></div>
        <div style="margin-top:0.6rem">${tierRows}</div>
    `;

    const list = document.getElementById("risk-list");
    list.innerHTML = data.scores.map(s => `
        <div class="case-card${s.Canonical_ID === selectedId ? " selected" : ""}" data-id="${s.Canonical_ID}">
            <div class="case-card-top">
                <span class="case-card-id">#${s.Risk_Rank} · ${s.Label}</span>
                <span class="tier-badge tier-${s.Risk_Tier || "Low"}">${s.Risk_Tier || "—"} · <span class="risk-score-num">${s.Risk_Score}</span></span>
            </div>
            <div class="case-card-meta">${s.Entity_Type} · ${s.Roles || "—"}</div>
            <div class="risk-card-badges">
                <span>${s.Fusion_Badge || ""}</span>
                <span>Influence: ${s.Influence_Score ?? "—"}</span>
                <span>Sources: ${s.Sources || "—"}</span>
            </div>
        </div>
    `).join("");

    list.querySelectorAll(".case-card").forEach(el => {
        el.addEventListener("click", () => selectEntity(el.dataset.id));
    });

    document.getElementById("page-label").textContent =
        `${currentOffset + 1}–${Math.min(currentOffset + PAGE_SIZE, data.total)} of ${data.total}`;
    document.getElementById("prev-page").disabled = currentOffset === 0;
    document.getElementById("next-page").disabled = currentOffset + PAGE_SIZE >= data.total;
}

async function selectEntity(id) {
    selectedId = id;
    document.querySelectorAll(".case-card").forEach(el => {
        el.classList.toggle("selected", el.dataset.id === id);
    });

    const e = await fetchJSON(`/api/risk/${encodeURIComponent(id)}`);
    const panel = document.getElementById("risk-detail-panel");
    panel.innerHTML = `
        <h3>${e.Label}</h3>
        <div class="detail-row"><strong>Type:</strong> ${e.Entity_Type}</div>
        <div class="detail-row"><strong>Roles:</strong> ${e.Roles || "—"}</div>
        <div class="detail-row"><strong>Risk score:</strong> ${e.Risk_Score} (${e.Risk_Tier})</div>
        <div class="detail-row"><strong>Influence score:</strong> ${e.Influence_Score ?? "—"}</div>
        <div class="detail-row"><strong>Cross-verified:</strong> ${e.Cross_Verified ? "Yes" : "No"}</div>
        <div class="detail-row"><strong>Badge:</strong> ${e.Fusion_Badge || "—"}</div>
        <div class="detail-row"><strong>Sources:</strong> ${e.Sources || "—"}</div>
        <div class="detail-row"><strong>Rank:</strong> #${e.Risk_Rank} of all entities</div>
    `;
}

document.getElementById("apply-filters").addEventListener("click", () => {
    currentOffset = 0;
    loadRiskScores();
});
document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("entity-type-filter").value = "";
    document.getElementById("risk-tier-filter").value = "";
    document.getElementById("min-score-filter").value = "";
    document.getElementById("search-filter").value = "";
    currentOffset = 0;
    loadRiskScores();
});
document.getElementById("prev-page").addEventListener("click", () => {
    currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
    loadRiskScores();
});
document.getElementById("next-page").addEventListener("click", () => {
    currentOffset += PAGE_SIZE;
    loadRiskScores();
});

loadRiskScores();