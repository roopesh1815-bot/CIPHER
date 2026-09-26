const API = {
  cases: "/api/cases?limit=1&offset=0",
  graph: "/api/graph?limit=5000",
  influencers: "/api/influencers?limit=20&offset=0",
  alerts: "/api/alerts",
  risk: "/api/risk?limit=5&offset=0",
  hiddenLinks: "/api/hidden-links",
  communities: "/api/communities",
};

const ENTITY_COLORS = {
  Person: "#60a5fa",
  Mobile: "#34d399",
  Phone: "#34d399",
  Location: "#f472b6",
  Vehicle: "#a78bfa",
  Account: "#facc15",
  CellTower: "#2dd4bf",
  SocialHandle: "#fb923c",
};

const CASE_COLOR = "#f1c27d";
const MAX_SUGGESTIONS = 4;
const MAX_REVIEW_ITEMS = 5;
const MAX_GRAPH_NEIGHBORS = 20;
const MAX_CASE_NODES = 8;
const networkContainer = document.getElementById("investigation-network");
const networkState = document.getElementById("network-state");
const keyPlayerSelector = document.getElementById("key-player-selector");
let network = null;
let graphData = null;
let influencers = [];
let selectedKeyPlayer = null;
let selectedCases = [];
let selectedNodeDetails = null;

async function fetchJSON(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json();
}

async function loadResource(url) {
  try {
    return { data: await fetchJSON(url), error: null };
  } catch (error) {
    console.error(`Dashboard request failed for ${url}:`, error);
    return { data: null, error };
  }
}

function setMetric(id, value, error) {
  const element = document.getElementById(id);
  element.textContent = error || value === undefined || value === null
    ? "Unavailable"
    : Number(value).toLocaleString();
  element.classList.toggle("unavailable", Boolean(error) || value === undefined || value === null);
}

function appendText(parent, tagName, text, className) {
  const element = document.createElement(tagName);
  element.textContent = text;
  if (className) element.className = className;
  parent.appendChild(element);
  return element;
}

function appendContextRow(parent, label, value) {
  const row = document.createElement("div");
  row.className = "context-row";
  const strong = appendText(row, "strong", `${label}: `);
  const content = document.createElement("span");
  content.textContent = value === undefined || value === null || value === "" ? "—" : String(value);
  row.append(strong, content);
  parent.appendChild(row);
}

function statusLabel(status) {
  if (status === "ai_inference") return "Analytical inference — unconfirmed";
  if (status === "investigator_confirmed") return "Investigator-reviewed case record";
  if (status === "observed_fact") return "Reported case context";
  return "Data-derived case context";
}

function setPanelState(container, message, unavailable = false) {
  container.replaceChildren();
  appendText(container, "p", message, `panel-state${unavailable ? " unavailable" : ""}`);
}

function updateMetrics(results) {
  const cases = results.cases.data;
  const graph = results.graph.data;
  const alerts = results.alerts.data;
  setMetric("metric-cases", cases && cases.total, Boolean(results.cases.error));
  setMetric(
    "metric-entities",
    graph && graph.meta && graph.meta.full_meta && graph.meta.full_meta.node_count,
    Boolean(results.graph.error)
  );
  setMetric(
    "metric-relationships",
    graph && graph.meta && graph.meta.full_meta && graph.meta.full_meta.edge_count,
    Boolean(results.graph.error)
  );
  setMetric("metric-alerts", alerts && alerts.length, Boolean(results.alerts.error));
}

function populateKeyPlayerOptions() {
  keyPlayerSelector.replaceChildren();
  influencers.forEach((influencer) => {
    const option = document.createElement("option");
    option.value = influencer.Canonical_ID;
    option.textContent = `#${influencer.Rank} · ${influencer.Label} (${influencer.Entity_Type})`;
    keyPlayerSelector.appendChild(option);
  });
  keyPlayerSelector.disabled = influencers.length === 0;
}

function getSelectedGraphNode() {
  if (!graphData || !selectedKeyPlayer) return null;
  return graphData.nodes.find((node) => node.id === selectedKeyPlayer.Canonical_ID) || null;
}

