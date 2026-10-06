#!/usr/bin/env node
import fs from "node:fs";

const rawUrl = process.env.N8N_MCP_URL;
const token = process.env.N8N_MCP_TOKEN;

if (!rawUrl || !token) {
  throw new Error("Faltan N8N_MCP_URL o N8N_MCP_TOKEN en GitHub Actions Secrets.");
}

const endpoint = new URL(rawUrl);
if (endpoint.protocol !== "https:" ||
    endpoint.hostname !== "n8n.quisqueyatech.com" ||
    endpoint.pathname !== "/mcp-server/http") {
  throw new Error("N8N_MCP_URL no coincide con el endpoint n8n permitido.");
}

let sessionId;
let id = 0;
const protocolVersion = "2025-06-18";

function parseSse(body) {
  const messages = [];
  for (const event of body.split(/\r?\n\r?\n/)) {
    const data = event.split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("\n");
    if (!data) continue;
    try { messages.push(JSON.parse(data)); } catch {}
  }
  return messages;
}

async function send(payload, expectResult = true) {
  const headers = {
    "authorization": `Bearer ${token}`,
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
    "mcp-protocol-version": protocolVersion,
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;

  const res = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (res.headers.get("mcp-session-id")) {
    sessionId = res.headers.get("mcp-session-id");
  }

  const body = await res.text();
  if (!res.ok) throw new Error(`MCP HTTP ${res.status}: ${body.slice(0, 500)}`);
  if (!expectResult || !body) return null;

  const contentType = res.headers.get("content-type") || "";
  const messages = contentType.includes("text/event-stream")
    ? parseSse(body)
    : [JSON.parse(body)];

  const error = messages.find((m) => m?.error);
  if (error) throw new Error(`MCP ${error.error.code}: ${error.error.message}`);

  return messages.find((m) => m?.result !== undefined) ?? messages.at(-1);
}

async function request(method, params = {}) {
  const requestId = ++id;
  const msg = await send({ jsonrpc: "2.0", id: requestId, method, params });
  if (!msg?.result) throw new Error(`Respuesta invalida para ${method}`);
  return msg.result;
}

const init = await request("initialize", {
  protocolVersion,
  capabilities: {},
  clientInfo: { name: "my-pc-automations-n8n-diagnostic", version: "1.0.0" },
});

await send({ jsonrpc: "2.0", method: "notifications/initialized", params: {} }, false);

const tools = [];
let cursor;
do {
  const result = await request("tools/list", cursor ? { cursor } : {});
  tools.push(...(result.tools || []));
  cursor = result.nextCursor;
} while (cursor);

const output = {
  ok: true,
  serverInfo: init.serverInfo ?? null,
  protocolVersion: init.protocolVersion ?? null,
  capabilities: init.capabilities ?? {},
  toolCount: tools.length,
  tools: tools.map((tool) => ({
    name: tool.name,
    description: tool.description ?? null,
    inputSchema: tool.inputSchema ?? null,
  })),
};

fs.mkdirSync("n8n-mcp/out", { recursive: true });
fs.writeFileSync("n8n-mcp/out/tools.json", JSON.stringify(output, null, 2));
console.log(JSON.stringify(output, null, 2));
