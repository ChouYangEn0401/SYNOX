from isdtelekit.core.registry import DANGER, CommandRegistry, Field
from isdtelekit.users.models import User
from isdtelekit.users.roles import BasicRoles

from synox.agent import tools
from synox.agent.loop import ai_decision, needs_card
from synox.packs import kit

OWNER = 100


def _registry():
    reg = CommandRegistry(owner_id=OWNER)
    reg.define_group("money", "💰", "記帳", owner_only=True)
    g = reg.group("money")
    kit.command(g, "add", lambda *a: None, "記一筆", default=True, fields=[
        Field("amount", "金額", required=True), Field("category", "類別", required=True), Field("memo", "備註")])
    n = g.leaf("pay", lambda *a: None, "付錢", effect=DANGER)
    n.fields = (Field("to", "給誰", required=True), Field("code", "驗證碼", fresh_code=True, required=True))
    g.leaf("chat", lambda *a: None, "聊天", interactive=True)
    g.leaf("knob", lambda *a: None, "放寬安全的開關", ai=False)
    g.leaf("raw", lambda *a: None, "原始參數", usage="<子指令…>")
    reg.define_group("agent", "🤖", "", bare=True)
    reg.group("agent").leaf("ai", lambda *a: None, "AI")
    reg.define_group("sudo", "🔐", "")
    reg.group("sudo").leaf("on", lambda *a: None, "解鎖")
    return reg


def _owner():
    return User(OWNER, "me", BasicRoles.ADMIN)


def test_names_and_lookup():
    reg = _registry()
    specs = {s.name: s for s in tools.build(reg, lambda n: ai_decision(reg, _owner(), n))}
    assert "money__add" in specs and tools.node_for(reg, "money__add").path == "money.add"
    assert tools.node_for(reg, "money") is None             # 群組不是工具


def test_exclusions():
    reg = _registry()
    names = {s.name for s in tools.build(reg, lambda n: ai_decision(reg, _owner(), n))}
    assert names == {"money__add", "money__pay", "money__raw"}
    # 不是擁有者：owner_only 的群組整個看不到
    stranger = User(7, "x", BasicRoles.GUEST)
    assert tools.build(reg, lambda n: ai_decision(reg, stranger, n)) == []


def test_schema_from_fields_skips_codes():
    reg = _registry()
    add = tools.schema(reg.node("money.add"))
    assert add["properties"].keys() == {"amount", "category", "memo"}
    assert add["required"] == ["amount", "category"]
    assert all(p["type"] == "string" for p in add["properties"].values())
    pay = tools.schema(reg.node("money.pay"))
    assert "code" not in pay["properties"] and pay["required"] == ["to"]
    assert "驗證碼" not in tools.description(reg.node("money.pay"))
    raw = tools.schema(reg.node("money.raw"))
    assert raw["properties"].keys() == {"args"}


def test_description_mentions_card_for_danger():
    reg = _registry()
    assert "確認卡" in tools.description(reg.node("money.pay"))
    assert "確認卡" not in tools.description(reg.node("money.add"))


def test_to_argv_round_trips_through_kit():
    reg = _registry()
    node = reg.node("money.add")
    argv = tools.to_argv(node, {"amount": "80", "category": "咖啡", "memo": "跟 同事"})
    values, missing, errors = kit.parse_args(node.fields, argv, positional=0)
    assert values == {"amount": "80", "category": "咖啡", "memo": "跟 同事"} and not missing and not errors
    assert tools.to_argv(reg.node("money.raw"), {"args": "a b"}) == ["a", "b"]
    assert tools.unknown_args(node, {"amount": "1", "evil": "x"}) == ["evil"]


def test_needs_card():
    reg = _registry()
    assert needs_card(reg.node("money.pay"), [])
    assert not needs_card(reg.node("money.add"), [])
