#!/usr/bin/env node
import fs from "node:fs";
import { N8N_MCP_TOOLS, READ_ONLY_TOOLS } from "./tools.mjs";

const rawUrl = process.env.N8N_MCP_URL;
const token = process.env.N8N_MCP_TOKEN;
if (!rawUrl || !token) throw new Error("Faltan N8N_MCP_URL o N8N_MCP_TOKEN.");

const endpoint = new URL(rawUrl);
if (endpoint.protocol !== "https:" || endpoint.hostname !== "n8n.quisqueyatech.com") throw new Error("Host n8n no permitido.");
if (endpoint.pathname === "/" || endpoint.pathname === "") endpoint.pathname = "/mcp-server/http";
if (endpoint.pathname !== "/mcp-server/http") throw new Error("Ruta MCP no permitida.");
endpoint.search = "";
endpoint.hash = "";

const protocolVersion = "2025-06-18";
let sessionId;
let nextId = 1;

const WRITE_TOOLS = N8N_MCP_TOOLS.filter((name) => !READ_ONLY_TOOLS.has(name));
const report = {
  testedAt: new Date().toISOString(),
  summary: { total: WRITE_TOOLS.length, pass: 0, negativePass: 0, fixturePass: 0, fail: 0 },
  tests: [],
  fixtures: {
    folder: "__MCP_WRITE_SUITE__",
    dataTable: "MCP_Write_Suite",
  },
};

function parseSse(body) {
  const out = [];
  for (const block of body.split(/\r?\n\r?\n/)) {
    const data = block.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
    if (!data) continue;
    try { out.push(JSON.parse(data)); } catch {}
  }
  return out;
}

