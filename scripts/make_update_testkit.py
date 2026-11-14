"""Build a kit to TEST SYNOX's self-update (Update.bat) before any real release exists.

    python scripts/make_update_testkit.py [--out <folder outside the repo>] [--version 0.2.1-test.1] [--no-sign]

Writes (default: a new folder in the system temp dir; never inside the repository, and the repository is not touched):

  old/SYNOX-<current>.zip      the current tree as a release ZIP (install this first: the "old" SYNOX)
  new/SYNOX-<test>.zip         the same files with the version changed to <test> (default: next patch + "-test.1",
                               e.g. 0.2.0 -> 0.2.1-test.1; a pre-release, so any real 0.2.1 is still newer)
  new/SHA256SUMS.txt           like a real release
  new/release.json(.sig)       like `scripts/release.py sign`, signed with a THROWAWAY key made here (--no-sign: none)
  test-key/                    that throwaway private key (only for this test; delete it afterwards)
  releases.json                a fake "GitHub release" whose assets are file:// URLs of new/ -- for SYNOX_UPDATE_API
  README.md                    short steps (Chinese) for trying it on Windows: install old -> Update.bat -FromZip ->
                               check version + config/data/packs kept -> Update.bat -Rollback

The version is changed only inside the ZIP (src/synox/__init__.py and pyproject.toml are rewritten while zipping).
The ZIPs carry exactly what scripts/make_zip.py ships (the files git tracks, minus INTERNAL); --tools is passed
through. Build it on the Windows machine you test on: releases.json holds absolute file:// paths of this folder.
What the update path checks, and the release steps for real: docs/release-playbook.md.
Standard library + `cryptography` (already a SYNOX dependency; without it the kit is unsigned). No network.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import make_zip  # noqa: E402
import release  # noqa: E402

TEST_KEY_ENV = "SYNOX_UPDATE_TEST_PUBKEY"
TEST_API_ENV = "SYNOX_UPDATE_API"
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")


def current_version() -> str:
    return release.versions_in(ROOT)["src/synox/__init__.py"] or ""


def default_test_version(current: str) -> str:
    m = SEMVER_RE.match(current)
    if m is None:
        raise ValueError(f"current version {current!r} is not semver")
    return f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}-test.1"


def newer(a: str, b: str) -> bool:
    """b newer than a (same rules SYNOX uses)."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from synox.packs.upgrade import semver_key
    ka, kb = semver_key(a), semver_key(b)
    return ka is not None and kb is not None and kb > ka


def _inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def build_zip(target: str, files: list, version: str = "") -> None:
    """Release ZIP (SYNOX/<rel>) of `files`; with version: the copies of the version files inside say <version>."""
    rewrite = {rel: rx for rel, rx in release.VERSION_FILES} if version else {}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for src, rel in files:
            if rel in rewrite:
                with open(src, "r", encoding="utf-8", newline="") as f:
                    text = f.read()
                z.writestr("SYNOX/" + rel, release.set_version(text, rewrite[rel], version).encode("utf-8"))
            else:
                z.write(src, "SYNOX/" + rel)


def _sha256(path: str):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest(), os.path.getsize(path)


