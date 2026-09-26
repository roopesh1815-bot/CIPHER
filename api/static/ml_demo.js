const summaryEl = document.getElementById("run-summary");
const predictionsEl = document.getElementById("prediction-list");

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function renderMetrics(payload) {
  summaryEl.replaceChildren();
  if (!payload.available) {
    summaryEl.appendChild(textElement("p", payload.message));
    return;
  }

  summaryEl.appendChild(textElement(
    "p",
    `${payload.model_type} · ${payload.model_version} · ${payload.dataset_version}`
  ));
  const metrics = payload.evaluation.test.model;
  const baseline = payload.evaluation.test.adamic_adar_baseline;
  const panel = document.createElement("div");
  panel.className = "metrics";
  [
    ["Test positive prevalence", metrics.positive_prevalence],
    ["Model accuracy", metrics.accuracy],
    ["Model precision", metrics.precision],
    ["Model recall", metrics.recall],
    ["Model F1", metrics.f1],
    ["Model ROC-AUC", metrics.roc_auc],
    ["Model average precision", metrics.average_precision],
    ["Adamic–Adar average precision", baseline.average_precision],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.append(
      textElement("div", label, "metric-label"),
      textElement("div", Number(value).toFixed(3), "metric-value")
    );
    panel.appendChild(item);
  });
  summaryEl.appendChild(panel);
}

function renderPredictions(rows) {
  predictionsEl.replaceChildren();
  rows.forEach((row) => {
    const card = document.createElement("article");
    card.className = "prediction";
    card.append(
      textElement(
        "strong",
        `${row.source_entity_id} ↔ ${row.target_entity_id}`
      ),
      textElement(
        "p",
        `Model score: ${Number(row.model_score).toFixed(3)} · Period: ${row.prediction_period}`
      ),
      textElement("p", `Status: ${row.status}`)
    );
    predictionsEl.appendChild(card);
  });
  if (!rows.length) predictionsEl.appendChild(textElement("p", "No ML-suggested relationships are available."));
}

async function loadDemo() {
  try {
    const response = await fetch("/api/ml-demo");
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const payload = await response.json();
    renderMetrics(payload);
    renderPredictions(payload.predictions || []);
  } catch (error) {
    summaryEl.replaceChildren(textElement("p", error.message, "state-error"));
  }
}

loadDemo();
