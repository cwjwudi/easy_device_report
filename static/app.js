const state = {
  templates: [],
  selectedTemplateId: null,
  lastReport: null,
  health: null,
  designerTemplate: null,
  designer: {
    activeTab: "page",
    selectedRegion: "header",
    selectedCell: { region: "header", row: 0, col: 0 },
    selectedBodyCustomTable: 0,
    schema: null,
    opcuaNodes: [],
  },
  opcuaBrowser: {
    nodes: [],
    childrenByNode: {},
    expanded: {},
    points: [],
    selectedNodeId: null,
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function clone(value) {
  return structuredClone(value || {});
}

function setStatus(selector, message, isError = false) {
  const el = $(selector);
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? "#b42318" : "#657184";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function currentTemplate() {
  return state.templates.find((item) => item.id === state.selectedTemplateId);
}

function ensureTemplateShape(template) {
  const config = clone(template);
  config.name ||= "未命名模板";
  config.page ||= { size: "A4", orientation: "portrait", margin_mm: 14 };
  config.opcua ||= { server_url: "mock://local", root_node: "ns=6;i=1000", node_values: {} };
  config.database ||= { type: "sqlite", path: state.health?.demo_db || "" };
  config.header ||= { title: "页眉", rows: [[{ type: "static", value: "" }]] };
  config.footer ||= { title: "页脚", rows: [[{ type: "static", value: "" }]] };
  config.body ||= { table: "", columns: [], filters: [], order_by: [], limit: 100 };
  config.header.rows = normalizeRegionRows(config.header.rows);
  config.footer.rows = normalizeRegionRows(config.footer.rows);
  config.body.columns ||= [];
  config.body.filters ||= [];
  config.body.order_by ||= [];
  config.body.custom_tables = Array.isArray(config.body.custom_tables) ? config.body.custom_tables : [];
  config.body.custom_tables = config.body.custom_tables.map((table, index) => ({
    title: table?.title || `自定义表格 ${index + 1}`,
    rows: normalizeRegionRows(table?.rows),
  }));
  return config;
}

function normalizeRegionRows(rows) {
  const normalized = Array.isArray(rows) && rows.length ? rows : [[{ type: "static", value: "" }]];
  const maxCols = Math.max(...normalized.map((row) => Math.max(row.length, 1)));
  return normalized.map((row) => {
    const next = row.map((cell) => (typeof cell === "object" && cell ? cell : { type: "static", value: cell ?? "" }));
    while (next.length < maxCols) next.push({ type: "static", value: "" });
    return next;
  });
}

function cellLabel(cell) {
  if (!cell || typeof cell !== "object") return String(cell ?? "");
  if (cell.type === "opcua") return `OPC UA: ${cell.node_id || ""}`;
  if (cell.type === "db_field") return `字段: ${cell.column || ""}`;
  if (cell.type === "db_summary") return `${cell.aggregate || "count"}(${cell.column || "*"})`;
  return cell.value || "";
}

function getSelectedCell() {
  const selected = state.designer.selectedCell;
  if (!state.designerTemplate || !selected) return null;
  if (selected.region === "body_custom") {
    const rows = state.designerTemplate.body?.custom_tables?.[selected.tableIndex || 0]?.rows;
    return rows?.[selected.row]?.[selected.col] || null;
  }
  const rows = state.designerTemplate[selected.region]?.rows;
  return rows?.[selected.row]?.[selected.col] || null;
}

function setSelectedCell(cell) {
  const selected = state.designer.selectedCell;
  if (!state.designerTemplate || !selected) return;
  if (selected.region === "body_custom") {
    const rows = state.designerTemplate.body?.custom_tables?.[selected.tableIndex || 0]?.rows;
    if (rows?.[selected.row]) rows[selected.row][selected.col] = cell;
  } else {
    state.designerTemplate[selected.region].rows[selected.row][selected.col] = cell;
  }
  renderDesigner();
}

function syncJsonEditor() {
  const editor = $("#templateEditor");
  if (editor && state.designerTemplate) editor.value = pretty(state.designerTemplate);
}

function syncDesignerFromInputs() {
  if (!state.designerTemplate) return;
  state.designerTemplate.name = $("#templateName")?.value.trim() || state.designerTemplate.name || "未命名模板";
  state.designerTemplate.page = {
    size: $("#pageSize")?.value || "A4",
    orientation: $("#pageOrientation")?.value || "portrait",
    margin_mm: Number($("#pageMargin")?.value || 14),
  };
  const body = state.designerTemplate.body;
  body.table = $("#bodyTable")?.value.trim() || body.table || "";
  body.limit = Number($("#bodyLimit")?.value || body.limit || 100);
  const orderColumn = $("#bodyOrderColumn")?.value || "";
  const orderDirection = $("#bodyOrderDirection")?.value || "ASC";
  body.order_by = orderColumn ? [{ column: orderColumn, direction: orderDirection }] : [];

  state.designerTemplate.opcua.server_url = $("#tplOpcServer")?.value.trim() || state.designerTemplate.opcua.server_url || "mock://local";
  state.designerTemplate.opcua.root_node = $("#tplOpcRoot")?.value.trim() || state.designerTemplate.opcua.root_node || "ns=6;i=1000";
  const dbType = $("#tplDbType")?.value || state.designerTemplate.database.type || "sqlite";
  state.designerTemplate.database.type = dbType;
  if (dbType === "mysql") {
    state.designerTemplate.database.name = $("#tplDbName")?.value.trim() || state.designerTemplate.database.name || "";
    state.designerTemplate.database.database = $("#tplDbName")?.value.trim() || state.designerTemplate.database.database || "";
    state.designerTemplate.database.host = $("#tplDbHost")?.value.trim() || state.designerTemplate.database.host || "127.0.0.1";
    state.designerTemplate.database.port = Number($("#tplDbPort")?.value || state.designerTemplate.database.port || 3306);
    state.designerTemplate.database.username = $("#tplDbUser")?.value.trim() || state.designerTemplate.database.username || "";
    state.designerTemplate.database.password = $("#tplDbPassword")?.value ?? state.designerTemplate.database.password ?? "";
    state.designerTemplate.database.charset ||= "utf8mb4";
  } else {
    state.designerTemplate.database.path = $("#tplDbPath")?.value.trim() || state.designerTemplate.database.path || "";
  }
  syncJsonEditor();
}

function parseEditorTemplate() {
  if (state.designerTemplate) {
    syncDesignerFromInputs();
    return { name: state.designerTemplate.name, config: clone(state.designerTemplate) };
  }
  const config = JSON.parse($("#templateEditor").value);
  const name = $("#templateName").value.trim() || config.name || "未命名模板";
  config.name = name;
  return { name, config };
}

function applyJsonToDesigner(showStatus = false) {
  try {
    state.designerTemplate = ensureTemplateShape(JSON.parse($("#templateEditor").value));
    state.designer.selectedCell = { region: "header", row: 0, col: 0 };
    state.designer.selectedBodyCustomTable = 0;
    renderDesigner();
    if (showStatus) setStatus("#templateStatus", "JSON 已应用到设计器");
    return true;
  } catch (error) {
    setStatus("#templateStatus", `JSON 格式错误：${error.message}`, true);
    return false;
  }
}

function currentDbConnection() {
  const type = $("#dbType").value;
  if (type === "sqlite") {
    return { type, path: $("#dbPath").value };
  }
  return {
    type,
    name: $("#dbName").value,
    host: $("#dbHost").value,
    port: Number($("#dbPort").value || 3306),
    username: $("#dbUser").value,
    password: $("#dbPassword").value,
    database: $("#dbName").value,
    charset: "utf8mb4",
  };
}

function templateDbConnection() {
  syncDesignerFromInputs();
  return clone(state.designerTemplate.database);
}

function getSchemaColumns() {
  const schema = state.designer.schema;
  const table = state.designerTemplate?.body?.table;
  const match = schema?.tables?.find((item) => item.table === table) || schema?.tables?.[0];
  return (match?.columns || []).map((column) => column.Field || column.name).filter(Boolean);
}

function allKnownColumns() {
  const fromSchema = getSchemaColumns();
  const fromBody = (state.designerTemplate?.body?.columns || []).map((column) => column.name);
  return Array.from(new Set([...fromBody, ...fromSchema])).filter(Boolean);
}

function renderSimpleTable(rows) {
  if (!rows || rows.length === 0) return "";
  return `<table class="report-table"><tbody>${rows
    .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

function renderReportCustomTables(tables) {
  return (tables || [])
    .map(
      (table) => `
        <section class="report-section">
          ${table.title ? `<h3>${escapeHtml(table.title)}</h3>` : ""}
          ${renderSimpleTable(table.rows)}
        </section>`
    )
    .join("");
}

function renderReport(report) {
  state.lastReport = report;
  const columns = report.body.columns || [];
  const rows = report.body.rows || [];
  $("#reportPreview").innerHTML = `
    <div class="report-title">
      <strong>${escapeHtml(report.name)}</strong>
      <span>生成时间 ${escapeHtml(report.generated_at)} · ${rows.length} 行</span>
    </div>
    ${renderSimpleTable(report.header.rows)}
    ${renderReportCustomTables(report.body.custom_tables)}
    <table class="report-table">
      <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
      <tbody>
        ${
          rows.length
            ? rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column.name])}</td>`).join("")}</tr>`).join("")
            : `<tr><td colspan="${Math.max(columns.length, 1)}">没有查询到数据</td></tr>`
        }
      </tbody>
    </table>
    ${renderSimpleTable(report.footer.rows)}
    <details>
      <summary>查询信息</summary>
      <pre>${escapeHtml(report.body.sql || "")}</pre>
      <pre>${escapeHtml(pretty(report.opcua_values || {}))}</pre>
    </details>
  `;
}

function renderTemplateList() {
  const list = $("#templateList");
  list.innerHTML = "";
  state.templates.forEach((template) => {
    const btn = document.createElement("button");
    btn.className = template.id === state.selectedTemplateId ? "active" : "";
    btn.textContent = `${template.name} #${template.id}`;
    btn.addEventListener("click", () => selectTemplate(template.id));
    list.appendChild(btn);
  });

  const select = $("#templateSelect");
  select.innerHTML = state.templates.map((template) => `<option value="${template.id}">${escapeHtml(template.name)}</option>`).join("");
  if (state.selectedTemplateId) select.value = String(state.selectedTemplateId);
}