def sign_files(new_dir: str, zip_name: str, version: str, key_dir: str = "", sign: bool = True) -> str:
    """SHA256SUMS.txt + release.json (+ .sig with a throwaway key written to key_dir). Returns the public key ("" when
    unsigned)."""
    sha, size = _sha256(os.path.join(new_dir, zip_name))
    with open(os.path.join(new_dir, "SHA256SUMS.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{sha}  {zip_name}\n")
    manifest = {"version": version, "date": _dt.date.today().isoformat(), "severity": "normal",
                "summary": "測試更新用的假新版（make_update_testkit.py）", "notes_url": "",
                "assets": {zip_name: {"sha256": sha, "size": size}}, "rebuild_venv": False, "min_from": None}
    blob = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with open(os.path.join(new_dir, "release.json"), "wb") as f:
        f.write(blob)
    if not sign:
        return ""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("[!] `cryptography` is not installed: the kit is unsigned (release.json without .sig)")
        return ""
    key = Ed25519PrivateKey.generate()
    os.makedirs(key_dir, exist_ok=True)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(os.path.join(key_dir, "throwaway-test-key.pem"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    sig = base64.b64encode(key.sign(blob)).decode("ascii") + "\n"
    with open(os.path.join(new_dir, "release.json.sig"), "w", encoding="ascii", newline="\n") as f:
        f.write(sig)
    pub = release.public_key_b64(key)
    with open(os.path.join(key_dir, "public-key.txt"), "w", encoding="ascii", newline="\n") as f:
        f.write(pub + "\n")
    return pub


def fake_releases(new_dir: str, version: str) -> dict:
    """What GitHub's releases/latest would answer, but every asset is a file:// URL of new_dir (SYNOX_UPDATE_API)."""
    assets = []
    for name in sorted(os.listdir(new_dir)):
        path = os.path.join(new_dir, name)
        sha, size = _sha256(path)
        assets.append({"name": name, "browser_download_url": pathlib.Path(path).resolve().as_uri(), "size": size,
                       "digest": "sha256:" + sha})
    return {"tag_name": "v" + version, "name": f"SYNOX {version}（測試包，不是真的發佈）",
            "body": "### 這版改了什麼\n\n- 測試更新用的假新版（不是真的發佈，只有版本號不一樣）\n",
            "prerelease": True, "draft": False, "published_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "html_url": "", "assets": assets}


README = """# SYNOX 更新測試包：{cur} → {test}

`scripts/make_update_testkit.py` 做的，**只給測試 Update.bat 用，不是真的發佈**。不會動到 SYNOX 的 repo。
完整說明：docs/release-playbook.md「先測更新」。

## 裡面有什麼

- `old\\SYNOX-{cur}.zip`：現在的版本（當「舊版」先裝起來）
- `new\\SYNOX-{test}.zip`：同一份程式，只把版本改成 {test}（假的新版）
- `new\\SHA256SUMS.txt`、`new\\release.json`{sig_files}：跟真的發佈一樣的檢查檔
- `releases.json`：假的「GitHub 發佈資訊」（第 7 步用）
{key_line}
## 步驟（Windows，命令提示字元）

1. 把 `old\\SYNOX-{cur}.zip` 解壓到新的資料夾，例如 `C:\\SYNOX-test\\`（**不要用你平常在用的 SYNOX**）。
2. 點兩下 `C:\\SYNOX-test\\SYNOX\\Setup.bat` 裝好、開起來，隨便做點事（記一筆筆記、裝一個工具、改個設定），
   再點 `Stop.bat`。記下 `config.json`、`data\\`、`packs\\` 裡有什麼。
3. 更新（沒有簽章的路，要明確加 -AllowUnsigned）：

       cd /d C:\\SYNOX-test\\SYNOX
       Update.bat -FromZip "{new_zip}" -AllowUnsigned

   應該看到「⚠️ 用這台電腦上的 ZIP 更新」「✅ 檔案跟旁邊的 SHA256SUMS.txt 一樣」，問你要不要從 {cur} 換成 {test}，輸入 Y。
4. 檢查：

       .venv\\Scripts\\python.exe -m synox about

   版本要是 **{test}**；`config.json`、`data\\`、`packs\\` 都跟第 2 步一樣；`_previous\\{cur}-<時間>\\` 是舊版。
   SYNOX 會自己開回來，網頁的資料、工具都在。
5. 退回：`Update.bat -Rollback` → 輸入 Y → 再跑一次第 4 步的指令，版本要回到 **{cur}**，資料都還在。
{sign_step}
7. （選做）走正式的那條路（查新版 → 下載 → 驗證 → 換檔），只是「GitHub」換成這台電腦上的檔案。先確定現在是 {cur}
   （不是的話先 `Update.bat -Rollback`）：

       set {api_env}={releases}
{key_set}       Update.bat{allow}

   每一段最上面都會印「⚠️⚠️ 測試模式」。測完**關掉這個命令提示字元視窗**（設的環境變數就不見了）。
8. （選做）壞掉的情況：把 `new\\SHA256SUMS.txt` 改掉一個字，再做第 3 步 → 要被拒絕，而且什麼都沒換。

用完：刪掉 `C:\\SYNOX-test\\` 和這個資料夾{key_rm}。有問題：`C:\\SYNOX-test\\SYNOX\\data\\logs\\update.log`。
"""

SIGN_STEP = """6. （選做）簽章那條路（不用 -AllowUnsigned）：

       set {key_env}={pub}
       Update.bat -FromZip "{new_zip}"

   應該看到「⚠️⚠️ 測試模式：也信任 {key_env}…」和「✅ 簽章驗過了」。測完 `Update.bat -Rollback` 回到 {cur}。
   這把是只給這次測試的拋棄式金鑰：真的 SYNOX 從來不信任它（只有你自己在這個視窗設了環境變數才算）。
"""


def write_readme(out: str, cur: str, test: str, pub: str) -> str:
    new_zip = os.path.join(out, "new", f"SYNOX-{test}.zip")
    text = README.format(
        cur=cur, test=test, new_zip=new_zip, releases=os.path.join(out, "releases.json"), api_env=TEST_API_ENV,
        sig_files="、`new\\release.json.sig`（用拋棄式測試金鑰簽的）" if pub else "（沒有簽章）",
        key_line=f"- `test-key\\`：拋棄式測試金鑰（公鑰：`{pub}`），測完刪掉\n" if pub else "",
        sign_step=SIGN_STEP.format(key_env=TEST_KEY_ENV, pub=pub, new_zip=new_zip, cur=cur) if pub else "",
        key_set=f"       set {TEST_KEY_ENV}={pub}\n" if pub else "",
        allow="" if pub else " -AllowUnsigned",
        key_rm="（含 `test-key\\`）" if pub else "")
    path = os.path.join(out, "README.md")
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    return path


def build(out: str, version: str = "", sign: bool = True, tools: str = "") -> dict:
    cur = current_version()
    test = version or default_test_version(cur)
    if not SEMVER_RE.match(test) or not newer(cur, test):
        raise ValueError(f"--version {test!r} must be semver and newer than the current {cur}")
    if _inside(out, ROOT):
        raise ValueError("--out must be outside the repository (the repository is never touched)")
    if os.path.exists(out) and os.listdir(out):
        raise ValueError(f"{out} is not empty")
    files = make_zip.release_files(tools)
    old_dir, new_dir = os.path.join(out, "old"), os.path.join(out, "new")
    os.makedirs(old_dir)
    os.makedirs(new_dir)
    old_zip = os.path.join(old_dir, f"SYNOX-{cur}.zip")
    new_zip = os.path.join(new_dir, f"SYNOX-{test}.zip")
    build_zip(old_zip, files)
    build_zip(new_zip, files, test)
    pub = sign_files(new_dir, os.path.basename(new_zip), test, key_dir=os.path.join(out, "test-key"), sign=sign)
    with open(os.path.join(out, "releases.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(fake_releases(new_dir, test), f, ensure_ascii=False, indent=2)
    readme = write_readme(out, cur, test, pub)
    return {"out": out, "current": cur, "test": test, "old_zip": old_zip, "new_zip": new_zip, "public_key": pub,
            "readme": readme, "files": len(files)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="", help="empty folder outside the repo (default: a new folder in temp)")
    parser.add_argument("--version", default="", help="version of the fake new release (default: next patch + -test.1)")
    parser.add_argument("--no-sign", action="store_true", help="no throwaway key, no release.json.sig")
    parser.add_argument("--tools", default="", help="built tool library to include (like make_zip.py --tools)")
    args = parser.parse_args(argv)
    out = os.path.abspath(args.out) if args.out else \
        tempfile.mkdtemp(prefix="synox-update-testkit-" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-")
    try:
        kit = build(out, args.version, sign=not args.no_sign, tools=args.tools)
    except ValueError as e:
        print(f"[X] {e}")
        return 2
    print(f"update test kit: {kit['current']} -> {kit['test']} ({kit['files']} files)")
    print(f"  old : {kit['old_zip']}")
    print(f"  new : {kit['new_zip']}")
    if kit["public_key"]:
        print(f"  throwaway public key ({TEST_KEY_ENV}): {kit['public_key']}")
    print(f"  steps: {kit['readme']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
