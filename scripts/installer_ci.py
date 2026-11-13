"""Small, testable helpers for the installer build workflow (.github/workflows/build-installer.yml, docs/release-build.md).

    <python> scripts/installer_ci.py version [--tag v0.2.0]           print the version (pyproject == synox.__version__;
                                                                       with --tag also == the tag without "v")
    <python> scripts/installer_ci.py fetch URL --sha256 HEX --out FILE download, then keep the file only if its sha256
                                                                       matches the pinned value (https:// or file:// only)
    <python> scripts/installer_ci.py extract ZIP --out DIR             unzip, refusing absolute paths and ".." entries
    <python> scripts/installer_ci.py check-iss                         static checks of setup/installer/synox.iss and its
                                                                       lang/*.isl texts (pages, languages, keys); needs
                                                                       no Inno Setup, runs anywhere

Standard library only. It never runs anything it downloads or extracts. Exit code: 0 ok, 1 check failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
INIT_VERSION = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)
USER_AGENT = "synox-installer-build"


class CheckError(ValueError):
    pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def project_version(root: str = ROOT) -> str:
    """pyproject.toml [project].version; CheckError when src/synox/__init__.py says something else."""
    with open(os.path.join(root, "pyproject.toml"), "rb") as f:
        version = tomllib.load(f)["project"]["version"]
    with open(os.path.join(root, "src", "synox", "__init__.py"), "r", encoding="utf-8") as f:
        m = INIT_VERSION.search(f.read())
    if not m:
        raise CheckError("src/synox/__init__.py has no __version__")
    if m.group(1) != version:
        raise CheckError(f"pyproject.toml says {version} but synox.__version__ is {m.group(1)}")
    return version


def check_tag(version: str, tag: str) -> None:
    if tag and tag != f"v{version}":
        raise CheckError(f"tag {tag} does not match the project version {version} (expected v{version})")


def fetch(url: str, expected: str, out: str) -> str:
    """Download url to out and verify its sha256. The file only appears at out when the hash matches."""
    expected = expected.strip().lower()
    if not HEX64.match(expected):
        raise CheckError(f"pinned sha256 is not 64 hex characters: {expected!r}")
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("https", "file"):
        raise CheckError(f"only https:// (or file:// for tests) is allowed, not {scheme or 'a bare path'}")
    folder = os.path.dirname(os.path.abspath(out))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with os.fdopen(fd, "wb") as f, urllib.request.urlopen(req, timeout=300) as resp:
            shutil.copyfileobj(resp, f)
        actual = sha256_file(tmp)
        if actual != expected:
            raise CheckError(f"sha256 mismatch for {url}: expected {expected}, got {actual}")
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def safe_extract(zip_path: str, out: str) -> list:
    """Extract every entry under out; CheckError (and nothing written) on absolute paths, drive letters or '..'."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        for name in names:
            parts = name.replace("\\", "/").split("/")
            if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or ".." in parts:
                raise CheckError(f"unsafe path in {os.path.basename(zip_path)}: {name}")
        os.makedirs(out, exist_ok=True)
        z.extractall(out)
    return names


# ---- static checks of the Inno Setup script (no Windows / ISCC needed) ------------------------------------------------

INSTALLER_DIR = os.path.join(ROOT, "setup", "installer")
# Same order and codes as synox.wizard.i18n.LANGS (tests/test_installer_script.py keeps them equal).
INSTALLER_LANGS = ("zh-TW", "zh-CN", "en", "es", "fr", "de", "pt-BR", "ru", "ar", "hi", "ja", "ko")
# Inno Setup 6 language files: the official ones ship in <Inno>\Languages; the others are unofficial (lang\inno\ if added).
INNO_OFFICIAL = {"es": "Spanish", "fr": "French", "de": "German", "pt-BR": "BrazilianPortuguese", "ru": "Russian",
                 "ar": "Arabic", "ja": "Japanese", "ko": "Korean"}
