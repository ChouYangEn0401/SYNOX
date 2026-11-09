# -*- coding: utf-8 -*-
"""cli pack 的指令：照位置填、key=value 補、選填不追問；commands[].stdin 的欄位走 stdin 不進 argv。
用一支假的命令列程式（印出收到的 argv 與 stdin 的 JSON）當 pack 的後端，真的經 JobRunner 跑。"""
import json
import os
import sys
import time

ECHO = r'''
import json, sys
data = sys.stdin.read() if not sys.stdin.isatty() else ""
print(json.dumps({"ok": True, "argv_text": " ".join(sys.argv[1:]), "stdin": data}, ensure_ascii=False))
'''


def _pack(folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "echo_cli.py"), "w", encoding="utf-8") as f:
        f.write(ECHO)
    manifest = {
        "name": "echo", "title": "回音", "summary": "測試用", "version": "0.1.0", "kind": "cli",
        "access": "owner", "auth": "none", "capabilities": ["subprocess"], "skill": "SKILL.md",
        "cli": {"python": sys.executable, "argv": ["{python}", "{pack_dir}/echo_cli.py"], "json_flag": "--json",
                "timeout": 30,
                "commands": [
                    {"name": "add", "default": True, "positional": 2, "effect": "write", "summary": "記一筆",
                     "argv": ["add", "--amount={amount}", "--desc={desc}", "--category={category}"],
                     "fields": [{"name": "amount", "ask": "多少", "required": True},
                                {"name": "desc", "ask": "什麼"}, {"name": "category", "ask": "類別"}]},
                    {"name": "put", "effect": "write", "summary": "寫入", "stdin": "{answers}",
                     "argv": ["put", "--date={date}"],
                     "fields": [{"name": "date", "ask": "日期", "required": True},
                                {"name": "answers", "ask": "內容", "required": True}]},
                ]},
    }
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: echo\ndescription: 測試\n---\n")


def _wait_for(bot, needle: str, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        texts = bot.texts()
        if any(needle in t for t in texts):
            return next(t for t in texts if needle in t)
        time.sleep(0.1)
    raise AssertionError(f"沒等到含 {needle!r} 的回覆：{bot.texts()}")


def _echo(reply_text: str) -> dict:
    # default_render 會把 JSON 結果印成文字；從回覆裡把 argv 與 stdin 撈回來（寬鬆：找最後一個 { 開頭的 JSON）
    start = reply_text.find("{")
    return json.loads(reply_text[start:]) if start >= 0 else {"text": reply_text}


def test_positional_fill_saves_without_asking(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    assert bot.app.extras["synox_pack_report"].items[0].status == "loaded"
    bot.say(owner, "/echo 120 午餐 category=食")
    bot.app.tasks.wait(20)
    texts = bot.texts()
    assert not any("要補充這些嗎" in t for t in texts), texts          # 選填不追問
    joined = "\n".join(texts)
    assert "--amount=120" in joined and "--desc=午餐" in joined and "--category=食" in joined


def test_stdin_field_goes_to_stdin_not_argv(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    bot.say(owner, "/echo_put 2026-11-10 answers=今天很好 很長的一段話")
    bot.app.tasks.wait(20)
    joined = "\n".join(bot.texts())
    assert "--date=2026-11-10" in joined
    assert "stdin：今天很好 很長的一段話" in joined                    # 內容有送到（經 stdin 印回來；render 用全形冒號）
    argv_line = next(t for t in joined.splitlines() if t.startswith("argv_text"))
    assert "answers" not in argv_line and "今天很好" not in argv_line      # 沒進 argv


def test_missing_required_field_is_a_short_error(make_bot, owner, tmp_path):
    _pack(str(tmp_path / "packs" / "echo"))
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    bot.say(owner, "/echo_put")
    bot.app.tasks.wait(5)
    assert any("日期" in t for t in bot.texts())
