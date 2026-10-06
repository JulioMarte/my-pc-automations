#!/usr/bin/env node
import fs from "node:fs";
import { N8N_MCP_TOOLS, READ_ONLY_TOOLS } from "./tools.mjs";

const rawUrl = process.env.N8N_MCP_URL;
const token = process.env.N8N_MCP_TOKEN;
const requestPath = process.env.MCP_REQUEST_FILE || "n8n-mcp/request.json";
const repoVisibility = (process.env.REPO_VISIBILITY || "unknown").toLowerCase();

if (!rawUrl || !token) throw new Error("Faltan N8N_MCP_URL o N8N_MCP_TOKEN.");
if (!fs.existsSync(requestPath)) throw new Error(`No existe ${requestPath}`);
const requestStat = fs.statSync(requestPath);
if (requestStat.size > 65536) throw new Error("Request file demasiado grande; maximo 64 KiB.");

const cfg = JSON.parse(fs.readFileSync(requestPath, "utf8"));
if (!N8N_MCP_TOOLS.includes(cfg.tool)) throw new Error(`Tool no permitida: ${cfg.tool}`);

const HIGH_RISK_TOOLS = new Set([
  "execute_workflow",
  "test_workflow",
  "publish_workflow",
  "unpublish_workflow",
  "archive_workflow",
  "restore_workflow_version",
  "delete_data_table_column",
  "call_agent",
  "publish_agent",
  "unpublish_agent",
  "revert_agent",
  "delete_agent",
  "update_agent_integration"
]);

const TARGET_ASSERTION_TOOLS = new Set([
  "execute_workflow",
  "test_workflow",
  "publish_workflow",
  "unpublish_workflow",
  "archive_workflow",
  "update_workflow",
  "restore_workflow_version",
  "rename_data_table",
  "add_data_table_column",
  "delete_data_table_column",
  "rename_data_table_column",
  "add_data_table_rows",
  "update_folder",
  "mutate_agent",
  "call_agent",
  "publish_agent",
  "unpublish_agent",
  "revert_agent",
  "delete_agent",
  "update_agent_integration"
]);

const endpoint = new URL(rawUrl);
if (endpoint.protocol !== "https:" || endpoint.hostname !== "n8n.quisqueyatech.com") {
  throw new Error("Host n8n no permitido.");
}
if (endpoint.pathname === "/" || endpoint.pathname === "") endpoint.pathname = "/mcp-server/http";
if (endpoint.pathname !== "/mcp-server/http") throw new Error("Ruta MCP no permitida.");
endpoint.search = "";
endpoint.hash = "";

const forcedReadOnly = (process.env.MCP_READ_ONLY || "").toLowerCase() === "true";
const forcedWriteOnly = (process.env.MCP_WRITE_ONLY || "").toLowerCase() === "true";
if (forcedReadOnly && forcedWriteOnly) {
  throw new Error("MCP_READ_ONLY y MCP_WRITE_ONLY no pueden estar activos a la vez.");
}
if (forcedReadOnly && !READ_ONLY_TOOLS.has(cfg.tool)) {
  throw new Error(`MCP_READ_ONLY bloquea la tool no-read: ${cfg.tool}`);
}
if (forcedWriteOnly && READ_ONLY_TOOLS.has(cfg.tool)) {
  throw new Error(`MCP_WRITE_ONLY bloquea la tool read: ${cfg.tool}`);
}
if (!READ_ONLY_TOOLS.has(cfg.tool) && cfg.confirmWrite !== true) {
  throw new Error(`${cfg.tool} requiere confirmWrite=true`);
}
if (HIGH_RISK_TOOLS.has(cfg.tool) && cfg.confirmRisk !== true) {
  throw new Error(`${cfg.tool} requiere confirmRisk=true por su impacto potencial`);
}
if (forcedWriteOnly && TARGET_ASSERTION_TOOLS.has(cfg.tool) && typeof cfg.expectedTargetName !== "string") {
  throw new Error(`${cfg.tool} requiere expectedTargetName para proteger contra IDs equivocados`);
}
if (cfg.outputMode === "full" && repoVisibility === "public") {
  throw new Error("outputMode=full no se permite en un repo publico.");
}

let sessionId;
let nextId = 1;
const protocolVersion = "2025-06-18";

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

  if (!res.ok) throw new Error(`MCP HTTP ${res.status}: ${body.slice(0, 800)}`);
  if (!expectResponse || !body) return null;

  const messages = (res.headers.get("content-type") || "").includes("text/event-stream")
    ? parseSse(body)
    : [JSON.parse(body)];

  const error = messages.find((m) => m?.error);
  if (error) throw new Error(`MCP ${error.error.code}: ${error.error.message}`);
  return messages.find((m) => m?.result !== undefined) ?? messages.at(-1);
}