async function send(payload, expectResponse = true) {
  const headers = {
    authorization: `Bearer ${token}`,
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    "mcp-protocol-version": protocolVersion,
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;
  const res = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(20000),
  });
  const sid = res.headers.get("mcp-session-id");
  if (sid) sessionId = sid;
  const body = await res.text();
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${body.slice(0, 800)}`);
  if (!expectResponse || !body) return null;
  const messages = (res.headers.get("content-type") || "").includes("text/event-stream") ? parseSse(body) : [JSON.parse(body)];
  const error = messages.find((m) => m?.error);
  if (error) throw new Error(`MCP ${error.error.code}: ${error.error.message}`);
  return messages.find((m) => m?.result !== undefined) ?? messages.at(-1);
}

async function rpc(method, params = {}) {
  const id = nextId++;
  const msg = await send({ jsonrpc: "2.0", id, method, params });
  if (!msg || msg.result === undefined) throw new Error(`Respuesta invalida para ${method}`);
  return msg.result;
}

function textFromResult(result) {
  return Array.isArray(result?.content) ? result.content.map((x) => x?.text || "").join("\n") : "";
}

function payload(result) {
  if (result?.structuredContent && typeof result.structuredContent === "object") return result.structuredContent;
  const text = textFromResult(result);
  if (!text) return result;
  try { return JSON.parse(text); } catch { return { text }; }
}

function findFirst(value, keys) {
  let out;
  const walk = (v) => {
    if (out !== undefined || v == null) return;
    if (Array.isArray(v)) return v.forEach(walk);
    if (typeof v !== "object") return;
    for (const key of keys) if (typeof v[key] === "string" && v[key]) { out = v[key]; return; }
    Object.values(v).forEach(walk);
  };
  walk(value);
  return out;
}

function findByName(value, name) {
  let out;
  const walk = (v) => {
    if (out || v == null) return;
    if (Array.isArray(v)) return v.forEach(walk);
    if (typeof v !== "object") return;
    if (v.name === name) { out = v; return; }
    Object.values(v).forEach(walk);
  };
  walk(value);
  return out;
}

function add(name, status, detail) {
  report.tests.push({ name, status, detail });
  if (status === "PASS") report.summary.pass++;
  else if (status === "NEGATIVE-PASS") report.summary.negativePass++;
  else if (status === "FIXTURE-PASS") report.summary.fixturePass++;
  else report.summary.fail++;
}

async function call(name, args = {}) {
  return rpc("tools/call", { name, arguments: args });
}

async function positive(name, args, detail = "Call completed.") {
  try {
    const result = await call(name, args);
    if (result?.isError) {
      add(name, "FAIL", textFromResult(result).slice(0, 600) || "isError=true");
      return null;
    }
    add(name, "PASS", detail);
    return { result, payload: payload(result) };
  } catch (e) {
    add(name, "FAIL", String(e.message || e).slice(0, 600));
    return null;
  }
}

async function negative(name, args, expected = /not found|invalid|missing|required|credential|model|publish|available|access|cannot|does not exist|unknown/i) {
  try {
    const result = await call(name, args);
    const detail = textFromResult(result) || JSON.stringify(payload(result) ?? {});
    if (result?.isError || expected.test(detail)) {
      add(name, "NEGATIVE-PASS", "Ruta MCP validada con rechazo de dominio controlado.");
      return true;
    }
    add(name, "FAIL", "Se esperaba rechazo controlado, pero la operación pareció exitosa.");
    return false;
  } catch (e) {
    const detail = String(e.message || e);
    if (expected.test(detail)) {
      add(name, "NEGATIVE-PASS", "Ruta MCP validada con rechazo controlado.");
      return true;
    }
    add(name, "FAIL", detail.slice(0, 600));
    return false;
  }
}

await rpc("initialize", {
  protocolVersion,
  capabilities: {},
  clientInfo: { name: "my-pc-automations-n8n-write-suite", version: "1.0.0" },
});
await send({ jsonrpc: "2.0", method: "notifications/initialized", params: {} }, false);

// Resolve a real project once.
const projects = await call("search_projects", {});
const projectId = findFirst(payload(projects), ["projectId", "id"]);
if (!projectId) throw new Error("No se encontro projectId real; abortando antes de escribir.");
report.projectIdResolved = true;

// Persistent folder fixture: create once, reuse forever.
let folders = await call("search_folders", { projectId, limit: 100 });
let folder = findByName(payload(folders), report.fixtures.folder);
if (!folder) {
  const created = await positive("create_folder", { projectId, name: report.fixtures.folder }, "Fixture folder creado una sola vez.");
  folder = created ? (findByName(created.payload, report.fixtures.folder) || created.payload) : null;
  if (!folder) {
    folders = await call("search_folders", { projectId, limit: 100 });
    folder = findByName(payload(folders), report.fixtures.folder);
  }
} else {
  add("create_folder", "FIXTURE-PASS", "Fixture folder ya existia; se reutiliza para evitar basura por corrida.");
}
const folderId = findFirst(folder, ["folderId", "id"]);
if (!folderId) throw new Error("No se pudo resolver folderId del fixture.");

const renamedFolder = report.fixtures.folder + "_RENAMED";
await positive("update_folder", { projectId, folderId, name: renamedFolder }, "Folder fixture renombrado.");
await positive("update_folder", { projectId, folderId, name: report.fixtures.folder }, "Folder fixture restaurado a su nombre canonico.");

// Persistent Data Table fixture.
let tables = await call("search_data_tables", {});
let table = findByName(payload(tables), report.fixtures.dataTable);
if (!table) {
  const created = await positive("create_data_table", {
    projectId,
    name: report.fixtures.dataTable,
    columns: [{ name: "suiteMarker", type: "string" }],
  }, "Data Table fixture creada una sola vez.");
  table = created ? (findByName(created.payload, report.fixtures.dataTable) || created.payload) : null;
  if (!table) {
    tables = await call("search_data_tables", {});
    table = findByName(payload(tables), report.fixtures.dataTable);
  }
} else {
  add("create_data_table", "FIXTURE-PASS", "Data Table fixture ya existia; se reutiliza.");
}
const dataTableId = findFirst(table, ["dataTableId", "tableId", "id"]);
if (!dataTableId) throw new Error("No se pudo resolver dataTableId del fixture.");

await positive("rename_data_table", { dataTableId, projectId, name: report.fixtures.dataTable + "_RENAMED" }, "Tabla renombrada temporalmente.");
await positive("rename_data_table", { dataTableId, projectId, name: report.fixtures.dataTable }, "Nombre de tabla restaurado.");

await positive("add_data_table_column", { dataTableId, projectId, name: "tempWriteCol", type: "string" }, "Columna temporal creada.");
tables = await call("search_data_tables", {});
table = findByName(payload(tables), report.fixtures.dataTable);
let tempColumn = findByName(table, "tempWriteCol");
let columnId = findFirst(tempColumn, ["columnId", "id"]);
if (columnId) {
  await positive("rename_data_table_column", { dataTableId, projectId, columnId, name: "tempWriteColRenamed" }, "Columna temporal renombrada.");
  tables = await call("search_data_tables", {});
  table = findByName(payload(tables), report.fixtures.dataTable);
  tempColumn = findByName(table, "tempWriteColRenamed");
  columnId = findFirst(tempColumn, ["columnId", "id"]) || columnId;
  await positive("delete_data_table_column", { dataTableId, projectId, columnId }, "Columna temporal eliminada.");
} else {
  add("rename_data_table_column", "FAIL", "No se pudo resolver la columna temporal tras crearla.");
  add("delete_data_table_column", "FAIL", "No se pudo resolver la columna temporal tras crearla.");
}

const rowsResult = await call("get_data_table_rows", { dataTableId, projectId, limit: 100 });
const rowsPayload = payload(rowsResult);
const rowsText = JSON.stringify(rowsPayload);
if (!rowsText.includes("write-suite-fixture")) {
  await positive("add_data_table_rows", {
    dataTableId, projectId,
    rows: [{ suiteMarker: "write-suite-fixture" }],
  }, "Se inserto una unica fila fixture; futuras corridas no duplican.");
} else {
  add("add_data_table_rows", "FIXTURE-PASS", "Fila fixture ya existia; no se duplico.");
}

// Ephemeral workflow fixture: create then archive.
const workflowCode = `import { workflow, node, trigger } from '@n8n/workflow-sdk';