function selectTemplate(id) {
  state.selectedTemplateId = Number(id);
  const template = currentTemplate();
  if (!template) return;
  state.designerTemplate = ensureTemplateShape(template.config);
  state.designer.selectedCell = { region: "header", row: 0, col: 0 };
  state.designer.selectedBodyCustomTable = 0;
  $("#templateName").value = state.designerTemplate.name;
  $("#templateSelect").value = String(template.id);
  renderTemplateList();
  renderDesigner();
}

function renderDesigner() {
  if (!state.designerTemplate) return;
  const tpl = state.designerTemplate;
  $("#templateName").value = tpl.name || "";
  $("#pageSize").value = tpl.page?.size || "A4";
  $("#pageOrientation").value = tpl.page?.orientation || "portrait";
  $("#pageMargin").value = tpl.page?.margin_mm ?? 14;
  $("#bodyLimit").value = tpl.body?.limit || 100;
  if ($("#tplOpcServer")) $("#tplOpcServer").value = tpl.opcua?.server_url || "";
  if ($("#tplOpcRoot")) $("#tplOpcRoot").value = tpl.opcua?.root_node || "ns=6;i=1000";
  if ($("#tplDbType")) $("#tplDbType").value = tpl.database?.type || "sqlite";
  if ($("#tplDbName")) $("#tplDbName").value = tpl.database?.database || tpl.database?.name || "";
  if ($("#tplDbHost")) $("#tplDbHost").value = tpl.database?.host || "";
  if ($("#tplDbPort")) $("#tplDbPort").value = tpl.database?.port || 3306;
  if ($("#tplDbUser")) $("#tplDbUser").value = tpl.database?.username || "";
  if ($("#tplDbPassword")) $("#tplDbPassword").value = tpl.database?.password || "";
  if ($("#tplDbPath")) $("#tplDbPath").value = tpl.database?.path || "";

  renderTabs();
  renderRegionTable("header");
  renderRegionTable("footer");
  renderBodyDesigner();
  renderPropertyPanel();
  syncJsonEditor();
}