INNO_UNOFFICIAL = {"zh-TW": "ChineseTraditional.isl", "zh-CN": "ChineseSimplified.isl", "hi": "Hindi.islu"}
# What the owner's decisions (docs/installer/spec.html section 8) need from [Setup].
REQUIRED_DIRECTIVES = {"PrivilegesRequired": "lowest", "DisableWelcomePage": "no", "DisableReadyPage": "yes",
                       "ShowLanguageDialog": "yes", "LanguageDetectionMethod": "uilanguage", "UsePreviousTasks": "no",
                       "DefaultDirName": "{localappdata}\\Programs\\SYNOX"}
FORBIDDEN_DIRECTIVES = ("LicenseFile", "PrivilegesRequiredOverridesAllowed", "InfoBeforeFile")
REQUIRED_TASKS = {"desktopicon": True, "startmenu": True, "fileassoc": True, "autostart": True, "claudecode": True,
                  "alltools": False}       # name -> checked by default
KEPT_ON_UNINSTALL = ("config.json", "data", "packs")
PLACEHOLDER = re.compile(r'%\d|%n|<a id="\w+">|</a>')


def iss_sections(text: str) -> dict:
    """{section: [lines]} of an .iss/.isl file: comments and preprocessor lines dropped, [Code] kept verbatim."""
    out, name = {}, ""
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^\[(\w+)\]$", line)
        if m:
            name = m.group(1)
            out.setdefault(name, [])
        elif name == "Code":
            out[name].append(raw)
        elif name and line and not line.startswith((";", "#")):
            out[name].append(line)
    return out


def iss_entries(lines: list) -> list:
    """Lines like `Name: "x"; Description: "{cm:Y}"; Flags: unchecked` -> [{"Name": "x", ...}, ...]."""
    entries = []
    for line in lines:
        entry = {}
        for m in re.finditer(r'(\w+):\s*("(?:[^"]|"")*"|[^;]*)', line):
            value = m.group(2).strip()
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('""', '"')
            entry[m.group(1)] = value
        entries.append(entry)
    return entries


def read_isl(path: str) -> dict:
    """{section: {key: value}} of one of our lang/*.isl files (UTF-8 with BOM)."""
    with open(path, "rb") as f:
        raw = f.read()
    name = os.path.basename(path)
    if not raw.startswith(b"\xef\xbb\xbf"):
        raise CheckError(f"{name}: needs a UTF-8 BOM (Inno Setup then reads it as UTF-8)")
    out = {}
    for section, lines in iss_sections(raw[3:].decode("utf-8")).items():
        table = out.setdefault(section, {})
        for line in lines:
            key, sep, value = line.partition("=")
            if not sep:
                raise CheckError(f"{name} [{section}]: no '=' in {line!r}")
            if key.strip() in table:
                raise CheckError(f"{name} [{section}]: {key.strip()} appears twice")
            table[key.strip()] = value
    return out


