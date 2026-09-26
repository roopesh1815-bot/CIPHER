const listEl = document.getElementById("community-list");
const detailEl = document.getElementById("detail-panel");
const totalEl = document.getElementById("total-count");

async function fetchCommunities() {
  const type = document.getElementById("filter-type").value;
  const suspect = document.getElementById("filter-suspect").value;
  const minSize = document.getElementById("filter-min-size").value;

  const params = new URLSearchParams();
  if (type) params.set("dominant_type", type);
  if (suspect) params.set("has_suspect", suspect);
  if (minSize) params.set("min_size", minSize);

  const res = await fetch(`/api/communities?${params.toString()}`);
  if (!res.ok) {
    listEl.innerHTML = `<p class="error">Failed to load communities (${res.status})</p>`;
    return;
  }
  const communities = await res.json();
  renderList(communities);
}

function renderList(communities) {
  totalEl.textContent = communities.length;
  listEl.innerHTML = "";
  communities.forEach((c) => {
    const card = document.createElement("div");
    card.className = "community-card";
    card.innerHTML = `
      <div class="label">${c.label} &middot; ${c.dominant_type}</div>
      <div class="meta">${c.size} members · ${c.internal_edges} internal links</div>
      <div class="badges">
        ${c.has_suspect ? '<span class="badge suspect">Contains flagged suspect</span>' : ""}
        <span class="badge verified">Cross-verified: ${c.cross_verified}</span>
      </div>
    `;
    card.addEventListener("click", () => showDetail(c.community_id, card));
    listEl.appendChild(card);
  });
}

async function showDetail(communityId, card) {
  document.querySelectorAll(".community-card").forEach((el) => el.classList.remove("selected"));
  card.classList.add("selected");

  detailEl.innerHTML = `<p class="empty-state">Loading...</p>`;
  const res = await fetch(`/api/communities/${communityId}`);
  if (!res.ok) {
    detailEl.innerHTML = `<p class="error">Failed to load community detail</p>`;
    return;
  }
  const c = await res.json();
  detailEl.innerHTML = `
    <h2>${c.label}</h2>
    <p><strong>Dominant type:</strong> ${c.dominant_type}</p>
    <p><strong>Size:</strong> ${c.size} · <strong>Internal edges:</strong> ${c.internal_edges}</p>
    <p><strong>Cross-verified members:</strong> ${c.cross_verified}</p>
    ${c.has_suspect ? '<p class="warn">Contains at least one flagged suspect</p>' : ""}
    <p><strong>Members (${c.members.length}):</strong></p>
    <ul class="member-list">${c.members.map((m, i) => `<li>${m} <span style="color:#6b7280">(${c.member_ids[i] || ""})</span></li>`).join("")}</ul>
  `;
}

document.getElementById("apply-btn").addEventListener("click", fetchCommunities);
document.getElementById("reset-btn").addEventListener("click", () => {
  document.getElementById("filter-type").value = "";
  document.getElementById("filter-suspect").value = "";
  document.getElementById("filter-min-size").value = "";
  fetchCommunities();
});

fetchCommunities();