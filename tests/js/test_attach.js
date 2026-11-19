// 附件的三個入口（📎、貼上、拖進來）共用的檢查（src/synox/web/static/attach.js）。
// 假的 File／剪貼簿／拖放物件，不開瀏覽器、不開埠；tests/test_web_reply.py 用 node 跑，退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const A = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "attach.js"));

const ACCEPT = "image/png,image/jpeg,image/webp,image/gif,.xlsx,.docx,.csv,.tsv,.txt,.md,.json,.log";

function file(name, size, type) {
  return { name: name, size: size, type: type || "", arrayBuffer() { return Promise.resolve(new ArrayBuffer(0)); } };
}
function clip({ text = "", files = [], items = null }) {
  return {
    getData(t) { return t === "text/plain" ? text : ""; },
    files: files,
    items: items || files.map((f) => ({ kind: "file", type: f.type, getAsFile: () => f })),
  };
}

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("a pasted screenshot becomes an attachment", () => {
  const shot = file("image.png", 2048, "image/png");
  assert.deepStrictEqual(A.fromClipboard(clip({ files: [shot] })), [shot]);
});

test("paste falls back to clipboard items when files is empty", () => {
  const shot = file("", 2048, "image/png");
  const got = A.fromClipboard(clip({ files: [], items: [{ kind: "string", getAsFile: () => null },
                                                        { kind: "file", getAsFile: () => shot }] }));
  assert.deepStrictEqual(got, [shot]);
  assert.strictEqual(A.displayName(shot), "貼上的圖片.png");
});

test("pasting text (even with an image of it, like from Excel) stays a text paste", () => {
  const pic = file("image.png", 2048, "image/png");
  assert.deepStrictEqual(A.fromClipboard(clip({ text: "a\tb\n1\t2", files: [pic] })), []);
  assert.deepStrictEqual(A.fromClipboard(clip({ text: "hello" })), []);
  assert.deepStrictEqual(A.fromClipboard(null), []);
});

test("only File objects are taken, never path strings", () => {
  const real = file("notes.txt", 10, "text/plain");
  const dt = { types: ["Files", "text/uri-list"], files: [real, "C:\\secret\\x.txt", { name: "fake.txt", size: 3 }] };
  assert.deepStrictEqual(A.fromDrop(dt), [real]);
  assert.deepStrictEqual(A.fromDrop({ types: ["text/plain"], files: [] }), []);
  assert.deepStrictEqual(A.fromDrop(null), []);
  const cd = clip({ files: [], items: [{ kind: "file", getAsFile: () => "file:///C:/x.png" }] });
  assert.deepStrictEqual(A.fromClipboard(cd), []);
});

test("hasFiles only for file drags", () => {
  assert.strictEqual(A.hasFiles({ types: ["Files"] }), true);
  assert.strictEqual(A.hasFiles({ types: ["text/plain", "text/uri-list"] }), false);
  assert.strictEqual(A.hasFiles(null), false);
});

test("several dropped files are planned together", () => {
  const p = A.plan([file("a.png", 5, "image/png"), file("b.csv", 5, "text/csv"), file("c.xlsx", 5, "")], 0, ACCEPT);
  assert.deepStrictEqual(p.ok.map((x) => x.name), ["a.png", "b.csv", "c.xlsx"]);
  assert.deepStrictEqual(p.problems, []);
});

test("same type rule as the 📎 picker (accept attribute)", () => {
  assert.strictEqual(A.accepts(file("A.PNG", 1, "image/png"), ACCEPT), true);
  assert.strictEqual(A.accepts(file("Report.XLSX", 1, ""), ACCEPT), true);
  assert.strictEqual(A.accepts(file("setup.exe", 1, "application/x-msdownload"), ACCEPT), false);
  assert.strictEqual(A.accepts(file("x.png.exe", 1, ""), ACCEPT), false);
  assert.strictEqual(A.accepts(file("doc.pdf", 1, "application/pdf"), ACCEPT), false);
  assert.strictEqual(A.accepts(file("pic.bmp", 1, "image/bmp"), "image/*"), true);
  assert.strictEqual(A.accepts(file("any.bin", 1, ""), ""), true);
  const p = A.plan([file("setup.exe", 5, ""), file("ok.txt", 5, "text/plain")], 0, ACCEPT);
  assert.deepStrictEqual(p.ok.map((x) => x.name), ["ok.txt"]);
  assert.strictEqual(p.problems.length, 1);
  assert.ok(p.problems[0].indexOf("setup.exe") >= 0);
});

test("size limits: empty and over 10 MB are refused", () => {
  const p = A.plan([file("e.txt", 0, "text/plain"), file("big.png", A.MAX_BYTES + 1, "image/png"),
                    file("edge.png", A.MAX_BYTES, "image/png")], 0, ACCEPT);
  assert.deepStrictEqual(p.ok.map((x) => x.name), ["edge.png"]);
  assert.strictEqual(p.problems.length, 2);
  assert.ok(p.problems[0].indexOf("e.txt") >= 0 && p.problems[1].indexOf("big.png") >= 0);
});

test("count limit counts the ones already attached", () => {
  const many = Array.from({ length: 5 }, (_, i) => file(i + ".png", 5, "image/png"));
  const p = A.plan(many, A.MAX_COUNT - 2, ACCEPT);
  assert.strictEqual(p.ok.length, 2);
  assert.strictEqual(p.problems.length, 1);
  assert.ok(p.problems[0].indexOf(String(A.MAX_COUNT)) >= 0);
  assert.strictEqual(A.plan(many, A.MAX_COUNT, ACCEPT).ok.length, 0);
});

test("names are only for display: whatever the name says, it is not used as a path", () => {
  const p = A.plan([file("..\\..\\evil.txt", 5, "text/plain")], 0, ACCEPT);
  assert.strictEqual(p.ok.length, 1);
  assert.strictEqual(p.ok[0].file.name, "..\\..\\evil.txt");    // 原樣交給伺服器的 X-SYNOX-Filename；web/uploads.clean_name 會清
});

test("paste listener: a screenshot in the chat view is attached, text pastes are left alone", () => {
  const body = { view: "chat", getAttribute(k) { return k === "data-view" ? this.view : null; } };
  const doc = { body: body };
  const input = { tagName: "TEXTAREA" };
  const got = [];
  const on = A.pasteListener(doc, input, (files) => got.push(files));
  const shot = file("image.png", 100, "image/png");
  function paste(target, cd) {
    const ev = { target: target, clipboardData: cd, prevented: false, preventDefault() { this.prevented = true; } };
    on(ev);
    return ev.prevented;
  }
  assert.strictEqual(paste(input, clip({ files: [shot] })), true);                       // 輸入框裡 Ctrl+V 截圖
  assert.strictEqual(paste({ tagName: "DIV" }, clip({ files: [shot, shot] })), true);    // 對話區別的地方也可以，好幾個
  assert.deepStrictEqual(got.map((f) => f.length), [1, 2]);
  assert.strictEqual(paste(input, clip({ text: "hello", files: [shot] })), false);       // 有字：照常貼字
  assert.strictEqual(paste({ tagName: "INPUT" }, clip({ files: [shot] })), false);       // 在別的輸入框（例如改標題）：不管
  assert.strictEqual(paste({ tagName: "DIV", isContentEditable: true }, clip({ files: [shot] })), false);
  body.view = "settings";
  assert.strictEqual(paste(input, clip({ files: [shot] })), false);                      // 不在對話頁：不管
  assert.strictEqual(got.length, 2);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