function renderKeyPlayerDetails() {
  const details = document.getElementById("key-player-details");
  details.replaceChildren();
  const graphNode = getSelectedGraphNode();
  const selected = selectedNodeDetails || selectedKeyPlayer;
  const selectedGraphNode = selectedNodeDetails || graphNode;
  if (!selected) {
    setPanelState(details, "Key Player information is unavailable.", true);
    return;
  }

  appendContextRow(details, "Entity", selected.Label || selected.label);
  appendContextRow(details, "Type", selected.Entity_Type || selected.entity_type);
  appendContextRow(details, "Roles", selected.Roles || selected.roles);
  appendContextRow(details, "Influence score", selected.Influence_Score);
  appendContextRow(details, "Sources", selected.Sources || (selectedGraphNode && selectedGraphNode.sources));
  appendContextRow(details, "Source count", selectedGraphNode && selectedGraphNode.source_count);
  appendContextRow(details, "Relationships", selectedGraphNode ? graphData.edges.filter(
    (edge) => edge.from === selectedGraphNode.id || edge.to === selectedGraphNode.id
  ).length : undefined);

  if (selectedNodeDetails && selectedNodeDetails.id !== selectedKeyPlayer.Canonical_ID) {
    const centerButton = document.createElement("button");
    centerButton.type = "button";
    centerButton.className = "center-entity-button";
    centerButton.textContent = "Center network on this entity";
    centerButton.addEventListener("click", () => selectKeyPlayer(selectedNodeDetails.id));
    details.appendChild(centerButton);
  }
}

function renderAssociatedCases() {
  const container = document.getElementById("key-player-cases");
  container.replaceChildren();
  if (!selectedKeyPlayer) {
    setPanelState(container, "Case associations are unavailable.", true);
    return;
  }
  if (!selectedCases) {
    setPanelState(container, "Unable to load case associations.", true);
    return;
  }
  if (selectedCases.length === 0) {
    setPanelState(container, "No matching case-entity records were found.");
    return;
  }

  selectedCases.forEach((caseRecord) => {
    const link = document.createElement("a");
    link.className = "case-association";
    link.href = `/cases/${encodeURIComponent(caseRecord.fir_id)}/graph`;
    appendText(link, "strong", caseRecord.fir_id);
    appendText(
      link,
      "span",
      [caseRecord.crime_type, caseRecord.district, caseRecord.status].filter(Boolean).join(" · ")
        || "Case context"
    );
    const records = caseRecord.entity_records || [];
    const context = records.map((record) => {
      const role = record.role
        && record.role.toLocaleLowerCase() !== String(record.entity_type || "").toLocaleLowerCase()
        ? ` · ${record.role}`
        : "";
      const source = record.source ? ` · Source: ${record.source}` : "";
      return `${record.entity_type}${role} · ${statusLabel(record.confidence_tier)}${source}`;
    }).join("; ");
    if (context) appendText(link, "span", context);
    container.appendChild(link);
  });
}

function renderReviewItems(containerId, records, error, toItem, emptyMessage) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  if (error) {
    setPanelState(container, "Unable to load this information.", true);
    return;
  }
  if (!records || records.length === 0) {
    setPanelState(container, emptyMessage);
    return;
  }
  records.forEach((record) => {
    const item = toItem(record);
    container.appendChild(item);
  });
}

function makeReviewItem(title, detail, href, warning = false) {
  const item = document.createElement(href ? "a" : "div");
  item.className = `review-item${warning ? " review-item-warning" : ""}`;
  if (href) item.href = href;
  appendText(item, "span", title, "review-item-title");
  if (detail) appendText(item, "span", detail, "review-item-detail");
  return item;
}

