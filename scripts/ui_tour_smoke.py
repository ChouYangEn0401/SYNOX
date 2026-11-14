"""新手教學的真瀏覽器煙霧測試（開發用；不在 pytest 裡，因為要 Playwright＋Chromium）。

    python scripts/ui_tour_smoke.py --chromium /path/to/chromium --out shots/

做的事（全部在暫存資料夾，網頁只綁 127.0.0.1 的隨機埠；官方工具庫用假的網路，不連外）：
1. 開一支「剛裝好」的 SYNOX（一個工具都沒有）＋網頁，用一次性登入連結登入。
2. 第一次打開網頁 → 有「要不要我帶你走一遍？」→ 按「開始」→ 照著每一步做（像真的人：自己按「對話」「工具」「設定」、
   按「幫我填好」再按送出、載入工具清單、按安裝、看報告、**自己按確認安裝**、移除），檢查每一步有沒有自動往下走、
   聚光圈有沒有指對地方、焦點有沒有移到小卡。
3. 走完 → 在對話打 /tutorial → 從頭複習；Esc 收起成小按鈕、再展開、「先離開」。
4. 桌機（1280×820）與手機（360×740，減少動態）各跑一次；手機寬度不能有橫向捲軸。每一步都截圖。
有任何一項不對、或瀏覽器主控台有錯誤，結束碼就不是 0。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "tests")]

OWNER = 100


def make_synox(tmp: str):
    from isdtelekit.testing import FakeChannel
    from synox.app import build
    from synox.config import SynoxConfig
    from synox.vault import Vault
    from test_pack_library import _entry, _web, _zip

    data = os.path.join(tmp, "data")
    packs = os.path.join(tmp, "packs")
    os.makedirs(packs)
    config = SynoxConfig.from_dict({"owner_id": OWNER, "data_dir": data, "vault": {"mode": "file"},
                                    "llm": {"kind": "none"}, "web": {"port": 0}}, require_token=False, root=tmp)
    app = build(config, home=FakeChannel(), adapter=None, vault=Vault(b"k" * 32, data), pack_dirs=[packs])
    ui = app.extras["synox_web"]
    blob = _zip("hello", "0.2.0")
    ui.catalog_opener = _web([_entry("hello", "0.2.0", blob)], {"hello-0.2.0.synoxpack": blob})
    assert ui.start(), ui.error
    return app, ui, data


class Run:

    def __init__(self, page, out: str, tag: str):
        self.page, self.out, self.tag, self.n = page, out, tag, 0
        self.problems = []

    def shot(self, name: str):
        self.n += 1
        path = os.path.join(self.out, f"{self.tag}-{self.n:02d}-{name}.png")
        self.page.screenshot(path=path)
        return path

    def check(self, ok: bool, what: str):
        if not ok:
            self.problems.append(f"[{self.tag}] {what}")
            print("  ✗", what)

    def count(self) -> str:
        return self.page.locator(".tour-card .count").inner_text(timeout=4000)

    def wait_count(self, want: str, what: str, timeout=4000):
        try:
            self.page.wait_for_function(
                "w => { const c = document.querySelector('.tour-card .count'); return c && c.textContent.indexOf(w) === 0; }",
                arg=want, timeout=timeout)
        except Exception:
            self.check(False, f"{what}：等不到「{want}」（現在：{self.count()}）")

    def ring_on(self, selector: str) -> bool:
        """聚光圈框住目標（目標比畫面大時，只看畫面裡的那一段）。"""
        self.page.wait_for_timeout(350)                       # 聚光圈有 .22s 的移動動畫
        return self.page.evaluate("""s => {
            const r = document.querySelector('.tour-ring'), t = document.querySelector(s);
            if (!r || r.classList.contains('hidden') || !t) return false;
            const a = r.getBoundingClientRect(), b = t.getBoundingClientRect();
            const top = Math.max(0, b.top), bottom = Math.min(innerHeight, b.bottom);
            return a.left <= b.left + 1 && a.top <= top + 1 && a.right >= b.right - 1 && a.bottom >= bottom - 1;
        }""", selector)

    def next(self):
        self.page.locator(".tour-card .tour-actions button", has_text="下一步").click()


def walk(page, run: Run, phone: bool):
    p = page
    p.wait_for_selector(".tour-offer", timeout=6000)
    run.check("要不要我帶你走一遍" in p.locator(".tour-offer h2").inner_text(), "邀請卡的字")
    run.shot("offer")
    p.locator(".tour-offer button", has_text="開始").click()
    p.wait_for_selector(".tour-card")
    total = run.count().split("／")[1]
    run.check(total == "12", f"擁有者應該是 12 步（{total}）")
    run.check(p.evaluate("document.activeElement && document.activeElement.id") == "tour-title", "焦點移到小卡標題")
    run.shot("welcome")
    run.next()
    run.wait_count("教學 2／", "第 2 步")
    run.check(run.ring_on('[data-tour="nav.chat"]'), "聚光圈在「對話」上")
    run.check("已經在這裡" in p.locator(".tour-card").inner_text(), "已經在對話頁：打勾、不自動跳")
    run.shot("open-chat")
    run.next()
    run.wait_count("教學 3／", "第 3 步")
    run.check(run.ring_on('[data-tour="chat.input"]'), "聚光圈在輸入框")
    run.shot("ask-help")
    p.locator(".tour-card button", has_text="幫我填好").click()
    run.check(p.input_value("#input") == "/help", "「幫我填好」只填字")
    run.check(p.locator(".tour-card").count() == 1 and run.count().startswith("教學 3／"), "填好不會自己送出")
    p.locator('[data-tour="chat.send"]').click()                        # 使用者自己按送出
    run.wait_count("教學 4／", "送出 /help 之後自動到下一步")
    run.shot("new-chat")
    run.next()
    run.wait_count("教學 5／", "第 5 步")
    run.shot("tools-before")
    p.locator('[data-tour="nav.tools"]').click()
    run.wait_count("教學 6／", "按「工具」之後自動到下一步")
    run.shot("open-settings")
    p.locator('[data-tour="nav.settings"]').click()
    run.wait_count("教學 7／", "按「設定」之後自動到下一步")
    p.wait_for_timeout(300)
    run.check(run.ring_on('[data-tour="settings.tab.packs"]'), "聚光圈在「功能與安裝」分頁")
    run.shot("packs-tab")
    p.locator('[data-tour="settings.tab.packs"]').click()
    run.wait_count("教學 8／", "按分頁之後自動到下一步")
    p.wait_for_timeout(300)
    run.shot("catalog")
    p.locator('[data-tour="settings.packs.catalog.load"]').click()      # 使用者自己按「載入工具清單」
    run.wait_count("教學 9／", "載入清單之後自動到下一步")
    run.shot("read-report-before")
    p.locator("#lib-list button", has_text="安裝").first.click()       # 使用者自己按「安裝」→ 先看報告
    p.wait_for_selector("#pack-review:not(.hidden)")
    p.wait_for_timeout(600)
    run.check(run.ring_on('[data-tour="settings.packs.review"]'), "聚光圈移到檢查報告")
    run.check(run.count().startswith("教學 9／"), "看到報告還沒裝：停在這一步")
    run.shot("read-report")
    p.locator("#pack-review button", has_text="確認安裝").click()      # 使用者自己按確認
    run.wait_count("教學 10／", "自己按確認裝好之後自動到下一步", timeout=15000)
    p.wait_for_timeout(500)
    run.shot("remove")
    if p.locator("#pack-rows button", has_text="移除").count():
        p.once("dialog", lambda d: d.accept())
        p.locator("#pack-rows button", has_text="移除").first.click()
        p.wait_for_timeout(800)
    run.next()
    run.wait_count("教學 11／", "第 11 步")
    run.shot("get-help")
    run.next()
    run.wait_count("教學 12／", "最後一步")
    card = p.locator(".tour-card").inner_text()
    run.check("現在你可以自己挑想要的工具了" in card and "帶我去" in card, "最後一步的字＋「帶我去」")
    run.shot("done")
    p.locator(".tour-card button", has_text="完成").click()
    p.wait_for_timeout(300)
    run.check(p.locator(".tour-card").count() == 0, "完成之後小卡收掉")
    # 複習：在對話打 /tutorial
    p.locator('[data-tour="nav.chat"]').click()
    p.wait_for_timeout(500)
    p.fill("#input", "/tutorial")
    p.locator('[data-tour="chat.send"]').click()
    try:
        p.wait_for_selector(".tour-card", timeout=6000)
        run.wait_count("教學 1／", "走完後再打 /tutorial＝從頭複習")
    except Exception:
        run.check(False, "打 /tutorial 之後沒有開始教學")
    run.check(p.locator(".msg .tour-start").count() >= 1, "對話裡有「在畫面上帶我走」按鈕")
    run.shot("replay")
    p.keyboard.press("Escape")
    run.check(p.locator(".tour-pill").count() == 1, "Esc 收成小按鈕")
    run.shot("minimized")
    p.locator(".tour-pill").click()
    run.check(p.locator(".tour-card").is_visible(), "按小按鈕展開")
    p.locator(".tour-card button", has_text="先離開").click()
    run.check(p.locator(".tour-card").count() == 0, "先離開")
    if phone:
        wide = p.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        run.check(wide <= 0, f"手機寬度有橫向捲軸（多 {wide}px）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium", default="/opt/pw-browsers/chromium")
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "synox-tour-shots"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    from playwright.sync_api import sync_playwright

    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium)
        for tag, size, phone in (("desktop", (1280, 820), False), ("phone", (360, 740), True)):
            tmp = tempfile.mkdtemp(prefix="synox-tour-")
            try:
                app, ui, _data = make_synox(tmp)
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]},
                                          reduced_motion="reduce" if phone else "no-preference",
                                          device_scale_factor=2 if phone else 1)
                ctx.add_init_script("window.SYNOX_NO_SPLASH = true;")   # 開場的門（splash.js）不出現：這裡測的是教學
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(f"{m.text} {m.location.get('url', '')}")
                        if m.type == "error" and not str(m.location.get("url", "")).endswith("/favicon.ico") else None)
                page.on("response", lambda r: errors.append(f"{r.status} {r.url}")
                        if r.status >= 400 and not r.url.endswith("/favicon.ico") else None)
                page.goto(ui.login_link(OWNER))
                page.locator("button[type=submit]").click()
                page.wait_for_selector("#view-chat:not(.hidden)")
                run = Run(page, args.out, tag)
                print(f"== {tag} {size[0]}×{size[1]}")
                try:
                    walk(page, run, phone)
                except Exception as e:                      # 卡住了：留一張圖再報
                    run.check(False, f"中途出錯：{e}")
                    run.shot("error")
                run.check(not errors, f"瀏覽器主控台有錯誤：{errors[:6]}")
                problems += run.problems
                ctx.close()
                ui.stop()
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        browser.close()
    print(f"截圖：{args.out}")
    print("全部通過" if not problems else "有問題：\n" + "\n".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
