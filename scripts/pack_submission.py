"""Package a reviewed allowlist without local credentials or runtime state."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = [f"evidence/{name}.png" for name in (
    "01-feishu-top", "02-feishu-bottom", "03-news-link")]


def selected_files():
    names = {"README.md", "FINAL_SUBMISSION.md", "workflow.md", "requirements.txt",
             ".gitignore", ".env.example", "evidence/README.md"}
    for directory, suffixes in (
        ("stockflow", {".py"}), ("tests", {".py"}), ("scripts", {".py"}),
        (".github/workflows", {".yml", ".yaml"}), ("docs", {".svg"}),
        ("evidence/verified-run", {".json", ".md"}),
    ):
        names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / directory).iterdir()
                     if p.is_file() and p.suffix in suffixes)
    names.update(name for name in SCREENSHOTS if (ROOT / name).is_file())
    return sorted(names)


def local_credentials():
    path = ROOT / ".env"
    if not path.is_file():
        return []
    values = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in {"FEISHU_WEBHOOK", "FEISHU_SECRET"}:
            value = value.strip().strip("\"'")
            if value:
                values.append(value.encode("utf-8"))
    return values


def main():
    credentials = local_credentials()
    entries = []
    blobs = {}
    for name in selected_files():
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"Unexpected path: {name}")
        data = path.read_bytes()
        if any(value in data for value in credentials):
            raise ValueError(f"Credential detected; packaging stopped: {name}")
        if re.search(rb"https://open\.feishu\.cn/open-apis/bot/v2/hook/[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", data):
            raise ValueError(f"Webhook detected; packaging stopped: {name}")
        blobs[name] = data
        entries.append({"path": name, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    template = blobs[".env.example"].decode("utf-8-sig")
    for key in ("FEISHU_WEBHOOK", "FEISHU_SECRET"):
        if not re.search(rf"^{key}=\s*$", template, re.MULTILINE):
            raise ValueError("Template must contain blank credentials")
    report = json.loads(blobs["evidence/verified-run/report.json"])
    receipt = json.loads(blobs["evidence/verified-run/receipt.json"])
    if not (report["run_id"] == receipt["run_id"] and receipt["status"] == "sent"
            and receipt["receipt"]["code"] == 0):
        raise ValueError("Verified-run report and success receipt do not match")
    destination = ROOT / "submission"
    destination.mkdir(exist_ok=True)
    archive = destination / "ai-agent-stock-workflow-submission.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in blobs.items():
            output.writestr(f"{ROOT.name}/{name}", data)
    present = [name for name in SCREENSHOTS if name in blobs]
    manifest = {"archive": archive.name, "files": entries,
                "real_push_run_id": report["run_id"], "screenshots": present,
                "github_actions_run_verified": False}
    (destination / "SUBMISSION_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Archive: {archive}")
    print(f"Files: {len(entries)}; credential check: passed")
    if SCREENSHOTS[0] not in present or SCREENSHOTS[1] not in present:
        print("Pending: add actual Feishu screenshots, then run packaging again.")
    print("Pending: configure GitHub Secrets and verify Actions delivery/scheduled run.")


if __name__ == "__main__":
    main()