function renderTabs() {
  $$("#designerTabs .tab").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === state.designer.activeTab));
  $$(".designer-tab").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${state.designer.activeTab}`));
}

function renderRegionTable(region) {
  const container = $(`#${region}Designer`);
  const rows = state.designerTemplate[region].rows;
  container.innerHTML = `
    <table class="designer-table">
      <tbody>
        ${rows
          .map(
            (row, rowIndex) => `
              <tr>
                ${row
                  .map((cell, colIndex) => {
                    const selected = state.designer.selectedCell?.region === region && state.designer.selectedCell?.row === rowIndex && state.designer.selectedCell?.col === colIndex;
                    return `<td><button class="designer-cell ${selected ? "selected" : ""}" data-region="${region}" data-row="${rowIndex}" data-col="${colIndex}">${escapeHtml(cellLabel(cell)) || "&nbsp;"}</button></td>`;
                  })
                  .join("")}
              </tr>`
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderBodyDesigner() {
  renderBodyTableSelect();
  renderOrderColumnSelect();
  renderBodyColumns();
  renderFilters();
  renderBodyCustomTables();
}

function renderBodyTableSelect() {
  const select = $("#bodyTable");
  if (!select) return;
  const current = state.designerTemplate.body.table || "";
  const tables = Array.from(new Set([current, ...(state.designer.schema?.tables || []).map((item) => item.table).filter(Boolean)])).filter(Boolean);
  select.innerHTML = tables.length
    ? tables.map((table) => `<option value="${escapeHtml(table)}">${escapeHtml(table)}</option>`).join("")
    : `<option value="">请先加载表结构</option>`;
  select.value = current || tables[0] || "";
}

function renderOrderColumnSelect() {
  const select = $("#bodyOrderColumn");
  const current = state.designerTemplate.body.order_by?.[0]?.column || "";
  const columns = allKnownColumns();
  select.innerHTML = `<option value="">不排序</option>${columns.map((column) => `<option value="${escapeHtml(column)}">${escapeHtml(column)}</option>`).join("")}`;
  select.value = current;
  $("#bodyOrderDirection").value = state.designerTemplate.body.order_by?.[0]?.direction || "ASC";
}

function renderBodyColumns() {
  const selected = state.designerTemplate.body.columns || [];
  const knownColumns = allKnownColumns();
  const rows = knownColumns.length ? knownColumns : selected.map((column) => column.name);
  $("#bodyColumnsDesigner").innerHTML = rows
    .map((name) => {
      const index = selected.findIndex((column) => column.name === name);
      const column = selected[index] || { name, label: name };
      return `
        <div class="column-row ${index >= 0 ? "enabled" : ""}">
          <label><input type="checkbox" data-column-toggle="${escapeHtml(name)}" ${index >= 0 ? "checked" : ""}> ${escapeHtml(name)}</label>
          <input data-column-label="${escapeHtml(name)}" value="${escapeHtml(column.label || name)}" ${index < 0 ? "disabled" : ""}>
          <button class="secondary icon-btn" data-column-move="${escapeHtml(name)}" data-dir="-1" ${index <= 0 ? "disabled" : ""}>↑</button>
          <button class="secondary icon-btn" data-column-move="${escapeHtml(name)}" data-dir="1" ${index < 0 || index >= selected.length - 1 ? "disabled" : ""}>↓</button>
        </div>`;
    })
    .join("");
}

function renderFilters() {
  const columns = allKnownColumns();
  const filters = state.designerTemplate.body.filters || [];
  $("#filterDesigner").innerHTML = filters.length
    ? filters
        .map((filter, index) => {
          const source = filter.source || { type: "literal", value: filter.value ?? "" };
          return `
            <div class="filter-row">
              <select data-filter-column="${index}">
                ${columns.map((column) => `<option value="${escapeHtml(column)}" ${filter.column === column ? "selected" : ""}>${escapeHtml(column)}</option>`).join("")}
              </select>
              <select data-filter-operator="${index}">
                ${["=", "!=", ">", ">=", "<", "<=", "LIKE"].map((op) => `<option value="${op}" ${filter.operator === op ? "selected" : ""}>${op}</option>`).join("")}
              </select>
              <select data-filter-source-type="${index}">
                <option value="literal" ${source.type !== "opcua" ? "selected" : ""}>固定值</option>
                <option value="opcua" ${source.type === "opcua" ? "selected" : ""}>OPC UA</option>
              </select>
              ${
                source.type === "opcua"
                  ? `<select data-filter-node="${index}">${opcuaNodeOptions(source.node_id || "")}</select><input data-filter-node-manual="${index}" value="${escapeHtml(source.node_id || "")}" placeholder="或手动输入节点">`
                  : `<input data-filter-value="${index}" value="${escapeHtml(source.value ?? filter.value ?? "")}" placeholder="筛选值">`
              }
              <button class="danger icon-btn" data-filter-remove="${index}">×</button>
            </div>`;
        })
        .join("")
    : `<div class="empty-note">暂无筛选条件。</div>`;
}

function selectedBodyCustomTable() {
  const tables = state.designerTemplate?.body?.custom_tables || [];
  if (!tables.length) return null;
  if (state.designer.selectedBodyCustomTable >= tables.length) state.designer.selectedBodyCustomTable = tables.length - 1;
  if (state.designer.selectedBodyCustomTable < 0) state.designer.selectedBodyCustomTable = 0;
  return tables[state.designer.selectedBodyCustomTable];
}

function renderBodyCustomTables() {
  const select = $("#bodyCustomTableSelect");
  const titleInput = $("#bodyCustomTableTitle");
  const container = $("#bodyCustomTableDesigner");
  if (!select || !titleInput || !container) return;
  const tables = state.designerTemplate.body.custom_tables || [];
  if (!tables.length) {
    select.innerHTML = `<option value="">暂无自定义表格</option>`;
    titleInput.value = "";
    titleInput.disabled = true;
    container.innerHTML = `<div class="empty-note">点击“添加表格”，可在正文中插入和页眉一样的自定义表格。</div>`;
    return;
  }
  titleInput.disabled = false;
  select.innerHTML = tables.map((table, index) => `<option value="${index}">${escapeHtml(table.title || `自定义表格 ${index + 1}`)}</option>`).join("");
  select.value = String(state.designer.selectedBodyCustomTable);
  const table = selectedBodyCustomTable();
  titleInput.value = table.title || "";
  container.innerHTML = `
    <table class="designer-table">
      <tbody>
        ${table.rows
          .map(
            (row, rowIndex) => `
              <tr>
                ${row
                  .map((cell, colIndex) => {
                    const selected = state.designer.selectedCell?.region === "body_custom" && state.designer.selectedCell?.tableIndex === state.designer.selectedBodyCustomTable && state.designer.selectedCell?.row === rowIndex && state.designer.selectedCell?.col === colIndex;
                    return `<td><button class="designer-cell ${selected ? "selected" : ""}" data-region="body_custom" data-table-index="${state.designer.selectedBodyCustomTable}" data-row="${rowIndex}" data-col="${colIndex}">${escapeHtml(cellLabel(cell)) || "&nbsp;"}</button></td>`;
                  })
                  .join("")}
              </tr>`
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderPropertyPanel() {
  const panel = $("#propertyPanel");
  if (!state.designerTemplate) {
    panel.innerHTML = `<div class="empty-note">请选择模板。</div>`;
    return;
  }
  const selected = state.designer.selectedCell;
  const canEditCell = ["header", "footer"].includes(state.designer.activeTab) || (state.designer.activeTab === "body" && selected?.region === "body_custom");
  if (!canEditCell) {
    panel.innerHTML = `
      <div class="empty-note">在页眉、页脚或正文自定义表格中点击单元格，可编辑单元格绑定。</div>
      <button class="secondary full-btn" id="designerPreviewBtn">预览当前模板</button>
    `;
    $("#designerPreviewBtn").addEventListener("click", previewEdited);
    return;
  }
  const cell = getSelectedCell();
  if (!cell || !selected) {
    panel.innerHTML = `<div class="empty-note">请选择一个单元格。</div>`;
    return;
  }
  const columns = allKnownColumns();
  const regionName = selected.region === "header" ? "页眉" : selected.region === "footer" ? "页脚" : "正文自定义表格";
  panel.innerHTML = `
    <div class="property-title">${regionName} · 第 ${selected.row + 1} 行 / 第 ${selected.col + 1} 列</div>
    <label class="field">
      <span>单元格类型</span>
      <select id="cellType">
        <option value="static" ${cell.type === "static" ? "selected" : ""}>静态文本</option>
        <option value="opcua" ${cell.type === "opcua" ? "selected" : ""}>OPC UA 节点值</option>
        <option value="db_field" ${cell.type === "db_field" ? "selected" : ""}>数据库首行字段</option>
        <option value="db_summary" ${cell.type === "db_summary" ? "selected" : ""}>统计值</option>
      </select>
    </label>
    <div id="cellPropertyFields"></div>
    <button class="secondary full-btn" id="designerPreviewBtn">预览当前模板</button>
  `;
  $("#cellType").addEventListener("change", (event) => {
    const type = event.target.value;
    const next = { type };
    if (type === "static") next.value = cell.value || "";
    if (type === "opcua") next.node_id = cell.node_id || state.designer.opcuaNodes[0]?.node_id || "";
    if (type === "db_field") next.column = cell.column || columns[0] || "";
    if (type === "db_summary") {
      next.aggregate = cell.aggregate || "count";
      next.column = cell.column || columns[0] || "";
    }
    setSelectedCell(next);
  });
  $("#designerPreviewBtn").addEventListener("click", previewEdited);
  renderCellPropertyFields();
}

function opcuaNodeOptions(current = "") {
  const nodes = state.designer.opcuaNodes;
  const values = Array.from(new Set([current, ...nodes.map((node) => node.node_id).filter(Boolean)])).filter(Boolean);
  return values.map((nodeId) => {
    const node = nodes.find((item) => item.node_id === nodeId);
    const label = node ? `${node.display_name || node.browse_name || nodeId} (${nodeId})` : nodeId;
    return `<option value="${escapeHtml(nodeId)}" ${nodeId === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");
}

function renderCellPropertyFields() {
  const cell = getSelectedCell();
  const container = $("#cellPropertyFields");
  const columns = allKnownColumns();
  if (!cell) return;
  if (cell.type === "opcua") {
    container.innerHTML = `
      <label class="field">
        <span>选择节点</span>
        <select id="cellNodeSelect">${opcuaNodeOptions(cell.node_id || "")}</select>
      </label>
      <label class="field">
        <span>手动节点 ID</span>
        <input id="cellNodeManual" value="${escapeHtml(cell.node_id || "")}">
      </label>
      <button class="secondary full-btn" id="browseTplOpcFromCellBtn">刷新节点列表</button>
    `;
    $("#cellNodeSelect").addEventListener("change", (event) => {
      cell.node_id = event.target.value;
      setSelectedCell(cell);
    });
    $("#cellNodeManual").addEventListener("input", (event) => {
      cell.node_id = event.target.value;
      syncJsonEditor();
      if (state.designer.selectedCell.region === "body_custom") renderBodyCustomTables();
      else renderRegionTable(state.designer.selectedCell.region);
    });
    $("#browseTplOpcFromCellBtn").addEventListener("click", browseTemplateOpc);
    return;
  }
  if (cell.type === "db_field") {
    container.innerHTML = `
      <label class="field">
        <span>字段</span>
        <select id="cellDbField">${columns.map((column) => `<option value="${escapeHtml(column)}" ${cell.column === column ? "selected" : ""}>${escapeHtml(column)}</option>`).join("")}</select>
      </label>
    `;
    $("#cellDbField").addEventListener("change", (event) => {
      cell.column = event.target.value;
      setSelectedCell(cell);
    });
    return;
  }
  if (cell.type === "db_summary") {
    container.innerHTML = `
      <label class="field">
        <span>统计方式</span>
        <select id="cellAggregate">
          <option value="count" ${cell.aggregate === "count" ? "selected" : ""}>count</option>
          <option value="sum" ${cell.aggregate === "sum" ? "selected" : ""}>sum</option>
          <option value="avg" ${cell.aggregate === "avg" ? "selected" : ""}>avg</option>
        </select>
      </label>
      <label class="field">
        <span>字段</span>
        <select id="cellSummaryColumn">${columns.map((column) => `<option value="${escapeHtml(column)}" ${cell.column === column ? "selected" : ""}>${escapeHtml(column)}</option>`).join("")}</select>
      </label>
    `;
    $("#cellAggregate").addEventListener("change", (event) => {
      cell.aggregate = event.target.value;
      setSelectedCell(cell);
    });
    $("#cellSummaryColumn").addEventListener("change", (event) => {
      cell.column = event.target.value;
      setSelectedCell(cell);
    });
    return;
  }
  container.innerHTML = `
    <label class="field">
      <span>文本</span>
      <textarea id="cellStaticValue">${escapeHtml(cell.value || "")}</textarea>
    </label>
  `;
  $("#cellStaticValue").addEventListener("input", (event) => {
    cell.value = event.target.value;
    syncJsonEditor();
    if (state.designer.selectedCell.region === "body_custom") renderBodyCustomTables();
    else renderRegionTable(state.designer.selectedCell.region);
  });
}

function mutateRegionTable(region, action) {
  let rows;
  if (region === "body_custom") {
    const table = selectedBodyCustomTable();
    if (!table) return;
    rows = table.rows;
  } else {
    rows = state.designerTemplate[region].rows;
  }
  const colCount = rows[0]?.length || 1;
  if (action === "add-row") rows.push(Array.from({ length: colCount }, () => ({ type: "static", value: "" })));
  if (action === "add-col") rows.forEach((row) => row.push({ type: "static", value: "" }));
  if (action === "remove-row" && rows.length > 1) rows.pop();
  if (action === "remove-col" && colCount > 1) rows.forEach((row) => row.pop());
  state.designer.selectedCell = { region, tableIndex: region === "body_custom" ? state.designer.selectedBodyCustomTable : undefined, row: 0, col: 0 };
  renderDesigner();
}

function addBodyCustomTable() {
  syncDesignerFromInputs();
  const tables = state.designerTemplate.body.custom_tables;
  tables.push({
    title: `自定义表格 ${tables.length + 1}`,
    rows: [
      [{ type: "static", value: "名称" }, { type: "static", value: "值" }],
      [{ type: "static", value: "" }, { type: "static", value: "" }],
    ],
  });
  state.designer.selectedBodyCustomTable = tables.length - 1;
  state.designer.selectedCell = { region: "body_custom", tableIndex: state.designer.selectedBodyCustomTable, row: 0, col: 0 };
  renderDesigner();
}

function removeBodyCustomTable() {
  const tables = state.designerTemplate.body.custom_tables;
  if (!tables.length) return;
  tables.splice(state.designer.selectedBodyCustomTable, 1);
  state.designer.selectedBodyCustomTable = Math.max(0, state.designer.selectedBodyCustomTable - 1);
  state.designer.selectedCell = tables.length
    ? { region: "body_custom", tableIndex: state.designer.selectedBodyCustomTable, row: 0, col: 0 }
    : { region: "header", row: 0, col: 0 };
  renderDesigner();
}

function renameBodyCustomTable(value) {
  const table = selectedBodyCustomTable();
  if (!table) return;
  table.title = value;
  syncJsonEditor();
  renderBodyCustomTables();
}

async function loadHealth() {
  try {
    state.health = await api("/api/health");
    $("#health").textContent = `服务正常\n${state.health.time}`;
    $("#dbPath").value = state.health.demo_db;
    if (state.health.field_opcua) {
      $("#opcServer").value = state.health.field_opcua.server_url;
      $("#opcRoot").value = state.health.field_opcua.root_node;
    }
    if (state.health.field_mysql) {
      $("#dbHost").value = state.health.field_mysql.host;
      $("#dbPort").value = state.health.field_mysql.port;
      $("#dbUser").value = state.health.field_mysql.username;
      $("#dbName").value = state.health.field_mysql.database;
    }
  } catch (error) {
    $("#health").textContent = `服务异常：${error.message}`;
  }
}

async function loadTemplates() {
  state.templates = await api("/api/report-templates");
  const fieldTemplate = state.templates.find((item) => item.name.includes("现场 MySQL"));
  if (!state.selectedTemplateId && fieldTemplate) {
    state.selectedTemplateId = fieldTemplate.id;
  } else if (!state.selectedTemplateId && state.templates.length) {
    state.selectedTemplateId = state.templates[0].id;
  }
  renderTemplateList();
  if (state.selectedTemplateId) selectTemplate(state.selectedTemplateId);
}

function renderOpcBrowser() {
  const keyword = ($("#opcSearch")?.value || "").trim().toLowerCase();
  const pointNodeIds = new Set(state.opcuaBrowser.points.map((point) => point.config.node_id));
  const nodes = visibleOpcNodes().filter((node) => {
    if (!keyword) return true;
    return [node.node_id, node.display_name, node.browse_name, String(node.value ?? "")]
      .join(" ")
      .toLowerCase()
      .includes(keyword);
  });
  $("#opcBrowseList").innerHTML = nodes.length
    ? nodes
        .map((node) => {
          const added = pointNodeIds.has(node.node_id);
          const hasChildren = Boolean(node.has_children);
          const expanded = Boolean(state.opcuaBrowser.expanded[node.node_id]);
          return `
            <div class="opc-tree-node ${state.opcuaBrowser.selectedNodeId === node.node_id ? "selected" : ""}" data-opc-select="${escapeHtml(node.node_id)}" style="margin-left:${Math.min(Number(node.depth || 0) * 18, 72)}px">
              <button class="secondary tree-expander" data-opc-expand="${escapeHtml(node.node_id)}" ${hasChildren ? "" : "disabled"}>${hasChildren ? (expanded ? "−" : "+") : ""}</button>
              <div class="tree-main">
                <div class="opc-node-title">${escapeHtml(node.display_name || node.browse_name || node.node_id)}</div>
                <div class="opc-node-meta">${escapeHtml(node.node_id)}</div>
                ${node.value !== undefined && node.value !== null ? `<div class="opc-node-value">值：${escapeHtml(node.value)}</div>` : ""}
                ${added ? `<div class="opc-node-value">已添加到点位库</div>` : ""}
              </div>
              <input class="tree-inline-input" data-opc-inline-alias="${escapeHtml(node.node_id)}" value="${escapeHtml(node.display_name || node.browse_name || node.node_id)}" ${added ? "disabled" : ""}>
              <div class="opc-point-actions">
                <button class="secondary" data-opc-read-node="${escapeHtml(node.node_id)}">读取</button>
                <button data-opc-add-inline="${escapeHtml(node.node_id)}" ${added ? "disabled" : ""}>${added ? "已添加" : "添加"}</button>
              </div>
            </div>`;
        })
        .join("")
    : `<div class="empty-note">暂无浏览结果，点击“浏览节点”。</div>`;

  $("#opcPointList").innerHTML = state.opcuaBrowser.points.length
    ? state.opcuaBrowser.points
        .map((point) => `
          <div class="opc-point">
            <input class="opc-point-title" data-opc-alias="${point.id}" value="${escapeHtml(point.config.alias || point.name)}">
            <div class="opc-point-meta">${escapeHtml(point.config.node_id)}</div>
            <div class="opc-point-actions">
              <button class="secondary" data-opc-read-point="${point.id}">读取</button>
              <button class="secondary" data-opc-copy="${escapeHtml(point.config.node_id)}">填入模板节点</button>
              <button class="secondary" data-opc-save="${point.id}">保存</button>
              <button class="danger" data-opc-delete="${point.id}">删除</button>
            </div>
          </div>`)
        .join("")
    : `<div class="empty-note">还没有添加数据点。</div>`;
}

function visibleOpcNodes() {
  const roots = state.opcuaBrowser.nodes || [];
  const result = [];
  const walk = (items, depth) => {
    items.forEach((item) => {
      const node = { ...item, depth };
      result.push(node);
      if (state.opcuaBrowser.expanded[item.node_id]) {
        walk(state.opcuaBrowser.childrenByNode[item.node_id] || [], depth + 1);
      }
    });
  };
  walk(roots, 0);
  return result;
}

async function loadOpcPoints() {
  try {
    state.opcuaBrowser.points = await api("/api/opcua/points");
    state.designer.opcuaNodes = state.opcuaBrowser.points.map((point) => ({
      node_id: point.config.node_id,
      display_name: point.config.alias || point.config.display_name || point.name,
      browse_name: point.config.browse_name || point.config.alias || point.name,
    }));
    renderOpcBrowser();
    renderDesigner();
  } catch (error) {
    $("#opcResult").textContent = `读取已添加点位失败：${error.message}`;
  }
}

async function generateSelected() {
  if (!state.selectedTemplateId) return;
  setStatus("#generateStatus", "正在生成...");
  try {
    const report = await api("/api/reports/generate", {
      method: "POST",
      body: JSON.stringify({ template_id: state.selectedTemplateId, persist_run: true }),
    });
    renderReport(report);
    setStatus("#generateStatus", "生成成功");
  } catch (error) {
    setStatus("#generateStatus", `生成失败：${error.message}`, true);
  }
}

function renderStartupResult(result) {
  const box = $("#startupResult");
  const lines = [
    `一键启动：${result.ok ? "通过" : "有异常"}`,
    `时间：${result.time}`,
    "",
    ...(result.steps || []).map((step) => {
      const detail = typeof step.detail === "string" ? step.detail : JSON.stringify(step.detail, null, 2);
      return `${step.ok ? "✓" : "×"} ${step.name}\n${detail}`;
    }),
  ];
  box.textContent = lines.join("\n\n");
  box.classList.add("active");
}

async function oneClickStart() {
  setStatus("#generateStatus", "正在执行一键启动检查...");
  try {
    const result = await api("/api/startup/one-click", {
      method: "POST",
      body: "{}",
    });
    renderStartupResult(result);
    if (result.template_id) {
      state.selectedTemplateId = result.template_id;
      await loadTemplates();
    }
    if (result.report) renderReport(result.report);
    setStatus("#generateStatus", result.ok ? "一键启动完成，现场链路正常" : "一键启动完成，但存在异常，请查看诊断结果", !result.ok);
  } catch (error) {
    setStatus("#generateStatus", `一键启动失败：${error.message}`, true);
  }
}

async function previewEdited() {
  try {
    if (state.designer.activeTab === "advanced" && !applyJsonToDesigner(false)) return;
    syncDesignerFromInputs();
    const payload = parseEditorTemplate();
    const report = await api("/api/reports/generate", {
      method: "POST",
      body: JSON.stringify({ template: payload.config, persist_run: false }),
    });
    renderReport(report);
    $(".nav-btn[data-view='generate']").click();
    setStatus("#generateStatus", "已预览当前编辑内容");
  } catch (error) {
    setStatus("#templateStatus", `预览失败：${error.message}`, true);
  }
}

async function saveTemplate() {
  try {
    if (state.designer.activeTab === "advanced" && !applyJsonToDesigner(false)) return;
    syncDesignerFromInputs();
    const payload = parseEditorTemplate();
    const method = state.selectedTemplateId ? "PUT" : "POST";
    const path = state.selectedTemplateId ? `/api/report-templates/${state.selectedTemplateId}` : "/api/report-templates";
    const saved = await api(path, { method, body: JSON.stringify(payload) });
    state.selectedTemplateId = saved.id;
    await loadTemplates();
    setStatus("#templateStatus", "模板已保存");
  } catch (error) {
    setStatus("#templateStatus", `保存失败：${error.message}`, true);
  }
}

async function copyTemplate() {
  if (!state.selectedTemplateId) return;
  const copied = await api(`/api/report-templates/${state.selectedTemplateId}/copy`, { method: "POST", body: "{}" });
  state.selectedTemplateId = copied.id;
  await loadTemplates();
}

async function deleteTemplate() {
  if (!state.selectedTemplateId) return;
  const template = currentTemplate();
  if (!confirm(`删除模板 "${template.name}"？`)) return;
  await api(`/api/report-templates/${state.selectedTemplateId}`, { method: "DELETE" });
  state.selectedTemplateId = null;
  state.designerTemplate = null;
  await loadTemplates();
}

function newTemplate() {
  const base = state.designerTemplate || state.templates[0]?.config || {};
  state.selectedTemplateId = null;
  state.designerTemplate = ensureTemplateShape(base);
  state.designerTemplate.name = "新建报表模板";
  state.designer.selectedCell = { region: "header", row: 0, col: 0 };
  state.designer.selectedBodyCustomTable = 0;
  renderTemplateList();
  renderDesigner();
}

async function exportReport(format) {
  if (!state.selectedTemplateId) return;
  const response = await fetch(`/api/reports/export/${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template_id: state.selectedTemplateId, persist_run: false }),
  });
  if (!response.ok) {
    setStatus("#generateStatus", `导出失败：${await response.text()}`, true);
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `report.${format === "excel" ? "xlsx" : format}`;
  a.click();
  URL.revokeObjectURL(url);
}

async function browseTemplateOpc() {
  try {
    syncDesignerFromInputs();
    setStatus("#templateStatus", "正在刷新 OPC UA 点位列表...");
    const result = await api("/api/opcua/browse", {
      method: "POST",
      body: JSON.stringify({
        server_url: state.designerTemplate.opcua.server_url,
        root_node: state.designerTemplate.opcua.root_node || "ns=6;i=1000",
        max_depth: 3,
        limit: 180,
        include_values: true,
        node_values: state.designerTemplate.opcua.node_values || {},
      }),
    });
    state.designer.opcuaNodes = result.nodes || [];
    renderDesigner();
    setStatus("#templateStatus", "OPC UA 点位列表已刷新");
  } catch (error) {
    setStatus("#templateStatus", `OPC UA 浏览失败：${error.message}`, true);
  }
}

async function loadTemplateSchema() {
  try {
    syncDesignerFromInputs();
    setStatus("#templateStatus", "正在加载表结构...");
    state.designer.schema = await api("/api/database/schema", {
      method: "POST",
      body: JSON.stringify(templateDbConnection()),
    });
    const firstTable = state.designer.schema.tables?.find((item) => item.table === state.designerTemplate.body.table) || state.designer.schema.tables?.[0];
    if (!state.designerTemplate.body.table && firstTable) state.designerTemplate.body.table = firstTable.table;
    renderDesigner();
    setStatus("#templateStatus", "表结构已加载");
  } catch (error) {
    setStatus("#templateStatus", `表结构加载失败：${error.message}`, true);
  }
}

async function testTemplateDb() {
  try {
    syncDesignerFromInputs();
    const result = await api("/api/database/test", {
      method: "POST",
      body: JSON.stringify(templateDbConnection()),
    });
    setStatus("#templateStatus", result.message || "数据库连接成功");
  } catch (error) {
    setStatus("#templateStatus", `数据库连接失败：${error.message}`, true);
  }
}

function mutateColumn(name, action, value) {
  const columns = state.designerTemplate.body.columns;
  const index = columns.findIndex((column) => column.name === name);
  if (action === "toggle") {
    if (index >= 0) columns.splice(index, 1);
    else columns.push({ name, label: name });
  }
  if (action === "label" && index >= 0) {
    columns[index].label = value || name;
    syncJsonEditor();
    return;
  }
  if (action === "move" && index >= 0) {
    const nextIndex = index + Number(value);
    if (nextIndex >= 0 && nextIndex < columns.length) {
      const [column] = columns.splice(index, 1);
      columns.splice(nextIndex, 0, column);
    }
  }
  renderDesigner();
}

function mutateFilter(index, key, value) {
  const filters = state.designerTemplate.body.filters;
  const filter = filters[index];
  if (!filter) return;
  if (key === "remove") filters.splice(index, 1);
  if (key === "column") filter.column = value;
  if (key === "operator") filter.operator = value;
  if (key === "sourceType") filter.source = value === "opcua" ? { type: "opcua", node_id: state.designer.opcuaNodes[0]?.node_id || "" } : { type: "literal", value: "" };
  if (key === "value") {
    filter.source = { type: "literal", value };
    syncJsonEditor();
    return;
  }
  if (key === "node") {
    filter.source = { type: "opcua", node_id: value };
    syncJsonEditor();
    return;
  }
  renderDesigner();
}

function addFilter() {
  const firstColumn = allKnownColumns()[0] || state.designerTemplate.body.columns[0]?.name || "";
  state.designerTemplate.body.filters.push({ column: firstColumn, operator: "=", source: { type: "literal", value: "" } });
  renderDesigner();
}

async function testOpc() {
  try {
    const result = await api("/api/opcua/test", {
      method: "POST",
      body: JSON.stringify({
        server_url: $("#opcServer").value,
        node_values: JSON.parse($("#opcValues").value || "{}"),
      }),
    });
    $("#opcResult").textContent = pretty(result);
  } catch (error) {
    $("#opcResult").textContent = error.message;
  }
}

async function readOpc() {
  try {
    const nodes = state.opcuaBrowser.points.map((point) => point.config.node_id);
    if (!nodes.length) {
      $("#opcResult").textContent = "请先在 OPC UA 浏览器中添加数据点。";
      return;
    }
    const result = await api("/api/opcua/read", {
      method: "POST",
      body: JSON.stringify({
        server_url: $("#opcServer").value,
        nodes,
        node_values: JSON.parse($("#opcValues").value || "{}"),
      }),
    });
    $("#opcResult").textContent = pretty(result);
  } catch (error) {
    $("#opcResult").textContent = error.message;
  }
}

async function browseOpc() {
  try {
    $("#opcResult").textContent = "正在浏览 OPC UA 节点...";
    const result = await api("/api/opcua/browse", {
      method: "POST",
      body: JSON.stringify({
        server_url: $("#opcServer").value,
        root_node: $("#opcRoot").value,
        max_depth: 0,
        limit: 500,
        include_values: true,
        node_values: JSON.parse($("#opcValues").value || "{}"),
      }),
    });
    state.opcuaBrowser.nodes = result.nodes || [];
    state.opcuaBrowser.childrenByNode = {};
    state.opcuaBrowser.expanded = {};
    if (!state.opcuaBrowser.selectedNodeId && state.opcuaBrowser.nodes.length) {
      state.opcuaBrowser.selectedNodeId = state.opcuaBrowser.nodes[0].node_id;
    }
    $("#opcResult").textContent = `浏览完成，共 ${state.opcuaBrowser.nodes.length} 个节点。`;
    renderOpcBrowser();
  } catch (error) {
    $("#opcResult").textContent = error.message;
  }
}

async function expandOpcNode(nodeId) {
  if (!nodeId) return;
  if (state.opcuaBrowser.expanded[nodeId]) {
    state.opcuaBrowser.expanded[nodeId] = false;
    renderOpcBrowser();
    return;
  }
  if (!state.opcuaBrowser.childrenByNode[nodeId]) {
    try {
      $("#opcResult").textContent = `正在展开 ${nodeId} ...`;
      const result = await api("/api/opcua/browse", {
        method: "POST",
        body: JSON.stringify({
          server_url: $("#opcServer").value,
          root_node: nodeId,
          max_depth: 0,
          limit: 500,
          include_values: true,
          node_values: JSON.parse($("#opcValues").value || "{}"),
        }),
      });
      state.opcuaBrowser.childrenByNode[nodeId] = result.nodes || [];
      $("#opcResult").textContent = `已展开 ${nodeId}，子节点 ${state.opcuaBrowser.childrenByNode[nodeId].length} 个。`;
    } catch (error) {
      $("#opcResult").textContent = `展开失败：${error.message}`;
      return;
    }
  }
  state.opcuaBrowser.expanded[nodeId] = true;
  renderOpcBrowser();
}

async function addOpcPoint(nodeId) {
  const node = state.opcuaBrowser.nodes.find((item) => item.node_id === nodeId) || { node_id: nodeId };
  const flatNode = visibleOpcNodes().find((item) => item.node_id === nodeId) || node;
  const aliasInput = Array.from(document.querySelectorAll("[data-opc-inline-alias]")).find((item) => item.dataset.opcInlineAlias === nodeId);
  const alias = aliasInput?.value || flatNode.display_name || flatNode.browse_name || flatNode.node_id;
  try {
    const point = await api("/api/opcua/points", {
      method: "POST",
      body: JSON.stringify({
        alias: alias.trim() || node.display_name || node.browse_name || node.node_id,
        node_id: flatNode.node_id,
        display_name: flatNode.display_name,
        browse_name: flatNode.browse_name,
        server_url: $("#opcServer").value,
        root_node: $("#opcRoot").value,
        data_type: typeof flatNode.value,
        refresh_seconds: 5,
      }),
    });
    $("#opcResult").textContent = `已添加数据点：${point.name}`;
    await loadOpcPoints();
  } catch (error) {
    $("#opcResult").textContent = `添加失败：${error.message}`;
  }
}

async function readSingleOpcNode(nodeId, target = "#opcResult") {
  try {
    const result = await api("/api/opcua/read", {
      method: "POST",
      body: JSON.stringify({
        server_url: $("#opcServer").value,
        nodes: [nodeId],
        node_values: JSON.parse($("#opcValues").value || "{}"),
      }),
    });
    $(target).textContent = pretty(result);
  } catch (error) {
    $(target).textContent = error.message;
  }
}

async function saveOpcPoint(pointId) {
  const point = state.opcuaBrowser.points.find((item) => Number(item.id) === Number(pointId));
  if (!point) return;
  const alias = document.querySelector(`[data-opc-alias="${pointId}"]`)?.value || point.config.alias || point.name;
  try {
    const saved = await api(`/api/opcua/points/${pointId}`, {
      method: "PUT",
      body: JSON.stringify({
        ...point.config,
        alias,
        server_url: point.config.server_url || $("#opcServer").value,
        root_node: point.config.root_node || $("#opcRoot").value,
      }),
    });
    $("#opcResult").textContent = `已保存数据点：${saved.name}`;
    await loadOpcPoints();
  } catch (error) {
    $("#opcResult").textContent = `保存失败：${error.message}`;
  }
}

async function deleteOpcPoint(pointId) {
  try {
    await api(`/api/opcua/points/${pointId}`, { method: "DELETE" });
    $("#opcResult").textContent = "数据点已删除。";
    await loadOpcPoints();
  } catch (error) {
    $("#opcResult").textContent = `删除失败：${error.message}`;
  }
}

function copyOpcPointToTemplate(nodeId) {
  if (!state.designerTemplate) {
    $("#opcResult").textContent = "请先选择一个模板。";
    return;
  }
  state.designerTemplate.opcua.server_url = $("#opcServer").value;
  state.designerTemplate.opcua.root_node = $("#opcRoot").value;
  if (state.designer.selectedCell && ["header", "footer", "body_custom"].includes(state.designer.selectedCell.region)) {
    setSelectedCell({ type: "opcua", node_id: nodeId });
    $("#opcResult").textContent = "已填入当前选中的模板单元格。";
  } else {
    $("#opcResult").textContent = "已更新模板 OPC UA 连接。请在页眉、页脚或正文自定义表格中选中单元格后再填入节点。";
  }
}

async function testDb() {
  try {
    const result = await api("/api/database/test", {
      method: "POST",
      body: JSON.stringify(currentDbConnection()),
    });
    $("#dbResult").textContent = pretty(result);
  } catch (error) {
    $("#dbResult").textContent = error.message;
  }
}

async function schemaDb() {
  try {
    $("#dbResult").textContent = "正在读取表结构...";
    const result = await api("/api/database/schema", {
      method: "POST",
      body: JSON.stringify(currentDbConnection()),
    });
    $("#dbResult").textContent = pretty(result);
  } catch (error) {
    $("#dbResult").textContent = error.message;
  }
}

async function previewDb() {
  try {
    const result = await api("/api/database/query-preview", {
      method: "POST",
      body: JSON.stringify({
        connection: currentDbConnection(),
        table: $("#dbTable").value,
        columns: $("#dbColumns").value.split(",").map((x) => x.trim()).filter(Boolean),
        order_by: [{ column: "collection_time", direction: "ASC" }],
        limit: 20,
      }),
    });
    $("#dbResult").textContent = pretty(result);
  } catch (error) {
    $("#dbResult").textContent = error.message;
  }
}

async function loadRuns() {
  const rows = await api("/api/report-runs");
  $("#runsTable").innerHTML = `
    <thead><tr><th>ID</th><th>模板</th><th>状态</th><th>消息</th><th>时间</th></tr></thead>
    <tbody>${rows
      .map((row) => `<tr><td>${row.id}</td><td>${row.template_id ?? ""}</td><td>${escapeHtml(row.status)}</td><td>${escapeHtml(row.message)}</td><td>${escapeHtml(row.created_at)}</td></tr>`)
      .join("")}</tbody>
  `;
}

function bindNav() {
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".nav-btn").forEach((item) => item.classList.remove("active"));
      $$(".view").forEach((item) => item.classList.remove("active"));
      btn.classList.add("active");
      $(`#view-${btn.dataset.view}`).classList.add("active");
      if (btn.dataset.view === "runs") loadRuns();
    });
  });
}

