if (!document.querySelector('link[href="css/relation-ui.css"]')) {
  const relationStyle = document.createElement("link");
  relationStyle.rel = "stylesheet";
  relationStyle.href = "css/relation-ui.css";
  document.head.appendChild(relationStyle);
}

function relationUiBadgeClass(grade) {
  if (grade === "A") return "badge-a";
  if (grade === "B") return "badge-b";
  if (grade === "THEME" || grade === "C") return "badge-theme";
  return "badge-unmapped";
}

function relationStateMeta(row) {
  const grade = row.relation_grade || "UNMAPPED";
  if ((grade === "A" || grade === "B") && row.ingest_mode === "MANUAL") {
    return {
      label: "영구관계 등록됨",
      css: "relation-state-persistent",
      description: "bb-invest 검증 후 관계 DB에 저장된 A/B 관계",
    };
  }
  if (grade === "A" || grade === "B") {
    return {
      label: "자동 확인",
      css: "relation-state-auto",
      description: grade === "A" ? "이벤트의 직접 당사자 또는 원문 명시 종목" : "자동 수집 근거에서 확인된 경제관계",
    };
  }
  if (grade === "THEME" || grade === "C") {
    return {
      label: "후보",
      css: "relation-state-candidate",
      description: "테마성·추정 관계로 영구 등록하지 않는 후보",
    };
  }
  if (grade === "PROXY") {
    return {
      label: "참고용",
      css: "relation-state-reference",
      description: "시장/섹터 반응을 보기 위한 프록시이며 개별주 후보가 아님",
    };
  }
  return {
    label: "미매핑",
    css: "relation-state-reference",
    description: "검증 가능한 상장사 관계를 아직 찾지 못함",
  };
}

function renderRelationCard(row) {
  const state = relationStateMeta(row);
  const knownDate = row.relation_known_date
    ? `<span><strong>관계 확인일</strong> ${escapeHtml(row.relation_known_date)}</span>`
    : "";
  const sourceName = row.evidence_source || "근거 출처 미표기";
  const fromEntity = row.from_entity
    ? `<span><strong>연결 기준</strong> ${escapeHtml(row.from_entity)}</span>`
    : "";
  const sourceLink = row.source_url
    ? `<a href="${escapeHtml(row.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link relation-source-link">근거 원문 ↗</a>`
    : "";
  const roleNames = {DIRECT:'직접 당사자',DIRECT_MENTION:'원문 당사자',CONTEXT_MENTION:'본문 언급 · 경제관계 미확인',
    SUPPLY_CONTRACT:'공급·납품 계약 상대방',OWNERSHIP_LINK:'지분·계열 관계',INVESTMENT_LINK:'투자·출자 관계',
    OFFICIAL_CONSORTIUM:'공식 프로젝트 참여사',IPO_MAJOR_SHAREHOLDER:'IPO 최대주주',IPO_INVESTOR:'IPO 투자사',MARKET_PROXY:'시장 반응 참고'};

  return `
    <article class="relation-item">
      <div class="relation-item-top">
        <div class="relation-ticker-wrap">
          <code class="relation-ticker">${escapeHtml(row.ticker || "미매핑")}</code>
          <strong>${escapeHtml(row.company_name || '')}</strong>
          <span class="badge ${relationUiBadgeClass(row.relation_grade)}">${escapeHtml(row.relation_grade || "UNMAPPED")}</span>
        </div>
        <span class="relation-state ${state.css}">${escapeHtml(state.label)}</span>
      </div>
      <div class="relation-type-line">
        <strong>${escapeHtml(roleNames[row.relation_type] || row.relation_type || "미매핑")}</strong>
        <span>${Number(row.relation_score || 0)}점</span>
      </div>
      <p class="relation-state-description">${escapeHtml(state.description)}</p>
      <div class="relation-meta">
        ${fromEntity}
        ${knownDate}
        <span><strong>근거</strong> ${escapeHtml(sourceName)}</span>
      </div>
      <p class="relation-evidence">${escapeHtml(row.evidence_text || "관계 근거가 아직 없습니다.")}</p>
      <p class="relation-state-description">수혜·악재 방향은 연결 사실만으로 확정하지 않습니다.</p>
      ${sourceLink}
    </article>
  `;
}

function renderRelationGroup(containerId, rows, emptyText) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (!rows.length) {
    container.innerHTML = `<div class="relation-empty">${escapeHtml(emptyText)}</div>`;
    return;
  }
  container.innerHTML = rows.map(renderRelationCard).join("");
}

function renderRelationOverview(detail) {
  const rows = detail.related_securities || [];
  const verified = rows.filter(row => row.relation_grade === "A" || row.relation_grade === "B");
  const candidates = rows.filter(row => row.relation_grade === "THEME" || row.relation_grade === "C");
  const references = rows.filter(row => row.relation_grade === "PROXY" || row.relation_grade === "UNMAPPED");
  const persistentCount = verified.filter(row => row.ingest_mode === "MANUAL").length;

  const summary = document.getElementById("relationSummary");
  if (summary) {
    const persistentText = persistentCount > 0 ? ` · 영구등록 ${persistentCount}개` : "";
    summary.innerHTML = `
      <div class="relation-summary-main">
        <strong>검증 A/B ${verified.length}개</strong>
        <span>후보 ${candidates.length}개 · 참고/미매핑 ${references.length}개${persistentText}</span>
      </div>
      <div class="relation-summary-note">A는 직접 당사자, B는 확인된 경제관계입니다. THEME/C와 PROXY는 매매 후보 확정으로 보지 않습니다.</div>
    `;
  }

  renderRelationGroup("verifiedRelations", verified, "검증된 A/B 관련주가 아직 없습니다.");
  renderRelationGroup("candidateRelations", candidates, "현재 테마성 후보가 없습니다.");
  renderRelationGroup("referenceRelations", references, "참고용 프록시나 미매핑 항목이 없습니다.");
}

const baseRenderDetailForRelations = window.renderDetail;
if (typeof baseRenderDetailForRelations === "function") {
  window.renderDetail = function renderDetailWithRelations(detail) {
    baseRenderDetailForRelations(detail);
    renderRelationOverview(detail);
  };
}