def _check_languages(text: str, sections: dict) -> list:
    problems = []
    langs = iss_entries(sections.get("Languages", []))
    if len(langs) != len(INSTALLER_LANGS):
        problems.append(f"[Languages] has {len(langs)} entries, expected {len(INSTALLER_LANGS)}")
    if [e.get("Name") for e in langs[:1]] != ["en"]:
        problems.append("[Languages] English must come first (used when the Windows language matches none)")
    defines = dict(re.findall(r'#define\s+(\w+)\s+"([^"]*)"', text))
    seen = set()
    for entry in langs:
        files = [f.strip() for f in entry.get("MessagesFile", "").split(",")]
        last = files[-1]
        code = last[len("lang\\"):-len(".isl")] if last.startswith("lang\\") and last.endswith(".isl") else ""
        if code not in INSTALLER_LANGS:
            problems.append(f"[Languages] {entry.get('Name')}: the last file must be lang\\<code>.isl, not {last}")
            continue
        seen.add(code)
        if code != "en" and (len(files) < 3 or files[-2] != "lang\\en.isl"):
            problems.append(f"[Languages] {code}: lang\\en.isl must come right before lang\\{code}.isl (English fallback)")
        m = re.match(r"^\{#(\w+)\}$", files[0])
        base = defines.get(m.group(1), "") if m else files[0]
        if code in INNO_OFFICIAL and base != f"compiler:Languages\\{INNO_OFFICIAL[code]}.isl":
            problems.append(f"[Languages] {code}: use the official compiler:Languages\\{INNO_OFFICIAL[code]}.isl")
        if code in INNO_UNOFFICIAL and (base != "compiler:Default.isl" or INNO_UNOFFICIAL[code] not in text):
            problems.append(f"[Languages] {code}: English base plus the optional lang\\inno\\{INNO_UNOFFICIAL[code]}")
        if code == "en" and base != "compiler:Default.isl":
            problems.append("[Languages] en: the base must be compiler:Default.isl")
    if seen != set(INSTALLER_LANGS):
        problems.append(f"[Languages] missing: {sorted(set(INSTALLER_LANGS) - seen)}")
    return problems


def _check_texts(folder: str, text: str) -> list:
    problems = []
    try:
        en = read_isl(os.path.join(folder, "lang", "en.isl"))
    except (OSError, CheckError) as e:
        return [str(e)]
    if "LangOptions" in en:
        problems.append("lang/en.isl must not have [LangOptions] (it is loaded for every language)")
    for code in INSTALLER_LANGS:
        try:
            table = read_isl(os.path.join(folder, "lang", code + ".isl"))
        except (OSError, CheckError) as e:
            problems.append(str(e))
            continue
        for section in ("Messages", "CustomMessages"):
            mine, base = table.get(section, {}), en.get(section, {})
            if set(mine) != set(base):
                problems.append(f"lang/{code}.isl [{section}]: missing {sorted(set(base) - set(mine))}, "
                                f"extra {sorted(set(mine) - set(base))}")
            for key in sorted(set(mine) & set(base)):
                if not mine[key].strip():
                    problems.append(f"lang/{code}.isl: {key} is empty")
                elif sorted(PLACEHOLDER.findall(mine[key])) != sorted(PLACEHOLDER.findall(base[key])):
                    problems.append(f"lang/{code}.isl: {key} has other placeholders or links than English")
        for key in ("IconWizard", "IconUninstall"):                     # these become Start menu file names
            if re.search(r'[\\/:*?"<>|]', table.get("CustomMessages", {}).get(key, "")):
                problems.append(f"lang/{code}.isl: {key} has a character Windows file names cannot have")
        if table.get("CustomMessages", {}).get("SynoxLangCode") != code:
            problems.append(f"lang/{code}.isl: SynoxLangCode must be {code}")
        if code != "en":
            options = table.get("LangOptions", {})
            if not re.search(r"\(.+\)$", options.get("LanguageName", "")):
                problems.append(f"lang/{code}.isl: LanguageName should read 'native (Latin)'")
            if code in INNO_UNOFFICIAL and "LanguageID" not in options:
                problems.append(f"lang/{code}.isl: needs LanguageID so the Windows language preselects it")
    used = set(re.findall(r"\{cm:(\w+)\}", text)) | set(re.findall(r"CustomMessage\('(\w+)'\)", text))
    missing = sorted(used - set(en.get("CustomMessages", {})))
    if missing:
        problems.append(f"synox.iss uses custom messages that lang/en.isl does not define: {missing}")
    return problems