function bindSourceTabs() {
  $("#sourceTabs")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-source-tab]");
    if (!btn) return;
    $$("#sourceTabs .tab").forEach((item) => item.classList.toggle("active", item === btn));
    $$(".source-tab").forEach((panel) => panel.classList.toggle("active", panel.id === `source-tab-${btn.dataset.sourceTab}`));
  });
}

function bindDesignerEvents() {
  $("#designerTabs").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-tab]");
    if (!btn) return;
    syncDesignerFromInputs();
    state.designer.activeTab = btn.dataset.tab;
    renderDesigner();
  });

  ["templateName", "pageSize", "pageOrientation", "pageMargin", "bodyTable", "bodyLimit", "bodyOrderColumn", "bodyOrderDirection", "tplOpcServer", "tplOpcRoot", "tplDbType", "tplDbName", "tplDbHost", "tplDbPort", "tplDbUser", "tplDbPassword", "tplDbPath"].forEach((id) => {
    $(`#${id}`)?.addEventListener("input", () => {
      syncDesignerFromInputs();
      if (["bodyTable", "bodyLimit", "bodyOrderColumn", "bodyOrderDirection"].includes(id)) renderBodyDesigner();
    });
    $(`#${id}`)?.addEventListener("change", () => {
      syncDesignerFromInputs();
      renderBodyDesigner();
    });
  });

  document.addEventListener("click", (event) => {
    const cell = event.target.closest(".designer-cell");
    if (cell) {
      state.designer.selectedCell = { region: cell.dataset.region, tableIndex: Number(cell.dataset.tableIndex || 0), row: Number(cell.dataset.row), col: Number(cell.dataset.col) };
      if (cell.dataset.region === "body_custom") {
        state.designer.selectedBodyCustomTable = Number(cell.dataset.tableIndex || 0);
        state.designer.activeTab = "body";
      } else {
        state.designer.activeTab = cell.dataset.region;
      }
      renderDesigner();
      return;
    }
    const tableAction = event.target.closest("[data-table-action]");
    if (tableAction) {
      mutateRegionTable(tableAction.dataset.region, tableAction.dataset.tableAction);
      return;
    }
    const toggle = event.target.closest("[data-column-toggle]");
    if (toggle) {
      mutateColumn(toggle.dataset.columnToggle, "toggle");
      return;
    }
    const move = event.target.closest("[data-column-move]");
    if (move) {
      mutateColumn(move.dataset.columnMove, "move", move.dataset.dir);
      return;
    }
    const removeFilter = event.target.closest("[data-filter-remove]");
    if (removeFilter) {
      mutateFilter(Number(removeFilter.dataset.filterRemove), "remove");
    }
    const expandOpc = event.target.closest("[data-opc-expand]");
    if (expandOpc) {
      expandOpcNode(expandOpc.dataset.opcExpand);
      return;
    }
    const selectOpc = event.target.closest("[data-opc-select]");
    if (selectOpc) {
      state.opcuaBrowser.selectedNodeId = selectOpc.dataset.opcSelect;
      renderOpcBrowser();
    }
    const deleteOpc = event.target.closest("[data-opc-delete]");
    if (deleteOpc) {
      deleteOpcPoint(Number(deleteOpc.dataset.opcDelete));
    }
    const saveOpc = event.target.closest("[data-opc-save]");
    if (saveOpc) {
      saveOpcPoint(Number(saveOpc.dataset.opcSave));
    }
    const readPoint = event.target.closest("[data-opc-read-point]");
    if (readPoint) {
      const point = state.opcuaBrowser.points.find((item) => Number(item.id) === Number(readPoint.dataset.opcReadPoint));
      if (point) readSingleOpcNode(point.config.node_id);
    }
    const copyOpc = event.target.closest("[data-opc-copy]");
    if (copyOpc) {
      copyOpcPointToTemplate(copyOpc.dataset.opcCopy);
    }
    const addInline = event.target.closest("[data-opc-add-inline]");
    if (addInline) {
      addOpcPoint(addInline.dataset.opcAddInline);
    }
    const readNode = event.target.closest("[data-opc-read-node]");
    if (readNode) {
      readSingleOpcNode(readNode.dataset.opcReadNode);
    }
  });

  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-column-label]")) mutateColumn(event.target.dataset.columnLabel, "label", event.target.value);
    if (event.target.matches("[data-filter-value]")) mutateFilter(Number(event.target.dataset.filterValue), "value", event.target.value);
    if (event.target.matches("[data-filter-node-manual]")) mutateFilter(Number(event.target.dataset.filterNodeManual), "node", event.target.value);
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-filter-column]")) mutateFilter(Number(event.target.dataset.filterColumn), "column", event.target.value);
    if (event.target.matches("[data-filter-operator]")) mutateFilter(Number(event.target.dataset.filterOperator), "operator", event.target.value);
    if (event.target.matches("[data-filter-source-type]")) mutateFilter(Number(event.target.dataset.filterSourceType), "sourceType", event.target.value);
    if (event.target.matches("[data-filter-node]")) mutateFilter(Number(event.target.dataset.filterNode), "node", event.target.value);
  });

  $("#bodyCustomTableSelect")?.addEventListener("change", (event) => {
    state.designer.selectedBodyCustomTable = Number(event.target.value || 0);
    state.designer.selectedCell = { region: "body_custom", tableIndex: state.designer.selectedBodyCustomTable, row: 0, col: 0 };
    renderDesigner();
  });
  $("#bodyCustomTableTitle")?.addEventListener("input", (event) => renameBodyCustomTable(event.target.value));
  $("#addBodyCustomTableBtn")?.addEventListener("click", addBodyCustomTable);
  $("#removeBodyCustomTableBtn")?.addEventListener("click", removeBodyCustomTable);
  $("#loadSchemaBtn").addEventListener("click", loadTemplateSchema);
  $("#addFilterBtn").addEventListener("click", addFilter);
  $("#browseTplOpcBtn")?.addEventListener("click", browseTemplateOpc);
  $("#testTplDbBtn")?.addEventListener("click", testTemplateDb);
  $("#applyJsonBtn").addEventListener("click", () => {
    applyJsonToDesigner(true);
  });
}

