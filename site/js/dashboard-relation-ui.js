function mappingStatusText(event) {
  const grade = event.relation_grade || "UNMAPPED";
  if ((grade === "A" || grade === "B") && event.relation_ingest_mode === "MANUAL") {
    return "검증 관계 · 영구등록";
  }
  if (grade === "A") return "직접 당사자";
  if (grade === "B") return "자동 매핑";
  if (grade === "THEME" || grade === "C") return "테마 후보";
  if (grade === "PROXY") return "프록시";
  return "미매핑";
}

function mappingStatusClass(event) {
  const grade = event.relation_grade || "UNMAPPED";
  if ((grade === "A" || grade === "B") && event.relation_ingest_mode === "MANUAL") {
    return "mapping-status-verified";
  }
  if (grade === "A" || grade === "B") return "mapping-status-auto";
  if (grade === "THEME" || grade === "C") return "mapping-status-candidate";
  return "mapping-status-reference";
}

function decorateMappingStatus(events) {
  const tbody = document.getElementById("eventsTableBody");
  if (!tbody || !events || !events.length) return;
  const rows = Array.from(tbody.querySelectorAll("tr"));
  rows.forEach((row, index) => {
    const event = events[index];
    const cell = row.children[6];
    if (!event || !cell) return;
    const status = document.createElement("div");
    status.className = `mapping-status ${mappingStatusClass(event)}`;
    status.textContent = mappingStatusText(event);
    cell.appendChild(status);
  });
}

const baseRenderTableForMappingStatus = window.renderTable;
if (typeof baseRenderTableForMappingStatus === "function") {
  window.renderTable = function renderTableWithMappingStatus(events) {
    baseRenderTableForMappingStatus(events);
    decorateMappingStatus(events);
  };
}