function renderAlerts(result) {
  const alerts = result.data || [];
  const temporalAlert = alerts.find((alert) => alert.type === "temporal_burst");
  const visibleAlerts = alerts.slice(0, MAX_REVIEW_ITEMS);
  if (temporalAlert && !visibleAlerts.includes(temporalAlert)) {
    visibleAlerts[visibleAlerts.length - 1] = temporalAlert;
  }
  renderReviewItems(
    "alerts-list",
    result.data && visibleAlerts,
    result.error,
    (alert) => makeReviewItem(
      alert.type === "temporal_burst" ? "Temporal activity alert" : "Structural anomaly",
      `${alert.entity_label} · ${alert.severity} · ${alert.detail}`,
      "/alerts"
    ),
    "No alert items are currently available."
  );
}

function renderPriorities(result) {
  renderReviewItems(
    "priority-list",
    result.data && result.data.scores,
    result.error,
    (entity) => makeReviewItem(
      `${entity.Label} · ${entity.Entity_Type}`,
      `Priority for review: ${entity.Risk_Score} (${entity.Risk_Tier})`,
      `/risk-scoring`
    ),
    "No risk-scoring items are currently available."
  );
}

function renderSuggestions(result) {
  renderReviewItems(
    "suggestions-list",
    result.data && result.data.slice(0, MAX_SUGGESTIONS),
    result.error,
    (link) => makeReviewItem(
      `${link.label_a} ↔ ${link.label_b}`,
      `${link.type_a} / ${link.type_b} · Score ${Number(link.combined_score).toFixed(3)} · ${link.shared_neighbor_count} shared neighbor(s)`,
      "/hidden-links",
      true
    ),
    "No graph-similarity suggestions are currently available."
  );
}

function renderCommunities(result) {
  renderReviewItems(
    "communities-summary",
    result.data && result.data.slice(0, 3),
    result.error,
    (community) => makeReviewItem(
      `Algorithmic community ${community.community_id}`,
      `${community.size} entities · ${community.dominant_type} dominant type · ${community.internal_edges} internal edges`,
      "/communities"
    ),
    "No detected communities are currently available."
  );
}

function caseEdgeStatus(caseRecord) {
  const records = caseRecord.entity_records || [];
  if (records.some((record) => record.confidence_tier === "ai_inference")) return "ai_suggested";
  if (records.some((record) => record.confidence_tier === "observed_fact")) return "reported";
  return "data-derived";
}

function caseEdgeTitle(caseRecord) {
  const records = caseRecord.entity_records || [];
  const roles = [...new Set(records.map((record) => record.role).filter(Boolean))];
  const roleText = roles.length ? ` · Role recorded: ${roles.join(", ")}` : "";
  const status = caseEdgeStatus(caseRecord);
  const provenance = status === "ai_suggested"
    ? "Analytical inference — unconfirmed"
    : status === "reported" ? "Reported case context" : "Data-derived case context";
  const sources = [...new Set(records.map((record) => record.source).filter(Boolean))];
  const sourceText = sources.length ? ` · Source: ${sources.join(", ")}` : "";
  return `Case entity record${roleText} · ${provenance}${sourceText}`;
}

function networkNodeTitle(node) {
  if (node.node_type === "case") {
    const record = node.case_record;
    const context = (record.entity_records || []).map((entity) => {
      const role = entity.role ? ` · Role: ${entity.role}` : "";
      const source = entity.source ? ` · Source: ${entity.source}` : "";
      return `${entity.entity_type}${role} · ${statusLabel(entity.confidence_tier)}${source}`;
    });
    return [
      node.label,
      record.crime_type,
      record.district,
      "Associated case context",
      ...context,
    ].filter(Boolean).join("\n");
  }
  return [
    node.label,
    node.entity_type,
    node.roles ? `Roles: ${node.roles}` : "",
    node.sources ? `Sources: ${node.sources}` : "",
  ].filter(Boolean).join("\n");
}