function bindActions() {
  $("#templateSelect").addEventListener("change", (event) => selectTemplate(Number(event.target.value)));
  $("#oneClickStartBtn").addEventListener("click", oneClickStart);
  $("#generateBtn").addEventListener("click", generateSelected);
  $("#exportHtmlBtn").addEventListener("click", () => exportReport("html"));
  $("#exportPdfBtn").addEventListener("click", () => exportReport("pdf"));
  $("#exportExcelBtn").addEventListener("click", () => exportReport("excel"));
  $("#newTemplateBtn").addEventListener("click", newTemplate);
  $("#copyTemplateBtn").addEventListener("click", copyTemplate);
  $("#saveTemplateBtn").addEventListener("click", saveTemplate);
  $("#deleteTemplateBtn").addEventListener("click", deleteTemplate);
  $("#formatTemplateBtn").addEventListener("click", () => {
    try {
      $("#templateEditor").value = pretty(JSON.parse($("#templateEditor").value));
      setStatus("#templateStatus", "JSON 已格式化");
    } catch (error) {
      setStatus("#templateStatus", `JSON 格式错误：${error.message}`, true);
    }
  });
  $("#previewEditedBtn").addEventListener("click", previewEdited);
  $("#testOpcBtn").addEventListener("click", testOpc);
  $("#readOpcBtn").addEventListener("click", readOpc);
  $("#browseOpcBtn").addEventListener("click", browseOpc);
  $("#opcSearch").addEventListener("input", renderOpcBrowser);
  $("#testDbBtn").addEventListener("click", testDb);
  $("#schemaDbBtn").addEventListener("click", schemaDb);
  $("#previewDbBtn").addEventListener("click", previewDb);
  $("#refreshRunsBtn").addEventListener("click", loadRuns);
  bindDesignerEvents();
}

async function boot() {
  bindNav();
  bindSourceTabs();
  bindActions();
  await loadHealth();
  await loadTemplates();
  await loadOpcPoints();
  await generateSelected();
}

boot().catch((error) => {
  $("#health").textContent = `初始化失败：${error.message}`;
});
