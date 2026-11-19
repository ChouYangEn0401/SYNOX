"""電腦提醒視窗的外觀（synox/remindwin/style.py）：跟著網頁外觀的 token，換成 tkinter 看得懂的 #rrggbb。"""

from synox.remindwin import style


def test_defaults_match_the_web_console():
    from synox.theme import contract
    for mode in ("light", "dark"):
        for name in ("bg", "surface", "text", "muted", "line", "accent", "accent-ink", "ok", "warn", "bad"):
            assert style.DEFAULTS[mode][name] == contract.DEFAULTS[mode][name]


def test_parse_color_forms():
    toks = {"accent": "#0a7c70", "surface": "#ffffff"}
    assert style.parse_color("#fff", toks) == (255, 255, 255, 1.0)
    assert style.parse_color("#0A7C70", toks)[:3] == (10, 124, 112)
    assert style.parse_color("rgb(1, 2, 3)", toks) == (1, 2, 3, 1.0)
    assert style.parse_color("rgba(53, 224, 196, .12)", toks) == (53, 224, 196, 0.12)
    assert style.parse_color("var(--accent)", toks)[:3] == (10, 124, 112)
    mixed = style.parse_color("color-mix(in srgb, var(--accent) 50%, #ffffff)", toks)
    assert mixed[:3] == (132, 190, 184)
    assert style.parse_color("oklch(0.7 0.1 200)", toks) is None
    assert style.parse_color("var(--nope)", toks) is None


def test_transparent_colors_are_blended_onto_the_card():
    pal = style.palette("dark")
    assert pal["surface"] == "#121924"
    assert pal["soft"].startswith("#") and len(pal["soft"]) == 7 and pal["soft"] != pal["surface"]


def test_theme_tokens_override_and_bad_values_fall_back():
    toks = {"bg": "#f5f3ef", "surface": "#fffdf8", "text": "#2a2118", "muted": "#7a6a58", "line": "#eadfce",
            "accent": "#b4541a", "accent-ink": "#ffffff", "accent2": "#3a6ea5", "soft": "#f7e7d8",
            "ok": "#2f7d32", "warn": "#9a6400", "bad": "oklch(0.5 0.2 20)"}
    pal = style.palette("light", toks)
    assert pal["accent"] == "#b4541a" and pal["surface"] == "#fffdf8"
    assert pal["bad"] == style.DEFAULTS["light"]["bad"]               # 看不懂的那一個用原本的
    assert pal["accent-hover"] != style.DEFAULTS["light"]["accent-hover"]   # 進階 token 從外觀包的核心色算


def test_look_follows_mode_and_system(tmp_path):
    assert style.load(str(tmp_path), dark_system=True).mode == "dark"          # 沒有檔案＝原本的 SYNOX、跟著系統
    assert style.load(str(tmp_path), dark_system=False).mode == "light"
    style.write(str(tmp_path), theme="costume-x", mode="dark",
                tokens={"light": {"radius": "14px", "font-ui": "\"Fraunces\", \"Noto Sans TC\", serif"},
                        "dark": {"accent": "#ff8800"}})
    got = style.load(str(tmp_path), dark_system=False)
    assert got.mode == "dark" and got.theme == "costume-x" and got.colors["accent"] == "#ff8800"
    assert got.radius == 14 and "Noto Sans TC" in got.font_ui                  # 深色沒寫：跟淺色的字型、圓角


def test_write_is_idempotent(tmp_path):
    p = style.write(str(tmp_path), mode="light")
    mtime = __import__("os").path.getmtime(p)
    assert style.write(str(tmp_path), mode="light") == p
    assert __import__("os").path.getmtime(p) == mtime
    assert style.read(str(tmp_path))["mode"] == "light"


def test_pick_font_prefers_an_installed_cjk_font():
    css = "\"Segoe UI Variable Text\", \"Segoe UI\", \"Microsoft JhengHei UI\", system-ui, sans-serif"
    assert style.pick_font(css, ["Segoe UI", "Microsoft JhengHei UI"]) == "Microsoft JhengHei UI"
    assert style.pick_font("\"Noto Sans TC\"", ["Noto Sans TC", "Microsoft JhengHei UI"]) == "Noto Sans TC"
    assert style.pick_font("Fraunces", []) == "Microsoft JhengHei UI"


def test_window_wording():
    from synox.notify import desk as deskmod
    from synox.remindwin import logic
    assert logic.T["title"] == "⏰ 提醒" and logic.T["move_head"] == "安排到別天"
    assert logic.LABELS[deskmod.BTN_ACK] == "我知道了" and logic.LABELS[deskmod.BTN_DONE] == "我完成了"
    assert logic.LABELS[deskmod.BTN_RESCHEDULE_PICK].startswith("挑日期時間")
