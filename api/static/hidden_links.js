const listEl = document.getElementById("link-list");
const detailEl = document.getElementById("detail-panel");
const totalEl = document.getElementById("total-count");

async function fetchLinks() {
  const type = document.getElementById("filter-type").value;
  const minScore = document.getElementById("filter-min-score").value;
  const search = document.getElementById("filter-search").value;

  const params = new URLSearchParams();
  if (type) params.set("entity_type", type);
  if (minScore) params.set("min_score", minScore);
  if (search) params.set("search", search);

  const res = await fetch(`/api/hidden-links?${params.toString()}`);
  if (!res.ok) {
    listEl.innerHTML = `<p class="error">Failed to load hidden links (${res.status})</p>`;
    return;
  }
  const links = await res.json();
  renderList(links);
}

function renderList(links) {
  totalEl.textContent = links.length;
  listEl.innerHTML = "";
  links.forEach((link) => {
    const card = document.createElement("div");
    card.className = "link-card";
    card.innerHTML = `
      <div class="pair">${link.label_a} &harr; ${link.label_b}</div>
      <div class="types">${link.type_a} · ${link.type_b}</div>
      <div class="badges">
        <span class="badge score">Score: ${link.combined_score.toFixed(3)}</span>
        <span class="badge">Jaccard: ${link.jaccard.toFixed(3)}</span>
        <span class="badge">Shared: ${link.shared_neighbor_count}</span>
      </div>
      <div class="note">${link.note}</div>
    `;
    card.addEventListener("click", () => showDetail(link, card));
    listEl.appendChild(card);
  });
}

function showDetail(link, card) {
  document.querySelectorAll(".link-card").forEach((c) => c.classList.remove("selected"));
  card.classList.add("selected");

  detailEl.innerHTML = `
    <h2>${link.label_a} &harr; ${link.label_b}</h2>
    <p><strong>Types:</strong> ${link.type_a} / ${link.type_b}</p>
    <p><strong>Combined score:</strong> ${link.combined_score.toFixed(4)}</p>
    <p><strong>Jaccard:</strong> ${link.jaccard.toFixed(4)}</p>
    <p><strong>Adamic-Adar:</strong> ${link.adamic_adar.toFixed(4)}</p>
    <p><strong>Shared neighbours (${link.shared_neighbor_count}):</strong></p>
    <ul class="shared-list">${link.shared_neighbors.map((n) => `<li>${n}</li>`).join("")}</ul>
    <p class="note">${link.note}</p>
  `;
}

document.getElementById("apply-btn").addEventListener("click", fetchLinks);
document.getElementById("reset-btn").addEventListener("click", () => {
  document.getElementById("filter-type").value = "";
  document.getElementById("filter-min-score").value = "";
  document.getElementById("filter-search").value = "";
  fetchLinks();
});

fetchLinks();