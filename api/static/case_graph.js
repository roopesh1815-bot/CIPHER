const container = document.getElementById("graph-container");
const tooltip = document.getElementById("edge-tooltip");

const TYPE_COLORS = {
  Person: "#38bdf8",
  Account: "#facc15",
  Vehicle: "#a78bfa",
  Phone: "#34d399",
  Mobile: "#34d399",
  Location: "#f472b6",
};

const RING_RADIUS = 260;

let centerNode = null;
let internalLinks = [];
let centerReason = "";

async function loadCaseGraph() {
  const res = await fetch(`/api/graph/case/${FIR_ID}?hops=1`);
  if (!res.ok) {
    container.innerHTML = `<p style="color:#f87171;padding:20px;">Failed to load case graph (${res.status})</p>`;
    return;
  }
  const data = await res.json();
  render(data);
}

function buildRadialPositions(ringNodeIds) {
  const positions = {};
  const n = ringNodeIds.length;
  ringNodeIds.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / n;
    positions[id] = {
      x: RING_RADIUS * Math.cos(angle),
      y: RING_RADIUS * Math.sin(angle),
    };
  });
  return positions;
}

function render(data) {
  const rawNodes = data.nodes || [];
  const rawEdges = data.edges || [];
  internalLinks = data.internal_links || [];
  centerReason = data.center_reason || "";

  // The backend already decided the center — trust it, don't recompute.
  // Center node is the one carrying is_merged_center (true for a real merge,
  // false for a single-suspect or fallback center); other nodes don't have this key.
  centerNode = rawNodes.find((n) => n.is_merged_center !== undefined) || null;

  if (!centerNode) {
    container.innerHTML = `<p style="color:#f87171;padding:20px;">No center node returned for this case.</p>`;
    return;
  }

  const ringNodes = rawNodes.filter((n) => n.id !== centerNode.id);
  const positions = buildRadialPositions(ringNodes.map((n) => n.id));

  const nodes = new vis.DataSet(
    rawNodes.map((n) => {
      const isCenter = n.id === centerNode.id;
      const pos = isCenter ? { x: 0, y: 0 } : positions[n.id];
      return {
        id: n.id,
        label: n.label || n.id,
        roles: n.roles || "",
        fusion_badge: n.fusion_badge || "",
        is_center: isCenter,
        x: pos.x,
        y: pos.y,
        fixed: { x: true, y: true },
        color: {
          background: isCenter ? "#f87171" : (TYPE_COLORS[n.entity_type] || "#9ca3af"),
          border: isCenter ? "#ffffff" : "#1f2937",
        },
        size: isCenter ? 38 : 16,
        font: { color: "#e5e7eb", size: isCenter ? 16 : 12 },
        shape: "dot",
      };
    })
  );

  const edges = new vis.DataSet(
    rawEdges.map((e) => {
      const isSpoke = e.from === centerNode.id || e.to === centerNode.id;
      return {
        from: e.from,
        to: e.to,
        value: e.value || 0.5,
        title: e.title || "",
        color: { color: isSpoke ? "#4b5563" : "#2dd4bf", highlight: "#2dd4bf" },
        // spokes stay straight; node-to-node links curve so they don't overlap spokes
        smooth: isSpoke ? false : { type: "curvedCW", roundness: 0.2 },
      };
    })
  );

  const network = new vis.Network(container, { nodes, edges }, {
    physics: false,
    layout: { improvedLayout: false },
    edges: {
      scaling: { min: 1, max: 8 },
      arrows: { to: false },
    },
    interaction: { hover: true, dragNodes: false, zoomView: true, dragView: true },
  });

  network.on("hoverNode", (params) => {
    if (params.node !== centerNode.id) return;
    const lines = [`${centerNode.label}`];
    if (centerReason === "merged_suspects") {
      lines.push("Merged center — multiple suspects combined:");
      internalLinks.forEach((l) => {
        const a = nodes.get(l.from) || { label: l.from };
        const b = nodes.get(l.to) || { label: l.to };
        lines.push(`${a.label} \u2194 ${b.label}: ${l.title || "linked"}`);
      });
    } else if (centerReason === "fallback_no_suspect") {
      lines.push("No suspect tagged in this case — showing most-verified entity as center.");
    } else {
      lines.push("Single identified suspect.");
    }
    tooltip.innerHTML = lines.map((l) => `<div>${l}</div>`).join("");
    tooltip.classList.remove("hidden");
  });

  network.on("blurNode", () => {
    tooltip.classList.add("hidden");
  });

  network.on("hoverEdge", (params) => {
    const edge = edges.get(params.edge);
    if (!edge) return;

    const fromNode = nodes.get(edge.from);
    const toNode = nodes.get(edge.to);

    const lines = [`${fromNode.label} \u2194 ${toNode.label}`];
    if (edge.title) lines.push(edge.title);
    if (fromNode.roles) lines.push(`${fromNode.label}: ${fromNode.roles.replace(/\|/g, ", ")}`);
    if (toNode.roles) lines.push(`${toNode.label}: ${toNode.roles.replace(/\|/g, ", ")}`);
    const badges = [fromNode.fusion_badge, toNode.fusion_badge].filter(Boolean).join(" \u00b7 ");
    if (badges) lines.push(badges);

    tooltip.innerHTML = lines.map((l) => `<div>${l}</div>`).join("");
    tooltip.classList.remove("hidden");
  });

  network.on("blurEdge", () => {
    tooltip.classList.add("hidden");
  });

  network.on("dragging", () => {
    tooltip.classList.add("hidden");
  });

  network.fit({ animation: false });
}

document.addEventListener("mousemove", (e) => {
  if (!tooltip.classList.contains("hidden")) {
    tooltip.style.left = e.clientX + 12 + "px";
    tooltip.style.top = e.clientY + 12 + "px";
  }
});

loadCaseGraph();