async function request(method, params) {
  const id = nextId++;
  const msg = await send({ jsonrpc: "2.0", id, method, params });
  if (!msg || msg.result === undefined) throw new Error(`Respuesta invalida para ${method}`);
  return msg.result;
}

function validateValue(schema, value, path = "$") {
  if (!schema || typeof schema !== "object") return [];

  if (schema.allOf) {
    return schema.allOf.flatMap((s) => validateValue(s, value, path));
  }
  if (schema.anyOf) {
    const branches = schema.anyOf.map((s) => validateValue(s, value, path));
    if (branches.some((errors) => errors.length === 0)) return [];
    return [`${path} no coincide con ningun anyOf`];
  }
  if (schema.oneOf) {
    const validCount = schema.oneOf.filter((s) => validateValue(s, value, path).length === 0).length;
    return validCount === 1 ? [] : [`${path} debe coincidir exactamente con un oneOf`];
  }

  const errors = [];
  if (schema.const !== undefined && value !== schema.const) errors.push(`${path} debe ser ${JSON.stringify(schema.const)}`);
  if (Array.isArray(schema.enum) && !schema.enum.some((x) => JSON.stringify(x) === JSON.stringify(value))) {
    errors.push(`${path} no pertenece al enum permitido`);
  }

  if (schema.type) {
    const expected = Array.isArray(schema.type) ? schema.type : [schema.type];
    const actual = value === null ? "null" : Array.isArray(value) ? "array" : (Number.isInteger(value) ? "integer" : typeof value);
    const aliases = actual === "integer" ? ["integer", "number"] : [actual];
    if (!expected.some((t) => aliases.includes(t))) return [`${path} esperaba ${expected.join("|")}, recibio ${actual}`];
  }

  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) errors.push(`${path} demasiado corto`);
    if (schema.maxLength !== undefined && value.length > schema.maxLength) errors.push(`${path} demasiado largo`);
    if (schema.pattern && !(new RegExp(schema.pattern).test(value))) errors.push(`${path} no cumple pattern`);
  }

  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${path} menor que minimum`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${path} mayor que maximum`);
    if (schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum) errors.push(`${path} debe ser > exclusiveMinimum`);
    if (schema.exclusiveMaximum !== undefined && value >= schema.exclusiveMaximum) errors.push(`${path} debe ser < exclusiveMaximum`);
  }

  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) errors.push(`${path} tiene pocos items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) errors.push(`${path} tiene demasiados items`);
    if (schema.items) value.forEach((item, i) => errors.push(...validateValue(schema.items, item, `${path}[${i}]`)));
  }

  if (value && typeof value === "object" && !Array.isArray(value)) {
    const properties = schema.properties || {};
    for (const key of schema.required || []) {
      if (!(key in value)) errors.push(`${path} falta campo requerido ${key}`);
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(value)) if (!(key in properties)) errors.push(`${path} campo desconocido ${key}`);
    }
    for (const [key, child] of Object.entries(value)) {
      if (properties[key]) errors.push(...validateValue(properties[key], child, `${path}.${key}`));
      else if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
        errors.push(...validateValue(schema.additionalProperties, child, `${path}.${key}`));
      }
    }
  }

  return errors;
}

function validateArgumentsAgainstSchema(schema, args) {
  return validateValue(schema, args, "$arguments");
}

async function listTools() {
  const all = [];
  let cursor;
  do {
    const page = await request("tools/list", cursor ? { cursor } : {});
    all.push(...(page.tools || []));
    cursor = page.nextCursor;
  } while (cursor);
  return all;
}

function structuredPayload(result) {
  if (result?.structuredContent && typeof result.structuredContent === "object") return result.structuredContent;
  if (Array.isArray(result?.content)) {
    const text = result.content.map((x) => x?.text || "").join("\n");
    if (text) {
      try { return JSON.parse(text); } catch {}
    }
  }
  return result;
}

function findObjectById(value, id) {
  let found = null;
  const walk = (v) => {
    if (found || !v) return;
    if (Array.isArray(v)) return v.forEach(walk);
    if (typeof v !== "object") return;
    if (["id","workflowId","agentId","folderId","dataTableId","tableId"].some((k) => v[k] === id)) {
      found = v;
      return;
    }
    Object.values(v).forEach(walk);
  };
  walk(value);
  return found;
}

function firstName(value) {
  let found = null;
  const walk = (v) => {
    if (found || !v) return;
    if (Array.isArray(v)) return v.forEach(walk);
    if (typeof v !== "object") return;
    if (typeof v.name === "string" && v.name) { found = v.name; return; }
    Object.values(v).forEach(walk);
  };
  walk(value);
  return found;
}

async function resolveTargetName(tool, args) {
  let result;
  let targetId;

  if (args.workflowId) {
    targetId = args.workflowId;
    result = await request("tools/call", { name: "get_workflow_details", arguments: { workflowId: targetId } });
  } else if (args.agentId) {
    targetId = args.agentId;
    result = await request("tools/call", { name: "get_agent", arguments: { agentId: targetId } });
  } else if (args.folderId && args.projectId) {
    targetId = args.folderId;
    result = await request("tools/call", { name: "search_folders", arguments: { projectId: args.projectId, limit: 100 } });
  } else if ((args.dataTableId || args.tableId) && args.projectId) {
    targetId = args.dataTableId || args.tableId;
    result = await request("tools/call", { name: "search_data_tables", arguments: {} });
  } else {
    return null;
  }

  if (result?.isError) throw new Error("No se pudo verificar el recurso objetivo antes de escribir.");
  const body = structuredPayload(result);
  const exact = findObjectById(body, targetId);
  return firstName(exact || body);
}

function publicWriteSummary(result) {
  return {
    isError: Boolean(result?.isError),
    hasStructuredContent: Boolean(result?.structuredContent),
    contentTypes: Array.isArray(result?.content) ? [...new Set(result.content.map((x) => x?.type).filter(Boolean))] : [],
    structuredKeys: result?.structuredContent && typeof result.structuredContent === "object"
      ? Object.keys(result.structuredContent).slice(0, 20)
      : [],
  };
}

function sanitize(value, depth = 0) {
  if (depth > 4) return "[truncated]";
  if (value === null || typeof value !== "object") {
    if (typeof value === "string" && value.length > 1000) return value.slice(0, 1000) + "…";
    return value;
  }
  if (Array.isArray(value)) return value.slice(0, 20).map((x) => sanitize(x, depth + 1));
  const out = {};
  for (const [key, val] of Object.entries(value)) {
    if (/token|secret|password|authorization|cookie/i.test(key)) out[key] = "[redacted]";
    else out[key] = sanitize(val, depth + 1);
  }
  return out;
}

const initialized = await request("initialize", {
  protocolVersion,
  capabilities: {},
  clientInfo: { name: "my-pc-automations-n8n-tool-runner", version: "1.0.0" },
});
await send({ jsonrpc: "2.0", method: "notifications/initialized", params: {} }, false);

const liveTools = await listTools();
const liveTool = liveTools.find((tool) => tool.name === cfg.tool);
if (!liveTool) throw new Error(`Tool no anunciada actualmente por el servidor: ${cfg.tool}`);

const argumentErrors = validateArgumentsAgainstSchema(liveTool.inputSchema, cfg.arguments || {});
if (argumentErrors.length) {
  throw new Error(`Argument validation failed: ${argumentErrors.join("; ")}`);
}

if (forcedWriteOnly && TARGET_ASSERTION_TOOLS.has(cfg.tool)) {
  const actualTargetName = await resolveTargetName(cfg.tool, cfg.arguments || {});
  if (!actualTargetName) throw new Error("No se pudo resolver el nombre del recurso objetivo; write bloqueado.");
  if (actualTargetName !== cfg.expectedTargetName) {
    throw new Error("expectedTargetName no coincide con el recurso resuelto; write bloqueado.");
  }
}

const result = await request("tools/call", {
  name: cfg.tool,
  arguments: cfg.arguments || {},
});

if (result?.isError) {
  throw new Error(`MCP tool ${cfg.tool} devolvio isError=true`);
}

const isWrite = !READ_ONLY_TOOLS.has(cfg.tool);
const safeResult = isWrite && repoVisibility === "public"
  ? publicWriteSummary(result)
  : (cfg.outputMode === "full" ? result : sanitize(result));

const payload = {
  ok: true,
  tool: cfg.tool,
  mode: isWrite ? "write" : "read",
  serverInfo: initialized.serverInfo || null,
  result: safeResult,
};

fs.mkdirSync("n8n-mcp/out", { recursive: true });
fs.writeFileSync("n8n-mcp/out/result.json", JSON.stringify(payload, null, 2));
console.log(JSON.stringify(payload, null, 2));