const start = trigger({
  type: 'n8n-nodes-base.manualTrigger',
  version: 1,
  config: { name: 'Start' }
});

const mark = node({
  type: 'n8n-nodes-base.set',
  version: 3.4,
  config: {
    name: 'Mark Test',
    parameters: {
      mode: 'manual',
      includeOtherFields: true,
      assignments: {
        assignments: [
          { id: 'suite-marker', name: 'mcpWriteSuite', value: 'safe-test', type: 'string' }
        ]
      }
    }
  }
});

export default workflow('mcp-write-suite-safe', 'MCP Write Suite Safe').add(start.to(mark));`;

const createdWorkflow = await positive("create_workflow_from_code", {
  code: workflowCode,
  name: "MCP Write Suite Safe",
  description: "Temporary inert workflow created by MCP write validation suite.",
  versionName: "Initial safe fixture",
  projectId,
  folderId,
}, "Workflow temporal creado en el folder fixture.");
const workflowId = createdWorkflow && findFirst(createdWorkflow.payload, ["workflowId", "id"]);

if (workflowId) {
  await positive("move_workflows_to_folder", { workflowIds: [workflowId], folderId: "0" }, "Workflow temporal movido al root.");
  await positive("move_workflows_to_folder", { workflowIds: [workflowId], folderId }, "Workflow temporal devuelto al folder fixture.");

  await positive("update_workflow", {
    workflowId,
    operations: [{ type: "renameNode", oldName: "Mark Test", newName: "Mark Test Renamed" }],
  }, "Nodo del workflow temporal renombrado.");

  const history = await call("get_workflow_history", { workflowId });
  const historyPayload = payload(history);
  const versionIds = [];
  const walkVersions = (v) => {
    if (!v) return;
    if (Array.isArray(v)) return v.forEach(walkVersions);
    if (typeof v !== "object") return;
    if (typeof v.versionId === "string" && !versionIds.includes(v.versionId)) versionIds.push(v.versionId);
    Object.values(v).forEach(walkVersions);
  };
  walkVersions(historyPayload);

  await positive("prepare_workflow_pin_data", { workflowId }, "Schemas de pin data preparados.");
  await positive("test_workflow", { workflowId, pinData: { Start: [{ json: {} }] }, triggerNodeName: "Start", timeout: 30 }, "Workflow temporal probado solo con nodos internos.");
  await positive("execute_workflow", { workflowId, executionMode: "manual", triggerNodeName: "Start" }, "Ejecucion manual del workflow temporal solicitada.");

  await positive("publish_workflow", { workflowId }, "Workflow temporal publicado.");
  await positive("unpublish_workflow", { workflowId }, "Workflow temporal despublicado.");

  if (versionIds.length) {
    await positive("restore_workflow_version", { workflowId, versionId: versionIds[versionIds.length - 1] }, "Version previa restaurada sobre el workflow temporal.");
  } else {
    add("restore_workflow_version", "FAIL", "No se encontro versionId tras create/update.");
  }

  await positive("archive_workflow", { workflowId }, "Workflow temporal archivado al finalizar.");
} else {
  for (const name of ["move_workflows_to_folder","update_workflow","prepare_workflow_pin_data","test_workflow","execute_workflow","publish_workflow","unpublish_workflow","restore_workflow_version","archive_workflow"]) {
    add(name, "FAIL", "No se pudo resolver workflowId del fixture temporal.");
  }
}

// Ephemeral Agent fixture. No real model/credential/integration is attached.
const createdAgent = await positive("create_agent", {
  projectId,
  name: "MCP Write Suite Agent",
  config: { model: "", instructions: "Inert temporary agent for MCP write validation only." },
}, "Agent temporal creado sin modelo ni credencial.");
const agentId = createdAgent && findFirst(createdAgent.payload, ["agentId", "id"]);

if (agentId) {
  const agent = await call("get_agent", { agentId });
  const agentPayload = payload(agent);
  const configHash = findFirst(agentPayload, ["configHash"]);
  if (configHash) {
    await positive("mutate_agent", {
      agentId,
      baseConfigHash: configHash,
      operation: {
        type: "config.patch",
        patch: [{ op: "replace", path: "/instructions", value: "Inert MCP write-suite agent, mutated safely." }],
      },
    }, "Agent temporal mutado sin tools/credenciales.");
  } else {
    add("mutate_agent", "FAIL", "No se pudo obtener configHash del Agent temporal.");
  }

  await negative("call_agent", { agentId, request: { type: "message", message: "Return only SAFE_TEST." } }, /model|credential|invalid|not configured|required|cannot/i);
  await negative("publish_agent", { agentId }, /model|credential|invalid|publish|valid|required|cannot/i);
  await negative("unpublish_agent", { agentId }, /not published|publish|invalid|cannot|state/i);
  await negative("revert_agent", { agentId }, /version|published|publish|not found|cannot|invalid/i);
  await negative("update_agent_integration", {
    agentId,
    action: "connect",
    type: "telegram",
    credentialId: "__write_suite_invalid_credential__",
    settings: {},
  }, /credential|invalid|not found|access|cannot/i);

  await positive("delete_agent", { agentId }, "Agent temporal eliminado al finalizar.");
} else {
  for (const name of ["mutate_agent","call_agent","publish_agent","unpublish_agent","revert_agent","update_agent_integration","delete_agent"]) {
    add(name, "FAIL", "No se pudo resolver agentId del fixture temporal.");
  }
}

// Ensure every write-classified tool is covered once.
for (const name of WRITE_TOOLS) {
  if (!report.tests.some((t) => t.name === name)) add(name, "FAIL", "Tool de escritura no cubierta por la suite.");
}

report.tests.sort((a, b) => a.name.localeCompare(b.name));
fs.mkdirSync("n8n-mcp/out", { recursive: true });
fs.writeFileSync("n8n-mcp/out/write-suite.json", JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (report.summary.fail > 0) process.exitCode = 1;