def check_iss(folder: str = INSTALLER_DIR) -> list:
    """Every problem found in synox.iss and lang/*.isl as a plain sentence; [] = all good. Static only: whether
    Inno Setup compiles it and how the pages look is checked by the build workflow (ISCC) and on Windows."""
    with open(os.path.join(folder, "synox.iss"), "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return ["synox.iss must stay ASCII (translations go in lang/*.isl)"]
    sections = iss_sections(text)
    problems = []
    setup = {}
    for line in sections.get("Setup", []):
        key, _, value = line.partition("=")
        setup[key.strip()] = value.strip()
    for key, want in REQUIRED_DIRECTIVES.items():
        if setup.get(key) != want:
            problems.append(f"[Setup] {key} should be {want} (now {setup.get(key)!r})")
    for key in FORBIDDEN_DIRECTIVES:
        if key in setup:
            problems.append(f"[Setup] {key} must not be set (no license, admin or info page: owner Q4)")
    problems += _check_languages(text, sections)
    problems += _check_texts(folder, text)

    tasks = {e.get("Name"): "unchecked" not in e.get("Flags", "") for e in iss_entries(sections.get("Tasks", []))}
    if tasks != REQUIRED_TASKS:
        problems.append(f"[Tasks] should be {REQUIRED_TASKS} (name: checked by default), got {tasks}")
    code = "\n".join(sections.get("Code", []))
    want = ",".join(n if on else "!" + n for n, on in REQUIRED_TASKS.items())
    m = re.search(r"RecommendedTasks\s*=\s*'([^']*)'", code)
    if not m or m.group(1) != want:
        problems.append(f"[Code] RecommendedTasks should be '{want}' (same as the Custom defaults)")
    for needle, why in (("CreateInputOptionPage(wpWelcome", "the Recommended | Custom page after the welcome page"),
                        ("function ShouldSkipPage", "Recommended skips the folder and task pages"),
                        ("TNewLinkLabel", "the license line on the welcome page"),
                        ("function InitializeUninstall", "uninstall asks before deleting data"),
                        ("UninstallConfirmData", "a second confirmation before deleting data"),
                        ("claude-code.ps1", "the optional Claude Code step"),
                        ("installer-choices.json", "telling the setup wizard what was decided"),
                        ("lang.txt", "the language for the setup wizard and SYNOX")):
        if needle not in code:
            problems.append(f"[Code] has no {needle} ({why})")
    for entry in iss_entries(sections.get("UninstallDelete", [])):
        target = entry.get("Name", "").replace("{app}\\", "")
        if target in KEPT_ON_UNINSTALL:
            problems.append(f"[UninstallDelete] must not delete {target} (kept unless the user asks)")
    run = "\n".join(sections.get("Run", []))
    if "Setup.bat" not in run or "-Lang {cm:SynoxLangCode}" not in run:
        problems.append("[Run] must run Setup.bat -Lang {cm:SynoxLangCode} (the language goes on to the wizard)")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("version", help="print the project version (checks pyproject == synox.__version__)")
    p.add_argument("--tag", default="", help="a release tag such as v0.2.0; must match the version")
    p = sub.add_parser("fetch", help="download a file and verify its pinned sha256")
    p.add_argument("url")
    p.add_argument("--sha256", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("extract", help="unzip without allowing paths outside the target folder")
    p.add_argument("zip")
    p.add_argument("--out", required=True)
    sub.add_parser("check-iss", help="static checks of setup/installer/synox.iss and its lang/*.isl texts")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "version":
            version = project_version()
            check_tag(version, args.tag)
            print(version)
        elif args.cmd == "check-iss":
            problems = check_iss()
            for problem in problems:
                print(f"[X] {problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"ok  synox.iss: {len(INSTALLER_LANGS)} languages; pages, tasks and texts complete")
        elif args.cmd == "fetch":
            fetch(args.url, args.sha256, args.out)
            print(f"ok  sha256 {args.sha256.lower()}  {os.path.basename(args.out)}")
        else:
            names = safe_extract(args.zip, args.out)
            print(f"extracted {len(names)} entries from {os.path.basename(args.zip)}")
    except (CheckError, OSError, zipfile.BadZipFile) as e:
        print(f"[X] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
