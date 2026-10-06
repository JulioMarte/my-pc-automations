#!/usr/bin/env node
import fs from "node:fs";
import { N8N_MCP_TOOLS, READ_ONLY_TOOLS } from "./tools.mjs";

const rawUrl = process.env.N8N_MCP_URL;
const token = process.env.N8N_MCP_TOKEN;
const requestPath = process.env.MCP_REQUEST_FILE || "n8n-mcp/request.json";
const repoVisibility = (process.env.REPO_VISIBILITY || "unknown").toLowerCase();

if (!rawUrl || !token) throw new Error("Faltan N8N_MCP_URL o N8N_MCP_TOKEN.");
if (!fs.existsSync(requestPath)) throw new Error(`No existe ${requestPath}`);

const cfg = JSON.parse(fs.readFileSync(requestPath, "utf8"));
if (!N8N_MCP_TOOLS.includes(cfg.tool)) throw new Error(`Tool no permitida: ${cfg.tool}`);

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

function validateArgumentsAgainstSchema(schema, args) {
  if (!schema || schema.type !== "object") return [];
  const errors = [];
  const properties = schema.properties || {};
  for (const key of schema.required || []) {
    if (!(key in args)) errors.push(`Missing required argument: ${key}`);
  }
  if (schema.additionalProperties === false) {
    for (const key of Object.keys(args)) {
      if (!(key in properties)) errors.push(`Unknown argument: ${key}`);
    }
  }
  for (const [key, value] of Object.entries(args)) {
    const prop = properties[key];
    if (!prop || value == null) continue;
    const expected = Array.isArray(prop.type) ? prop.type : [prop.type];
    if (!prop.type) continue;
    const actual = Array.isArray(value) ? "array" : typeof value;
    const normalized = actual === "number" && Number.isInteger(value) ? ["integer", "number"] : [actual];
    if (!expected.some((t) => normalized.includes(t))) {
      errors.push(`Argument ${key} expected ${expected.join("|")}, got ${actual}`);
    }
  }
  return errors;
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

const result = await request("tools/call", {
  name: cfg.tool,
  arguments: cfg.arguments || {},
});

const payload = {
  ok: true,
  tool: cfg.tool,
  mode: READ_ONLY_TOOLS.has(cfg.tool) ? "read" : "write",
  serverInfo: initialized.serverInfo || null,
  result: cfg.outputMode === "full" ? result : sanitize(result),
};

fs.mkdirSync("n8n-mcp/out", { recursive: true });
fs.writeFileSync("n8n-mcp/out/result.json", JSON.stringify(payload, null, 2));
console.log(JSON.stringify(payload, null, 2));
