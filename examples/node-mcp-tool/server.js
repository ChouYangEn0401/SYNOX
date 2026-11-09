// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 The SYNOX authors
//
// 最小的 MCP stdio 伺服器：只用 Node 標準函式庫（readline），不依賴任何 npm 套件，所以沒有 node_modules。
// 協定：JSON-RPC 2.0，一行一個訊息；stdin 進、stdout 出。log 一律寫 stderr（寫 stdout 會弄壞 JSON-RPC）。
//
//   node server.js        → 等 stdin 的 JSON-RPC
//
// 只實作 SYNOX 會用到的四個方法：initialize、ping、tools/list、tools/call
// （notifications/initialized 是通知，不回）。

"use strict";

const readline = require("readline");

const PROTOCOL_VERSION = "2025-06-18";

// 工具清單。SYNOX 只會用 pack.json 的 mcp.tools_allow 列的那幾個；effect 也只看 pack.json 的 mcp.effects，
// 這裡寫什麼 annotations 都不算。internal_stats 故意沒列進 tools_allow：示範「伺服器多列的，SYNOX 看不到、叫不到」。
const TOOLS = [
  {
    name: "count_words",
    description: "數一段文字有幾個字、幾行。",
    inputSchema: {
      type: "object",
      properties: { text: { type: "string", description: "要數的文字" } },
      required: ["text"],
    },
  },
  {
    name: "roll_dice",
    description: "擲骰子：sides 面、擲 times 次。",
    inputSchema: {
      type: "object",
      properties: {
        sides: { type: "integer", description: "幾面（2 到 100，預設 6）" },
        times: { type: "integer", description: "擲幾次（1 到 20，預設 1）" },
      },
    },
  },
  {
    name: "internal_stats",
    description: "（沒有列進 tools_allow：在 SYNOX 裡不存在）",
    inputSchema: { type: "object", properties: {} },
  },
];

let calls = 0;

function text(message) {
  return { content: [{ type: "text", text: message }], isError: false };
}

function toolError(message) {
  return { content: [{ type: "text", text: message }], isError: true };
}

function callTool(name, args) {
  calls += 1;
  if (name === "count_words") {
    const value = typeof args.text === "string" ? args.text : "";
    const words = value.trim() ? value.trim().split(/\s+/u).length : 0;
    const chars = Array.from(value.replace(/\s/gu, "")).length;
    const lines = value ? value.split(/\r?\n/u).length : 0;
    return { ...text(`${words} 個詞、${chars} 個字（不含空白）、${lines} 行`),
             structuredContent: { words, chars, lines } };
  }
  if (name === "roll_dice") {
    const sides = args.sides === undefined ? 6 : args.sides;
    const times = args.times === undefined ? 1 : args.times;
    if (!Number.isInteger(sides) || sides < 2 || sides > 100) return toolError("sides 要是 2 到 100 的整數");
    if (!Number.isInteger(times) || times < 1 || times > 20) return toolError("times 要是 1 到 20 的整數");
    const rolls = Array.from({ length: times }, () => 1 + Math.floor(Math.random() * sides));
    const total = rolls.reduce((a, b) => a + b, 0);
    return { ...text(`擲了 ${times} 次 ${sides} 面骰：${rolls.join("、")}（共 ${total}）`),
             structuredContent: { rolls, total } };
  }
  if (name === "internal_stats") {
    return text(`這個程序處理了 ${calls} 次呼叫`);
  }
  return null;
}

function handle(msg) {
  const { id, method } = msg;
  const params = msg.params || {};
  switch (method) {
    case "initialize":
      return { result: { protocolVersion: PROTOCOL_VERSION, capabilities: { tools: {} },
                         serverInfo: { name: "node-mcp-tool", version: "0.1.0" } } };
    case "ping":
      return { result: {} };
    case "tools/list":
      return { result: { tools: TOOLS } };
    case "tools/call": {
      const out = callTool(params.name, params.arguments || {});
      if (out === null) return { error: { code: -32602, message: `沒有這個工具：${params.name}` } };
      return { result: out };
    }
    default:
      if (id === undefined) return null;                     // 通知（例如 notifications/initialized）：不回
      return { error: { code: -32601, message: `不支援的方法：${method}` } };
  }
}

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  if (!line.trim()) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch (e) {
    send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "不是 JSON" } });
    return;
  }
  let reply;
  try {
    reply = handle(msg);
  } catch (e) {
    process.stderr.write(`錯誤：${e && e.stack ? e.stack : e}\n`);
    reply = { error: { code: -32603, message: "內部錯誤" } };
  }
  if (reply !== null && msg.id !== undefined) send({ jsonrpc: "2.0", id: msg.id, ...reply });
});
rl.on("close", () => process.exit(0));