function networkNode(node, x, y, isCenter = false) {
  const isCase = node.node_type === "case";
  return {
    id: node.id,
    label: node.label,
    group: node.entity_type,
    shape: isCase ? "box" : "dot",
    color: isCenter
      ? { background: "#0f766e", border: "#d7fffa", highlight: { background: "#14b8a6", border: "#ffffff" } }
      : isCase
        ? { background: "#493a23", border: CASE_COLOR, highlight: { background: "#66502e", border: "#ffe0a3" } }
        : { background: ENTITY_COLORS[node.entity_type] || "#94a3b8", border: "#15202b", highlight: { background: "#e2e8f0", border: "#ffffff" } },
    borderWidth: isCenter ? 4 : isCase ? 2 : 1,
    size: isCenter ? 32 : isCase ? 20 : Math.max(10, Math.min(node.size || 12, 24)),
    font: { color: "#e8eef3", size: isCenter ? 15 : 10 },
    x,
    y,
    fixed: { x: true, y: true },
    title: networkNodeTitle(node),
    node_type: node.node_type || "entity",
    canonical_id: node.id,
    details: node,
  };
}

function renderNetwork() {
  if (!graphData || !selectedKeyPlayer) {
    if (network) network.destroy();
    network = null;
    networkContainer.replaceChildren();
    networkState.textContent = graphData
      ? "Centrality results are unavailable; no key entity was selected."
      : "Unable to load the graph data.";
    networkState.classList.remove("hidden");
    document.getElementById("network-counts").textContent = "Network unavailable";
    return;
  }

  const center = graphData.nodes.find((node) => node.id === selectedKeyPlayer.Canonical_ID);
  if (!center) {
    if (network) network.destroy();
    network = null;
    networkContainer.replaceChildren();
    networkState.textContent = "The selected key entity is not present in the current graph data.";
    networkState.classList.remove("hidden");
    document.getElementById("network-counts").textContent = "Network unavailable";
    return;
  }

  const incidentEdges = graphData.edges.filter(
    (edge) => edge.from === center.id || edge.to === center.id
  );
  const edgeWeightByNeighbor = new Map();
  incidentEdges.forEach((edge) => {
    const neighborId = edge.from === center.id ? edge.to : edge.from;
    edgeWeightByNeighbor.set(
      neighborId,
      Math.max(edgeWeightByNeighbor.get(neighborId) || 0, Number(edge.value) || 0)
    );
  });
  const connectedNodes = graphData.nodes
    .filter((node) => edgeWeightByNeighbor.has(node.id))
    .sort((left, right) =>
      edgeWeightByNeighbor.get(right.id) - edgeWeightByNeighbor.get(left.id)
      || left.id.localeCompare(right.id)
    );
  const entityNodes = connectedNodes.slice(0, MAX_GRAPH_NEIGHBORS);
  const allAssociatedCases = selectedCases || [];
  const caseNodes = allAssociatedCases.slice(0, MAX_CASE_NODES).map((caseRecord) => ({
    id: `case::${caseRecord.fir_id}`,
    label: caseRecord.fir_id,
    entity_type: "Case",
    node_type: "case",
    case_record: caseRecord,
    size: 20,
  }));
  const nodesById = new Map([
    [center.id, center],
    ...entityNodes.map((node) => [node.id, node]),
    ...caseNodes.map((node) => [node.id, node]),
  ]);
  const dataEdges = graphData.edges.filter(
    (edge) => nodesById.has(edge.from) && nodesById.has(edge.to)
  );
  const caseEdges = caseNodes.map((caseNode) => ({
    from: center.id,
    to: caseNode.id,
    title: caseEdgeTitle(caseNode.case_record),
    status: caseEdgeStatus(caseNode.case_record),
    is_case_context: true,
  }));

  const positionedNodes = [
    networkNode(center, 0, 0, true),
    ...entityNodes.map((node, index) => {
      const angle = (2 * Math.PI * index) / Math.max(entityNodes.length, 1);
      const radius = 225;
      return networkNode(node, radius * Math.cos(angle), radius * Math.sin(angle));
    }),
    ...caseNodes.map((node, index) => {
      const spread = Math.PI * 0.54;
      const angle = Math.PI * 0.23 + spread * (index + 1) / (caseNodes.length + 1);
      const radius = 260;
      return networkNode(node, radius * Math.cos(angle), radius * Math.sin(angle));
    }),
  ];
  const positionedEdges = [
    ...dataEdges.map((edge, index) => ({
      id: `data-edge-${index}`,
      from: edge.from,
      to: edge.to,
      title: `${edge.title || "Relationship"} · Weight: ${edge.value}`,
      rel_type: edge.title || "",
      value: edge.value,
      color: { color: "#66758a", highlight: "#4fd1c5" },
      smooth: edge.from === center.id || edge.to === center.id
        ? false
        : { enabled: true, type: "curvedCW", roundness: 0.12 },
    })),
    ...caseEdges.map((edge, index) => ({
      id: `case-edge-${index}`,
      from: edge.from,
      to: edge.to,
      title: edge.title,
      width: 1.5,
      dashes: edge.status === "ai_suggested",
      color: { color: edge.status === "ai_suggested" ? "#c4b5fd" : CASE_COLOR },
      smooth: false,
    })),
  ];

  networkState.classList.add("hidden");
  if (network) network.destroy();
  network = new vis.Network(
    networkContainer,
    {
      nodes: new vis.DataSet(positionedNodes),
      edges: new vis.DataSet(positionedEdges),
    },
    {
      physics: false,
      layout: { improvedLayout: false },
      interaction: { hover: true, tooltipDelay: 120, dragNodes: false },
      nodes: { shape: "dot", font: { face: "Segoe UI, system-ui, sans-serif" } },
      edges: {
        scaling: { min: 1, max: 7 },
        smooth: { enabled: true, type: "dynamic" },
        arrows: { to: false },
      },
    }
  );
  network.on("click", (event) => {
    if (!event.nodes.length) return;
    const clicked = nodesById.get(event.nodes[0]);
    if (clicked && clicked.node_type !== "case") {
      selectedNodeDetails = clicked;
      renderKeyPlayerDetails();
    }
  });
  network.fit({ animation: false });
  const caseCountText = selectedCases === null
    ? "case associations unavailable"
    : `${caseNodes.length} of ${allAssociatedCases.length} associated case(s) shown`;
  document.getElementById("network-counts").textContent =
    `${entityNodes.length} of ${connectedNodes.length} connected entities shown (highest recorded edge weights) · ${dataEdges.length} existing relationships · ${caseCountText}`;
}

