/* =========================================================
   CIPHER — Alerts Page
   ========================================================= */

const API_URL = "/api/alerts";

let allAlerts = [];


/* =========================================================
   DOM ELEMENTS
   ========================================================= */

const totalAlerts = document.getElementById("totalAlerts");
const criticalAlerts = document.getElementById("criticalAlerts");
const highAlerts = document.getElementById("highAlerts");
const mediumAlerts = document.getElementById("mediumAlerts");
const lowAlerts = document.getElementById("lowAlerts");

const alertType = document.getElementById("alertType");
const severity = document.getElementById("severity");
const search = document.getElementById("search");

const applyFilters = document.getElementById("applyFilters");
const resetFilters = document.getElementById("resetFilters");

const loadingState = document.getElementById("loadingState");
const errorState = document.getElementById("errorState");
const emptyState = document.getElementById("emptyState");

const alertsContainer = document.getElementById("alertsContainer");
const alertsTableBody = document.getElementById("alertsTableBody");
const resultCount = document.getElementById("resultCount");


/* =========================================================
   INITIAL LOAD
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
    loadAllAlerts();

    applyFilters.addEventListener("click", applyAlertFilters);

    resetFilters.addEventListener("click", resetAlertFilters);

    search.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            applyAlertFilters();
        }
    });
});


/* =========================================================
   LOAD ALL ALERTS
   ========================================================= */

async function loadAllAlerts() {

    showLoading();

    try {

        const response = await fetch(API_URL);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        allAlerts = await response.json();

        updateSummary(allAlerts);

        renderAlerts(allAlerts);

    } catch (error) {

        console.error("Failed to load alerts:", error);

        showError();
    }
}


/* =========================================================
   APPLY FILTERS
   ========================================================= */

async function applyAlertFilters() {

    showLoading();

    const params = new URLSearchParams();

    const selectedType = alertType.value;
    const selectedSeverity = severity.value;
    const searchValue = search.value.trim();


    if (selectedType) {
        params.append("type", selectedType);
    }

    if (selectedSeverity) {
        params.append("severity", selectedSeverity);
    }

    if (searchValue) {
        params.append("search", searchValue);
    }


    try {

        const url = params.toString()
            ? `${API_URL}?${params.toString()}`
            : API_URL;

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const filteredAlerts = await response.json();

        renderAlerts(filteredAlerts);

    } catch (error) {

        console.error("Failed to filter alerts:", error);

        showError();
    }
}


/* =========================================================
   RESET
   ========================================================= */

function resetAlertFilters() {

    alertType.value = "";
    severity.value = "";
    search.value = "";

    renderAlerts(allAlerts);
}


/* =========================================================
   SUMMARY
   ========================================================= */

function updateSummary(alerts) {

    totalAlerts.textContent = alerts.length;

    criticalAlerts.textContent =
        alerts.filter(a => a.severity === "Critical").length;

    highAlerts.textContent =
        alerts.filter(a => a.severity === "High").length;

    mediumAlerts.textContent =
        alerts.filter(a => a.severity === "Medium").length;

    lowAlerts.textContent =
        alerts.filter(a => a.severity === "Low").length;
}


/* =========================================================
   RENDER ALERTS
   ========================================================= */

function renderAlerts(alerts) {

    hideAllStates();

    alertsTableBody.innerHTML = "";

    resultCount.textContent =
        `${alerts.length} alert${alerts.length === 1 ? "" : "s"}`;


    if (!alerts.length) {

        emptyState.classList.remove("hidden");

        return;
    }


    alertsContainer.classList.remove("hidden");


    alerts.forEach(alert => {

        const row = document.createElement("tr");

        const severityClass =
            getSeverityClass(alert.severity);

        const typeLabel =
            getTypeLabel(alert.type);

        const caseCount =
            Array.isArray(alert.case_ids)
                ? alert.case_ids.length
                : 0;


        row.innerHTML = `
            <td>
                <span class="badge ${severityClass}">
                    ${escapeHTML(alert.severity)}
                </span>
            </td>

            <td>
                <span class="type-badge">
                    ${escapeHTML(typeLabel)}
                </span>
            </td>

            <td>
                <span class="entity-name">
                    ${escapeHTML(alert.entity_label)}
                </span>

                <span class="entity-id">
                    ${escapeHTML(alert.alert_id)}
                </span>
            </td>

            <td>
                ${escapeHTML(alert.entity_type || "—")}
            </td>

            <td>
                <div class="detail-text">
                    ${escapeHTML(alert.detail)}
                </div>
            </td>

            <td>
                <span class="case-count">
                    ${caseCount}
                </span>
            </td>
        `;

        alertsTableBody.appendChild(row);
    });
}


/* =========================================================
   HELPERS
   ========================================================= */

function getSeverityClass(severity) {

    switch (severity) {

        case "Critical":
            return "badge-critical";

        case "High":
            return "badge-high";

        case "Medium":
            return "badge-medium";

        default:
            return "badge-low";
    }
}


function getTypeLabel(type) {

    if (type === "temporal_burst") {
        return "Temporal Burst";
    }

    if (type === "anomaly") {
        return "Structural Anomaly";
    }

    return type || "Unknown";
}


/* =========================================================
   SAFE HTML
   ========================================================= */

function escapeHTML(value) {

    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


/* =========================================================
   UI STATES
   ========================================================= */

function hideAllStates() {

    loadingState.classList.add("hidden");
    errorState.classList.add("hidden");
    emptyState.classList.add("hidden");
    alertsContainer.classList.add("hidden");
}


function showLoading() {

    hideAllStates();

    loadingState.classList.remove("hidden");
}


function showError() {

    hideAllStates();

    errorState.classList.remove("hidden");
}