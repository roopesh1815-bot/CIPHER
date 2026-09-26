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
const CONTEXT_RADIUS = 440;

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

function buildRadialPositions(ringNodes) {
  const positions = {};
  const caseNodes = ringNodes.filter((node) => node.is_case_entity);
  const contextNodes = ringNodes.filter((node) => !node.is_case_entity);
  [
    [caseNodes, RING_RADIUS],
    [contextNodes, CONTEXT_RADIUS],
  ].forEach(([nodes, radius]) => {
    nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / nodes.length;
      positions[node.id] = {
        x: radius * Math.cos(angle),
        y: radius * Math.sin(angle),
      };
    });
  });
  return positions;
}

function showTooltip(lines) {
  tooltip.replaceChildren();
  lines.forEach((line) => {
    const row = document.createElement("div");
    row.textContent = line;
    tooltip.appendChild(row);
  });
  tooltip.classList.remove("hidden");
}

function edgeStatusText(edge) {
  return edge.status === "ai_suggested"
    ? "AI-suggested — not a confirmed link"
    : edge.status === "observed"
      ? "Observed"
      : "Data-derived";
}

function render(data) {
  const rawNodes = data.nodes || [];
  const rawEdges = data.edges || [];
  internalLinks = data.internal_links || [];
  centerReason = data.center_reason || "";

  // The backend applies the same case-scoped center rule for both graph pages.
  centerNode = rawNodes.find((n) => n.is_case_center === true) || null;

  if (!centerNode) {
    container.innerHTML = `<p style="color:#f87171;padding:20px;">No center node returned for this case.</p>`;
    return;
  }

  const ringNodes = rawNodes.filter((n) => n.id !== centerNode.id);
  const positions = buildRadialPositions(ringNodes);

  const nodes = new vis.DataSet(
    rawNodes.map((n) => {
      const isCenter = n.id === centerNode.id;
      const pos = isCenter ? { x: 0, y: 0 } : positions[n.id];
      return {
        id: n.id,
        label: n.label || n.id,
        roles: (n.case_roles || n.roles || []).toString().replace(/,/g, "|"),
        fusion_badge: n.fusion_badge || "",
        is_center: isCenter,
        title: isCenter
          ? (n.is_merged_center
            ? `Merged case center — ${(n.canonical_ids || []).length} case entities; underlying records are retained.`
            : `Case center — ${n.label}`)
          : `${n.label || n.id} (${n.entity_type || "Entity"})`,
        x: pos.x,
        y: pos.y,
        fixed: { x: true, y: true },
        color: {
          background: isCenter ? "#0f766e" : (TYPE_COLORS[n.entity_type] || "#9ca3af"),
          border: isCenter ? "#ffffff" : "#1f2937",
        },
        size: isCenter ? 38 : 16,
        font: { color: "#e5e7eb", size: isCenter ? 16 : 12 },
        shape: "dot",
      };
    })
  );

  const edges = new vis.DataSet(
    rawEdges.map((e, index) => {
      const isSpoke = e.from === centerNode.id || e.to === centerNode.id;
      const relationship = e.rel_type || e.title || "";
      return {
        id: `case-edge-${index}`,
        from: e.from,
        to: e.to,
        value: e.value ?? 1,
        rel_type: relationship,
        status: e.status || "data-derived",
        provenance: e.provenance || "",
        title: [relationship, edgeStatusText(e)].filter(Boolean).join(" · "),
        dashes: e.status === "ai_suggested",
        color: {
          color: e.status === "ai_suggested" ? "#c4b5fd" : (isSpoke ? "#4b5563" : "#2dd4bf"),
          highlight: "#2dd4bf",
        },
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
    const membersById = Object.fromEntries(
      (centerNode.member_metadata || []).map((member) => [member.canonical_id, member])
    );
    if (centerReason === "merged_suspects") {
      lines.push("Merged case center — multiple case entities with a suspect role; underlying records are retained.");
      (centerNode.member_metadata || []).forEach((member) => {
        const roles = member.roles.length ? ` (${member.roles.join(", ")})` : "";
        lines.push(`${member.label}${roles}`);
      });
      internalLinks.forEach((l) => {
        const a = membersById[l.from] || nodes.get(l.from) || { label: l.from };
        const b = membersById[l.to] || nodes.get(l.to) || { label: l.to };
        lines.push(`${a.label} \u2194 ${b.label}: ${l.rel_type || l.title || "Relationship"} (${edgeStatusText(l)})`);
      });
    } else if (centerReason === "fallback_no_suspect") {
      lines.push("No case entity has a suspect role; showing a case-based fallback center.");
    } else {
      lines.push("One case entity has a suspect role; this is a case-record designation, not a finding.");
    }
    showTooltip(lines);
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
    if (edge.rel_type) lines.push(edge.rel_type);
    lines.push(edgeStatusText(edge));
    if (edge.provenance) lines.push(`Provenance: ${edge.provenance}`);
    if (fromNode.roles) lines.push(`${fromNode.label}: ${fromNode.roles.replace(/\|/g, ", ")}`);
    if (toNode.roles) lines.push(`${toNode.label}: ${toNode.roles.replace(/\|/g, ", ")}`);
    const badges = [fromNode.fusion_badge, toNode.fusion_badge].filter(Boolean).join(" \u00b7 ");
    if (badges) lines.push(badges);

    showTooltip(lines);
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