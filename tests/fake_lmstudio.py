"""假的 LM Studio（給 urllib opener 用；不 listen 任何 port、不連網、不碰真的 LM Studio）。

有狀態：載入／卸載會真的改它記得的實例，之後 GET /api/v1/models 讀到的就是新的狀態。
mode：honor＝照 context_length 載入｜ignore＝不管帶什麼都載成 8192（伺服器默默不照做）｜error＝載入一律回 500。
欄位照 SYNOX 現有的 LM Studio 程式（src/synox/llm/local_models.py 的 _lmstudio_v1／load／unload）。
"""

import io
import json
import urllib.error
from urllib.parse import urlsplit

IGNORED_CONTEXT = 8192


class _Resp:
    def __init__(self, body=None, lines=None):
        self.status, self.body, self.lines = 200, body, list(lines or [])

    def read(self):
        return json.dumps(self.body).encode("utf-8") if self.body is not None else b"".join(self.lines)

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        pass


class FakeLMStudio:
    def __init__(self, mode="honor", *, reply="好", loaded=None):
        self.mode, self.reply = mode, reply
        self.models = {
            "qwen3.5-9b": {"size_bytes": 9_300_000_000, "max_context_length": 262144, "vision": True, "instances": []},
            "other-model": {"size_bytes": 4_000_000_000, "max_context_length": 32768, "vision": False, "instances": []},
        }
        for key, ctx in (loaded if loaded is not None else {"qwen3.5-9b": 8192, "other-model": 4096}).items():
            self.models[key]["instances"].append({"id": key, "ctx": ctx})
        self.calls = []

    def paths(self):
        return [c["path"] for c in self.calls]

    def instances(self, key):
        return [i["ctx"] for i in self.models[key]["instances"]]

    def __call__(self, request, timeout):
        path = urlsplit(request.full_url).path
        method = request.get_method()
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        self.calls.append({"method": method, "path": path, "body": body, "timeout": timeout})
        if (method, path) == ("GET", "/api/v1/models"):
            return _Resp({"models": [
                {"type": "llm", "key": k, "display_name": k, "size_bytes": m["size_bytes"],
                 "max_context_length": m["max_context_length"],
                 "loaded_instances": [{"id": i["id"], "config": {"context_length": i["ctx"]}} for i in m["instances"]],
                 "capabilities": {"vision": m["vision"], "trained_for_tool_use": True}}
                for k, m in self.models.items()]})
        if (method, path) == ("GET", "/v1/models"):
            return _Resp({"data": [{"id": k} for k in self.models]})
        if (method, path) == ("POST", "/api/v1/models/load"):
            if self.mode == "error":
                raise urllib.error.HTTPError(request.full_url, 500, "err", {},
                                             io.BytesIO(b'{"error": "Failed to load model: out of resources"}'))
            m = self.models[body["model"]]
            ctx = IGNORED_CONTEXT if self.mode == "ignore" else int(body.get("context_length") or 4096)
            inst = body["model"] if not m["instances"] else f"{body['model']}:{len(m['instances']) + 1}"
            m["instances"].append({"id": inst, "ctx": ctx})
            return _Resp({"instance_id": inst, "load_time_seconds": 1.5})
        if (method, path) == ("POST", "/api/v1/models/unload"):
            for m in self.models.values():
                m["instances"] = [i for i in m["instances"] if i["id"] != body["instance_id"]]
            return _Resp({"instance_id": body["instance_id"]})
        if (method, path) == ("POST", "/v1/chat/completions"):
            chunk = {"choices": [{"delta": {"content": self.reply}, "finish_reason": "stop"}]}
            return _Resp(lines=[f"data: {json.dumps(chunk, ensure_ascii=False)}\n".encode("utf-8"), b"data: [DONE]\n"])
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, io.BytesIO(b'{"error": "not found"}'))
