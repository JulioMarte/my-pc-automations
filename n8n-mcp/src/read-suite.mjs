#!/usr/bin/env node
import fs from "node:fs";
import { N8N_MCP_TOOLS, READ_ONLY_TOOLS } from "./tools.mjs";

const rawUrl = process.env.N8N_MCP_URL;
const token = process.env.N8N_MCP_TOKEN;
if (!rawUrl || !token) throw new Error("Faltan N8N_MCP_URL o N8N_MCP_TOKEN.");

const endpoint = new URL(rawUrl);
if (endpoint.protocol !== "https:" || endpoint.hostname !== "n8n.quisqueyatech.com") {
  throw new Error("Host n8n no permitido.");
}
if (endpoint.pathname === "/" || endpoint.pathname === "") endpoint.pathname = "/mcp-server/http";
if (endpoint.pathname !== "/mcp-server/http") throw new Error("Ruta MCP no permitida.");
endpoint.search = "";
endpoint.hash = "";

const protocolVersion = "2025-06-18";
let sessionId;
let nextId = 1;

function parseSse(body) {
  const out = [];
  for (const block of body.split(/\r?\n\r?\n/)) {
    const data = block.split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("\n");
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
  const res = await fetch(endpoint, { method: "POST", headers, body: JSON.stringify(payload), signal: AbortSignal.timeout(15000) });
  const sid = res.headers.get("mcp-session-id");
  if (sid) sessionId = sid;
  const body = await res.text();
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${body.slice(0, 500)}`);
  if (!expectResponse || !body) return null;
  const messages = (res.headers.get("content-type") || "").includes("text/event-stream")
    ? parseSse(body)
    : [JSON.parse(body)];
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

async function initialize() {
  const result = await rpc("initialize", {
    protocolVersion,
    capabilities: {},
    clientInfo: { name: "my-pc-automations-n8n-read-suite", version: "1.0.0" },
  });
  await send({ jsonrpc: "2.0", method: "notifications/initialized", params: {} }, false);
  return result;
}

async function listTools() {
  const all = [];
  let cursor;
  do {
    const page = await rpc("tools/list", cursor ? { cursor } : {});
    all.push(...(page.tools || []));
    cursor = page.nextCursor;
  } while (cursor);
  return all;
}

function textFromToolResult(result) {
  if (!result || typeof result !== "object") return "";
  if (Array.isArray(result.content)) {
    return result.content.map((c) => c?.text || "").join("\n");
  }
  return "";
}

function parsedToolPayload(result) {
  if (result?.structuredContent && typeof result.structuredContent === "object") {
    return result.structuredContent;
  }
  const text = textFromToolResult(result);
  if (!text) return result;
  try { return JSON.parse(text); } catch { return { text }; }
}

function isToolError(result) {
  return Boolean(result?.isError);
}

function walk(value, visitor, path = []) {
  if (value == null) return;
  visitor(value, path);
  if (Array.isArray(value)) value.forEach((v, i) => walk(v, visitor, [...path, i]));
  else if (typeof value === "object") {
    for (const [k, v] of Object.entries(value)) walk(v, visitor, [...path, k]);
  }
}

function findFirstByKeys(value, keys) {
  let found;
  walk(value, (v) => {
    if (found !== undefined || !v || typeof v !== "object" || Array.isArray(v)) return;
    for (const key of keys) {
      if (typeof v[key] === "string" && v[key]) {
        found = v[key];
        return;
      }
    }
  });
  return found;
}

function findObjectWithKey(value, key) {
  let found;
  walk(value, (v) => {
    if (found || !v || typeof v !== "object" || Array.isArray(v)) return;
    if (Object.hasOwn(v, key)) found = v;
  });
  return found;
}

function minimalFromSchema(schema) {
  if (!schema || schema.type !== "object") return {};
  const out = {};
  for (const key of schema.required || []) {
    const p = schema.properties?.[key] || {};
    if (p.default !== undefined) out[key] = p.default;
    else if (Array.isArray(p.enum) && p.enum.length) out[key] = p.enum[0];
    else if (p.type === "boolean") out[key] = false;
    else if (p.type === "integer" || p.type === "number") out[key] = 1;
    else if (p.type === "array") out[key] = [];
    else if (p.type === "object") out[key] = {};
    else out[key] = "test";
  }
  return out;
}

const init = await initialize();
const discovered = await listTools();
const toolMap = new Map(discovered.map((t) => [t.name, t]));
const readonlyNames = N8N_MCP_TOOLS.filter((n) => READ_ONLY_TOOLS.has(n));

const report = {
  serverInfo: init.serverInfo || null,
  protocolVersion: init.protocolVersion || null,
  testedAt: new Date().toISOString(),
  summary: { total: readonlyNames.length, pass: 0, negativePass: 0, skipContext: 0, fail: 0 },
  tests: [],
};

async function call(name, args = {}) {
  return rpc("tools/call", { name, arguments: args });
}

function add(name, status, detail, args = undefined) {
  report.tests.push({ name, status, detail, ...(args ? { args } : {}) });
  if (status === "PASS") report.summary.pass++;
  else if (status === "NEGATIVE-PASS") report.summary.negativePass++;
  else if (status === "SKIP-CONTEXT") report.summary.skipContext++;
  else report.summary.fail++;
}

async function negativeTest(name, args, expected = /not found|does not exist|access|credential|invalid|unknown/i) {
  try {
    const result = await call(name, args);
    const detail = textFromToolResult(result) || JSON.stringify(parsedToolPayload(result) ?? {});
    if (isToolError(result) || expected.test(detail)) {
      add(name, "NEGATIVE-PASS", "Schema/transport/auth route validated; controlled domain rejection received.", args);
      return { ok: true, negative: true, result };
    }
    add(name, "FAIL", "Expected a controlled domain rejection but call unexpectedly succeeded.", args);
    return { ok: false, result };
  } catch (e) {
    const detail = String(e.message || e);
    if (expected.test(detail)) {
      add(name, "NEGATIVE-PASS", "Transport/schema route validated; controlled rejection received.", args);
      return { ok: true, negative: true };
    }
    add(name, "FAIL", detail.slice(0, 500), args);
    return { ok: false };
  }
}

async function test(name, args, { allowToolError = false } = {}) {
  try {
    const result = await call(name, args);
    if (isToolError(result) && !allowToolError) {
      add(name, "FAIL", textFromToolResult(result).slice(0, 500) || "Tool returned isError=true", args);
      return { ok: false, result };
    }
    add(name, "PASS", isToolError(result) ? "Transport/schema OK; tool returned expected domain error." : "Call completed.", args);
    return { ok: true, result, payload: parsedToolPayload(result) };
  } catch (e) {
    add(name, "FAIL", String(e.message || e).slice(0, 500), args);
    return { ok: false };
  }
}

const roots = {};

// Safe discovery/list calls first.
roots.workflows = await test("search_workflows", { limit: 20, sortBy: "updatedAt:desc" });
roots.executions = await test("search_workflow_executions", { limit: 20 });
roots.credentials = await test("list_credentials", minimalFromSchema(toolMap.get("list_credentials")?.inputSchema));
roots.gateway = await test("list_n8n_gateway_services", minimalFromSchema(toolMap.get("list_n8n_gateway_services")?.inputSchema));
roots.tags = await test("list_workflow_tags", minimalFromSchema(toolMap.get("list_workflow_tags")?.inputSchema));
roots.tables = await test("search_data_tables", minimalFromSchema(toolMap.get("search_data_tables")?.inputSchema));
roots.nodes = await test("search_nodes", { queries: ["http request"], usage: "workflow" });
roots.projects = await test("search_projects", minimalFromSchema(toolMap.get("search_projects")?.inputSchema));
const projectId = findFirstByKeys(roots.projects?.payload, ["projectId", "id"]);
if (projectId) roots.folders = await test("search_folders", { projectId, limit: 20 });
else { add("search_folders", "SKIP-CONTEXT", "No se encontro un projectId real accesible."); roots.folders = null; }
roots.agents = await test("search_agents", minimalFromSchema(toolMap.get("search_agents")?.inputSchema));
roots.sdk = await test("get_workflow_sdk_reference", minimalFromSchema(toolMap.get("get_workflow_sdk_reference")?.inputSchema));
roots.agentBuilder = await test("get_agent_builder_reference", minimalFromSchema(toolMap.get("get_agent_builder_reference")?.inputSchema));

// Best practices: choose a real enum/default from live schema when present.
{
  const schema = toolMap.get("get_workflow_best_practices")?.inputSchema;
  const args = minimalFromSchema(schema);
  const technique = schema?.properties?.technique;
  if (technique?.enum?.length) args.technique = technique.enum[0];
  await test("get_workflow_best_practices", args);
}

// Workflow-specific reads.
const workflowPayload = roots.workflows?.payload;
const workflowId = findFirstByKeys(workflowPayload, ["workflowId", "id"]);
if (workflowId) {
  const details = await test("get_workflow_details", { workflowId });
  const history = await test("get_workflow_history", { workflowId });
  const historyPayload = history?.payload;
  const versionId = findFirstByKeys(historyPayload, ["versionId", "id"]);
  if (versionId) {
    await test("get_workflow_version", { workflowId, versionId });
    const versionIds = [];
    walk(historyPayload, (v) => {
      if (!v || typeof v !== "object" || Array.isArray(v)) return;
      for (const k of ["versionId", "id"]) {
        if (typeof v[k] === "string" && v[k] && !versionIds.includes(v[k])) versionIds.push(v[k]);
      }
    });
    if (versionIds.length >= 2) {
      const schema = toolMap.get("get_workflow_versions_diff")?.inputSchema;
      const args = minimalFromSchema(schema);
      const props = schema?.properties || {};
      for (const key of Object.keys(props)) {
        if (/workflow/i.test(key)) args[key] = workflowId;
        else if (/from|base|old/i.test(key)) args[key] = versionIds[1];
        else if (/to|target|new/i.test(key)) args[key] = versionIds[0];
      }
      await test("get_workflow_versions_diff", args);
    } else add("get_workflow_versions_diff", "SKIP-CONTEXT", "Se requiere al menos dos versiones reales del mismo workflow.");
  } else {
    add("get_workflow_version", "SKIP-CONTEXT", "No se encontro versionId real en el historial.");
    add("get_workflow_versions_diff", "SKIP-CONTEXT", "No hay suficientes versiones reales para comparar.");
  }
  if (!details?.ok) {}
} else {
  for (const name of ["get_workflow_details","get_workflow_history","get_workflow_version","get_workflow_versions_diff"]) {
    add(name, "SKIP-CONTEXT", "No se encontro un workflow real accesible para usar como contexto.");
  }
}

// Execution detail.
const executionPayload = roots.executions?.payload;
const executionId = findFirstByKeys(executionPayload, ["executionId", "id"]);
const executionWorkflowId = findFirstByKeys(executionPayload, ["workflowId"]);
if (executionId && executionWorkflowId) {
  await test("get_workflow_execution", { workflowId: executionWorkflowId, executionId, includeData: false });
} else {
  add("get_workflow_execution", "SKIP-CONTEXT", "No se encontro una ejecucion real con workflowId + executionId.");
}

// Data table rows.
const tablePayload = roots.tables?.payload;
const tableId = findFirstByKeys(tablePayload, ["dataTableId", "tableId", "id"]);
const tableProjectId = findFirstByKeys(tablePayload, ["projectId"]) || projectId;
if (tableId && tableProjectId) {
  const schema = toolMap.get("get_data_table_rows")?.inputSchema;
  const args = minimalFromSchema(schema);
  for (const key of Object.keys(schema?.properties || {})) {
    if (/table.*id|dataTableId/i.test(key)) args[key] = tableId;
    else if (/project.*id/i.test(key)) args[key] = tableProjectId;
  }
  await test("get_data_table_rows", args);
} else add("get_data_table_rows", "SKIP-CONTEXT", "No se encontro una Data Table real con projectId accesible.");

// Node metadata reads.
const nodePayload = roots.nodes?.payload;
const nodeText = textFromToolResult(roots.nodes?.result);
const nodeId = findFirstByKeys(nodePayload, ["nodeId", "id"]) ||
  nodeText.match(/-\s+((?:@[^\s]+\/)?n8n-[^\s]+|n8n-nodes-base\.[A-Za-z0-9_]+)/)?.[1];
if (nodeId) {
  await test("get_node_types", { nodeIds: [{ nodeId }] });
  await negativeTest("explore_node_resources", {
    nodeType: nodeId,
    version: Number(nodeText.match(/Version:\s*([0-9.]+)/)?.[1] || 1),
    methodName: "__read_suite_nonexistent_method__",
    methodType: "loadOptions",
    credentialType: "__read_suite_invalid__",
    credentialId: "__read_suite_invalid__"
  });
  const versionMatch = nodeText.match(/Version:\s*([0-9.]+)/);
  const typeVersion = versionMatch ? Number(versionMatch[1]) : 1;
  await test("validate_node_config", { nodes: [{ name: "ReadSuiteNode", type: nodeId, typeVersion, parameters: {} }] }, { allowToolError: true });
} else {
  for (const name of ["get_node_types","explore_node_resources","validate_node_config"]) add(name, "SKIP-CONTEXT", "No se obtuvo un nodeId real.");
}

// validate_workflow can be tested against an existing accessible workflow where schema allows workflowId.
{
  const schema = toolMap.get("validate_workflow")?.inputSchema;
  const args = minimalFromSchema(schema);
  let can = true;
  for (const key of schema?.required || []) {
    if (/workflow.*id/i.test(key) && workflowId) args[key] = workflowId;
    else if (/workflow.*id/i.test(key) && !workflowId) can = false;
  }
  if (can) await test("validate_workflow", args, { allowToolError: true });
  else add("validate_workflow", "SKIP-CONTEXT", "La validacion requiere un workflow real accesible.");
}

// Agent-specific reads.
const agentPayload = roots.agents?.payload;
const agentId = findFirstByKeys(agentPayload, ["agentId", "id"]);
if (agentId) {
  await test("get_agent", { agentId });
  await test("validate_agent", { agentId }, { allowToolError: true });
  const versionsSchema = toolMap.get("list_agent_versions")?.inputSchema;
  const versionsArgs = minimalFromSchema(versionsSchema);
  for (const key of Object.keys(versionsSchema?.properties || {})) if (/agent.*id/i.test(key)) versionsArgs[key] = agentId;
  await test("list_agent_versions", versionsArgs);

  const assetsSchema = toolMap.get("discover_agent_assets")?.inputSchema;
  const assetsArgs = minimalFromSchema(assetsSchema);
  for (const key of Object.keys(assetsSchema?.properties || {})) if (/agent.*id/i.test(key)) assetsArgs[key] = agentId;
  await test("discover_agent_assets", assetsArgs);

  const verifySchema = toolMap.get("verify_agent_mcp_server")?.inputSchema;
  const verifyArgs = minimalFromSchema(verifySchema);
  let verifyCan = true;
  for (const key of verifySchema?.required || []) {
    if (/agent.*id/i.test(key)) verifyArgs[key] = agentId;
    else if (/url|server/i.test(key)) verifyCan = false;
  }
  if (verifyCan) await test("verify_agent_mcp_server", verifyArgs, { allowToolError: true });
  else add("verify_agent_mcp_server", "SKIP-CONTEXT", "La tool requiere contexto MCP externo adicional; no se invento un endpoint.");
} else {
  const missingAgentId = "__read_suite_missing_agent__";
  await negativeTest("get_agent", { agentId: missingAgentId });
  await negativeTest("validate_agent", { agentId: missingAgentId });
  await negativeTest("list_agent_versions", { agentId: missingAgentId });
  await negativeTest("discover_agent_assets", { agentId: missingAgentId });
}

if (projectId) {
  await test("verify_agent_mcp_server", {
    projectId,
    name: "self_read_test",
    url: endpoint.toString(),
    transport: "streamableHttp",
    authentication: "none",
    connectionTimeoutMs: 5000
  }, { allowToolError: true });
}

// Ensure every current read-only tool is accounted for exactly once.
for (const name of readonlyNames) {
  if (!report.tests.some((t) => t.name === name)) {
    add(name, "FAIL", "Tool de lectura no cubierta por la suite.");
  }
}

report.tests.sort((a,b) => a.name.localeCompare(b.name));
fs.mkdirSync("n8n-mcp/out", { recursive: true });
fs.writeFileSync("n8n-mcp/out/read-suite.json", JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));

if (report.summary.fail > 0) process.exitCode = 1;
