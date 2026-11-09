"""終端機模式冒煙測試：SDK 的 run_console，輸入從清單來、輸出收進清單（不碰真的 stdin）。"""

from isdtelekit.host.console import run_console


def _console(bot, lines):
    out = []
    feed = iter(lines)

    def ask(_prompt):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError

    run_console(bot.app, ask=ask, out=out.append)
    return "\n".join(out)


def test_help_lists_groups(make_bot):
    bot = make_bot()
    text = _console(bot, ["/help all"])
    for title in ("📒 隨手記", "💰 記帳", "⏰ 提醒", "🤖 AI 助理", "🗓 排程指令"):
        assert title in text
    for cmd in ("/note ", "/money ", "/remind_add", "/ai ", "/ai_usage"):
        assert cmd in text


def test_console_flow(make_bot):
    bot = make_bot(None)                     # 示範 AI
    text = _console(bot, ["/money 120 午餐", "/money_month", "/remind_add 08:00 吃藥", "/remind_list",
                          "/note 買牛奶", "/note_list", "幫我記一筆 80 元咖啡", "把筆記全部刪掉", "!1", "/note_list"])
    assert "記了：午餐 120 元" in text and "共 120 元" in text
    assert "每天 08:00 提醒你：吃藥" in text and "1. 每天 08:00  吃藥" in text
    assert "記了：咖啡 80 元" in text
    assert "AI 想執行：/note_clear" in text and "全部筆記都刪掉了（1 筆）" in text
    assert text.rstrip().endswith("👋 bye")


def test_main_help_and_doctor_offline(capsys, tmp_path):
    from synox.__main__ import main
    assert main([]) == 1
    cfg = tmp_path / "config.json"
    cfg.write_text('{"owner_id": 1, "data_dir": "%s", "llm": {"kind": "fake"}, "vault": {"mode": "file"}}'
                   % str(tmp_path / "data").replace("\\", "/"), encoding="utf-8")
    code = main(["--config", str(cfg), "doctor", "--offline"])
    out = capsys.readouterr().out
    assert "SYNOX" in out and "packs：" in out and "money" in out and "--offline" in out
    assert code == 1                          # 沒有 bot_token 算一個問題
