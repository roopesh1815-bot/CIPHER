let currentOffset = 0;
const PAGE_SIZE = 25;
let selectedId = null;

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return res.json();
}

async function loadEntityTypes() {
    const data = await fetchJSON("/api/influencers/entity-types");
    const select = document.getElementById("entity-type-filter");
    data.entity_types.forEach(t => {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        select.appendChild(opt);
    });
}

function buildQuery() {
    const params = new URLSearchParams();
    const entityType = document.getElementById("entity-type-filter").value;
    const minScore = document.getElementById("min-score-filter").value;
    const search = document.getElementById("search-filter").value;

    if (entityType) params.set("entity_type", entityType);
    if (minScore) params.set("min_score", minScore);
    if (search) params.set("search", search);
    params.set("limit", PAGE_SIZE);
    params.set("offset", currentOffset);
    return params.toString();
}

function scoreClass(score) {
    if (score >= 80) return "score-critical";
    if (score >= 60) return "score-high";
    if (score >= 35) return "score-medium";
    return "score-low";
}

async function loadInfluencers() {
    const query = buildQuery();
    const data = await fetchJSON(`/api/influencers?${query}`);

    document.getElementById("influencers-stats").innerHTML = `
        <div>Total matching: <strong>${data.total}</strong></div>
    `;

    const list = document.getElementById("influencers-list");
    list.innerHTML = data.influencers.map(p => `
        <div class="case-card${p.Canonical_ID === selectedId ? " selected" : ""}" data-id="${p.Canonical_ID}">
            <div class="case-card-top">
                <span class="case-card-id">#${p.Rank} · ${p.Label}</span>
                <span class="tier-badge ${scoreClass(p.Influence_Score)}">${p.Influence_Score.toFixed(1)}</span>
            </div>
            <div class="case-card-meta">${p.Entity_Type} ${p.Roles ? "· " + p.Roles : ""}</div>
            <div class="case-card-preview">
                Betweenness ${p.Betweenness} · PageRank ${p.PageRank} · Closeness ${p.Closeness}
            </div>
        </div>
    `).join("");

    list.querySelectorAll(".case-card").forEach(el => {
        el.addEventListener("click", () => selectInfluencer(el.dataset.id));
    });

    document.getElementById("page-label").textContent =
        `${currentOffset + 1}–${Math.min(currentOffset + PAGE_SIZE, data.total)} of ${data.total}`;
    document.getElementById("prev-page").disabled = currentOffset === 0;
    document.getElementById("next-page").disabled = currentOffset + PAGE_SIZE >= data.total;
}

async function selectInfluencer(canonicalId) {
    selectedId = canonicalId;
    document.querySelectorAll(".case-card").forEach(el => {
        el.classList.toggle("selected", el.dataset.id === canonicalId);
    });

    const p = await fetchJSON(`/api/influencers/${encodeURIComponent(canonicalId)}`);
    const panel = document.getElementById("influencer-detail-panel");

    panel.innerHTML = `
        <h3>${p.Label}</h3>
        <a class="view-graph-btn" href="/network-graph?search=${encodeURIComponent(p.Label)}">View in graph →</a>
        <div class="detail-row"><strong>Rank:</strong> #${p.Rank} of all entities</div>
        <div class="detail-row"><strong>Type:</strong> ${p.Entity_Type}</div>
        <div class="detail-row"><strong>Roles:</strong> ${p.Roles || "—"}</div>
        <div class="detail-row"><strong>Influence score:</strong> ${p.Influence_Score.toFixed(1)} / 100</div>
        <div class="detail-row"><strong>Degree:</strong> ${p.Degree_Raw} (normalized ${p.Degree_Norm})</div>
        <div class="detail-row"><strong>Betweenness:</strong> ${p.Betweenness}</div>
        <div class="detail-row"><strong>PageRank:</strong> ${p.PageRank}</div>
        <div class="detail-row"><strong>Closeness:</strong> ${p.Closeness}</div>
        <div class="detail-row"><strong>Cross-verified:</strong> ${p.Cross_Verified ? "Yes" : "No"} (${p.Fusion_Badge || "—"})</div>
        <div class="detail-row"><strong>Sources:</strong> ${p.Sources || "—"}</div>
        <div class="detail-row"><strong>Records:</strong> FIR ${p.FIR_Count} · CDR ${p.CDR_Count} · Financial ${p.Fin_Count} · Social ${p.Soc_Count}</div>
    `;
}

document.getElementById("apply-filters").addEventListener("click", () => {
    currentOffset = 0;
    loadInfluencers();
});
document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("entity-type-filter").value = "";
    document.getElementById("min-score-filter").value = "";
    document.getElementById("search-filter").value = "";
    currentOffset = 0;
    loadInfluencers();
});
document.getElementById("prev-page").addEventListener("click", () => {
    currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
    loadInfluencers();
});
document.getElementById("next-page").addEventListener("click", () => {
    currentOffset += PAGE_SIZE;
    loadInfluencers();
});

loadEntityTypes();
loadInfluencers();