async function selectKeyPlayer(canonicalId) {
  const influencer = influencers.find((item) => item.Canonical_ID === canonicalId);
  const graphNode = graphData && graphData.nodes.find((item) => item.id === canonicalId);
  if (!influencer && !graphNode) return;
  selectedKeyPlayer = influencer || {
    Canonical_ID: graphNode.id,
    Label: graphNode.label,
    Entity_Type: graphNode.entity_type,
    Roles: graphNode.roles,
    Sources: graphNode.sources,
  };
  selectedNodeDetails = null;
  if (influencer) keyPlayerSelector.value = canonicalId;
  renderKeyPlayerDetails();
  const result = await loadResource(`/api/cases/entity/${encodeURIComponent(canonicalId)}`);
  selectedCases = result.data ? result.data.cases : null;
  renderAssociatedCases();
  renderNetwork();
}

async function initializeDashboard() {
  const [cases, graph, influencerResult, alerts, priorities, suggestions, communities] = await Promise.all([
    loadResource(API.cases),
    loadResource(API.graph),
    loadResource(API.influencers),
    loadResource(API.alerts),
    loadResource(API.risk),
    loadResource(API.hiddenLinks),
    loadResource(API.communities),
  ]);

  graphData = graph.data;
  influencers = influencerResult.data ? influencerResult.data.influencers || [] : [];
  updateMetrics({ cases, graph, alerts });
  renderAlerts(alerts);
  renderPriorities(priorities);
  renderSuggestions(suggestions);
  renderCommunities(communities);
  populateKeyPlayerOptions();
  keyPlayerSelector.addEventListener("change", () => selectKeyPlayer(keyPlayerSelector.value));

  if (influencers.length) {
    await selectKeyPlayer(influencers[0].Canonical_ID);
  } else {
    renderKeyPlayerDetails();
    renderAssociatedCases();
    renderNetwork();
  }
}

initializeDashboard();
