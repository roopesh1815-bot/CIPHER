let network = null;
let caseMode = null; // holds the FIR_ID string when viewing a case-scoped graph, else null
const CASE_RING_RADIUS = 260;
const CASE_CONTEXT_RADIUS = 440;

function getUrlParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return res.json();
}

async function loadEntityTypes() {
    const data = await fetchJSON("/api/graph/entity-types");
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
    const community = document.getElementById("community-filter").value;
    const search = document.getElementById("search-filter").value;
    const limit = document.getElementById("limit-filter").value;

    if (entityType) params.set("entity_type", entityType);
    if (community) params.set("community", community);
    if (search) params.set("search", search);
    if (limit) params.set("limit", limit);
    return params.toString();
}

function renderGraph(data) {
    document.getElementById("graph-stats").innerHTML = caseMode ? `
        <div>Case entities: <strong>${data.meta.seed_count}</strong></div>
        <div>Nodes shown: <strong>${data.meta.node_count}</strong></div>
        <div>Edges shown: <strong>${data.meta.edge_count}</strong></div>
    ` : `
        <div>Nodes shown: <strong>${data.meta.node_count}</strong></div>
        <div>Edges shown: <strong>${data.meta.edge_count}</strong></div>
        <div>Total in graph: ${data.meta.full_meta.node_count} nodes</div>
    `;

    const centerNode = caseMode
        ? data.nodes.find(n => n.is_case_center === true)
        : null;
    const radialPositions = {};
    if (centerNode) {
        const orbitNodes = data.nodes.filter(n => n.id !== centerNode.id);
        const caseNodes = orbitNodes.filter(n => n.is_case_entity);
        const contextNodes = orbitNodes.filter(n => !n.is_case_entity);
        [[caseNodes, CASE_RING_RADIUS], [contextNodes, CASE_CONTEXT_RADIUS]].forEach(([nodes, radius]) => {
            nodes.forEach((n, index) => {
                const angle = (2 * Math.PI * index) / nodes.length;
                radialPositions[n.id] = { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
            });
        });
    }

    const nodesDataset = new vis.DataSet(data.nodes.map(n => {
        const isCenter = n.id === (centerNode && centerNode.id);
        const position = isCenter ? { x: 0, y: 0 } : radialPositions[n.id];
        return {
            id: n.id,
            label: n.label,
            color: isCenter
                ? { background: "#0f766e", border: "#ffffff" }
                : n.is_case_entity
                    ? { background: n.color, border: "#ffcc00" }
                    : n.color,
            borderWidth: isCenter ? 4 : n.is_case_entity ? 3 : 1,
            size: isCenter ? 38 : Math.max(8, Math.min(n.size, 50)),
            title: isCenter
                ? (n.is_merged_center
                    ? `Merged case center — ${(n.canonical_ids || []).length} case entities; underlying records are retained.`
                    : `Case center — ${n.label}; recorded case role is not a finding.`)
                : `${n.label} (${n.entity_type})${n.is_case_entity ? " — case entity" : ""}`,
            ...(caseMode ? { x: position.x, y: position.y, fixed: { x: true, y: true } } : {}),
        };
    }));

    const edgesDataset = new vis.DataSet(data.edges.map((e, index) => {
        const relationship = e.rel_type || e.title || "";
        const status = e.status || "data-derived";
        const title = caseMode
            ? [relationship, status === "ai_suggested"
                ? "AI-suggested — not a confirmed link"
                : status === "observed" ? "Observed" : "Data-derived"].filter(Boolean).join(" · ")
            : e.title;
        return {
            ...(caseMode ? { id: `case-edge-${index}`, value: e.value ?? 1 } : {}),
            from: e.from,
            to: e.to,
            title,
            ...(caseMode ? { dashes: status === "ai_suggested" } : {
                width: Math.max(0.5, Math.min(e.value, 5)),
            }),
            color: {
                color: status === "ai_suggested" && caseMode ? "#c4b5fd" : "#333846",
                highlight: "#4fd1c5",
            },
        };
    }));

    const options = {
        physics: caseMode ? false : {
            stabilization: { iterations: 150 },
            barnesHut: { gravitationalConstant: -3000, springLength: 90, springConstant: 0.02 },
        },
        interaction: { hover: true, tooltipDelay: 150 },
        nodes: { shape: "dot", font: { color: "#e6e6e6", size: 11 } },
        edges: { smooth: false, scaling: { min: 1, max: 8 } },
    };

    const container = document.getElementById("network-container");
    if (network) network.destroy();
    network = new vis.Network(container, { nodes: nodesDataset, edges: edgesDataset }, options);

    network.on("click", async (params) => {
        if (params.nodes.length === 0) return;
        await showNodeDetail(params.nodes[0]);
    });

    network.once("stabilizationIterationsDone", () => {
        network.setOptions({ physics: false });
    });
}

async function loadGraph() {
    const query = buildQuery();
    const data = await fetchJSON(`/api/graph?${query}`);
    renderGraph(data);
}

async function loadCaseGraph(firId, hops) {
    const data = await fetchJSON(`/api/graph/case/${encodeURIComponent(firId)}?hops=${hops}`);
    document.getElementById("case-banner-text").textContent =
        `Case ${firId} — ${data.meta.seed_count} case entities; AI suggestions, if present, are unconfirmed.`;
    renderGraph(data);
}

function exitCaseMode() {
    caseMode = null;
    document.getElementById("case-banner").style.display = "none";
    history.replaceState(null, "", "/network-graph");
}

async function showNodeDetail(nodeId) {
    const data = await fetchJSON(`/api/graph/${encodeURIComponent(nodeId)}`);
    const n = data.node;
    const panel = document.getElementById("node-detail");

    panel.innerHTML = `
        <h3>${n.label}</h3>
        <div class="attr-row"><strong>Type:</strong> ${n.entity_type}</div>
        <div class="attr-row"><strong>Roles:</strong> ${n.roles || "—"}</div>
        <div class="attr-row"><strong>Sources:</strong> ${n.sources || "—"}</div>
        <div class="attr-row"><strong>FIR count:</strong> ${n.fir_count ?? "—"}</div>
        <div class="attr-row"><strong>Community:</strong> ${n.community ?? "—"}</div>
        <div class="attr-row"><strong>Cross-verified:</strong> ${n.cross_verified ? "Yes" : "No"}</div>
        <div class="neighbor-list">
            <strong>${data.neighbors.length} connection(s):</strong>
            ${data.neighbors.slice(0, 15).map(nb =>
                `<div class="neighbor-item" data-id="${nb.id}">${nb.label} (${nb.entity_type})</div>`
            ).join("")}
            ${data.neighbors.length > 15 ? `<div class="hint">...and ${data.neighbors.length - 15} more</div>` : ""}
        </div>
    `;

    panel.querySelectorAll(".neighbor-item").forEach(el => {
        el.addEventListener("click", () => {
            network.focus(el.dataset.id, { scale: 1.5, animation: true });
            network.selectNodes([el.dataset.id]);
            showNodeDetail(el.dataset.id);
        });
    });
}

document.getElementById("apply-filters").addEventListener("click", () => {
    if (caseMode) exitCaseMode();
    loadGraph();
});
document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("entity-type-filter").value = "";
    document.getElementById("community-filter").value = "";
    document.getElementById("search-filter").value = "";
    document.getElementById("limit-filter").value = "800";
    if (caseMode) exitCaseMode();
    loadGraph();
});
document.getElementById("case-hops").addEventListener("change", (e) => {
    if (caseMode) loadCaseGraph(caseMode, e.target.value);
});

// ── Init ──
loadEntityTypes();

const caseParam = getUrlParam("case");
if (caseParam) {
    caseMode = caseParam;
    document.getElementById("case-banner").style.display = "flex";
    loadCaseGraph(caseMode, document.getElementById("case-hops").value);
} else {
    loadGraph();
}