"""dish_present 태깅 로컬 도구 (addendum 2026-09-10 §3) — MacBook 안에서만 도는 FastAPI.

왜 로컬 서버인가: train 썸네일 576장(2880×1620, ~350 KB)은 아티팩트 16 MB 한도에 못 들어가고, 픽셀을 밖으로 내보낼 이유도 없다.
127.0.0.1 에 묶고, role manifest 에 있는 train/val 슬롯의 thumbnail.jpg 만 서빙한다(holdout → 403, 모르는 ref → 404).
태그는 attempt/dish/entries/<slot digest>-<utc ms>.json 으로 O_EXCL append-only(수정 = 새 엔트리, 최신 우선), 끝나면
`compile_dish_tags` 가 dish-tags-v1 원장(0600, 재작성 불가)을 만든다. production DB/R2 write 0.

실행:  uv run python -m scripts.yolo26n_v27_c500g.dish_tag_server serve --attempt <attempt> --mirror storage/rap-c500g-mirror \\
           --test-sheet-sha256 <sha> [--port 8765]
컴파일: uv run python -m scripts.yolo26n_v27_c500g.dish_tag_server compile --attempt <attempt> --test-sheet-sha256 <sha>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, StrictBool, field_validator

from scripts.yolo26n_v27_c500g.contracts import WRITE_COUNT_FIELDS, Role
from scripts.yolo26n_v27_c500g.private_io import write_private_json_new
from scripts.yolo26n_v27_c500g.roi import ROI_NAMES

DISH_TAGS_SCHEMA = "yolo26n-v27-c500g-dish-tags-v1"
DISH_TAG_VERSION = 1
TAGGABLE_ROLES = frozenset({Role.V27_TRAIN, Role.V27_VAL})
_ZERO_WRITES = {field: 0 for field in WRITE_COUNT_FIELDS}


class TagBody(BaseModel):
    source_ref: str
    tags: dict[str, StrictBool | None]

    @field_validator("tags")
    @classmethod
    def _exactly_three_rois(cls, value: dict[str, StrictBool | None]) -> dict[str, StrictBool | None]:
        if set(value) != set(ROI_NAMES):
            raise ValueError(f"tags must have exactly {ROI_NAMES}")
        return value


def _load_taggable_slots(roles_path: Path) -> dict[str, dict[str, object]]:
    roles = json.loads(Path(roles_path).read_text(encoding="utf-8"))
    slots: dict[str, dict[str, object]] = {}
    for row in roles["rows"]:
        role = Role(str(row["role"]))
        if role not in TAGGABLE_ROLES:
            continue
        ref = str(row["source_ref"])
        parts = ref.split("/")
        slots[ref] = {
            "source_ref": ref, "role": role.value, "camera_key": parts[1] if len(parts) > 1 else "",
            "night_date": str(row.get("night_date") or (parts[2].removeprefix("night=") if len(parts) > 2 else "")),
            "slot": parts[-1],
        }
    return dict(sorted(slots.items()))


def _latest_entries(ledger_dir: Path) -> dict[str, dict[str, object]]:
    """entries/*.json 을 파일명(utc ms) 순으로 읽어 source_ref 별 최신 엔트리."""
    latest: dict[str, dict[str, object]] = {}
    entries_dir = Path(ledger_dir) / "entries"
    if not entries_dir.is_dir():
        return latest
    for path in sorted(entries_dir.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        latest[str(entry["source_ref"])] = entry
    return latest


def create_app(*, roles_path: Path, mirror_root: Path, ledger_dir: Path, test_sheet_sha256: str, tagger: str = "owner") -> FastAPI:
    slots = _load_taggable_slots(Path(roles_path))
    mirror = Path(mirror_root)
    ledger = Path(ledger_dir)
    app = FastAPI(title="C500G dish_present tagging", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE_HTML

    @app.get("/api/slots")
    def api_slots() -> JSONResponse:
        latest = _latest_entries(ledger)
        rows = []
        for ref, slot in slots.items():
            entry = latest.get(ref)
            rows.append({**slot, "tags": entry["roi_tags"] if entry else None})
        tagged = sum(1 for r in rows if r["tags"] is not None)
        return JSONResponse({"slots": rows, "total": len(rows), "tagged": tagged, "test_sheet_sha256": test_sheet_sha256})

    @app.get("/api/thumb")
    def api_thumb(ref: str) -> FileResponse:
        slot = slots.get(ref)
        if slot is None:
            # holdout 은 manifest 에 있지만 taggable 이 아니므로 403 으로 구분한다.
            raise HTTPException(status_code=403 if _is_protected(ref, roles_path) else 404, detail="not a taggable slot")
        path = mirror / ref / "thumbnail.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="thumbnail missing in mirror")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/tag")
    def api_tag(body: TagBody) -> JSONResponse:
        if body.source_ref not in slots:
            raise HTTPException(status_code=403 if _is_protected(body.source_ref, roles_path) else 404, detail="not a taggable slot")
        now = datetime.now(UTC)
        entry = {
            "source_ref": body.source_ref, "roi_tags": {name: body.tags[name] for name in ROI_NAMES}, "tagger": tagger,
            "tagged_at": now.isoformat().replace("+00:00", "Z"), "dish_tag_version": DISH_TAG_VERSION,
            "test_sheet_sha256": test_sheet_sha256,
        }
        digest = hashlib.sha256(body.source_ref.encode("utf-8")).hexdigest()[:16]
        write_private_json_new(ledger / "entries" / f"{digest}-{int(now.timestamp() * 1000):013d}.json", entry)
        return JSONResponse({"ok": True, "tags": entry["roi_tags"], "tagged_at": entry["tagged_at"]})

    return app


def _is_protected(ref: str, roles_path: Path) -> bool:
    roles = json.loads(Path(roles_path).read_text(encoding="utf-8"))
    return any(str(row["source_ref"]) == ref for row in roles["rows"])


def compile_dish_tags(ledger_dir: Path, out_path: Path, *, test_sheet_sha256: str) -> dict[str, object]:
    """entries → dish-tags-v1 원장 (source_ref × roi_name 한 줄, 최신 엔트리 기준). 이미 있으면 FileExistsError."""
    latest = _latest_entries(Path(ledger_dir))
    entries: list[dict[str, object]] = []
    counts = {"food_in_dish_true": 0, "food_in_dish_false": 0, "unclear": 0}
    for ref in sorted(latest):
        entry = latest[ref]
        for name in ROI_NAMES:
            value = entry["roi_tags"][name]  # type: ignore[index]
            entries.append({"source_ref": ref, "roi_name": name, "food_in_dish": value, "tagger": entry["tagger"], "tagged_at": entry["tagged_at"]})
            counts["food_in_dish_true" if value is True else "food_in_dish_false" if value is False else "unclear"] += 1
    ledger = {
        "schema": DISH_TAGS_SCHEMA, "status": "DISH_TAGS_READY", "test_sheet_sha256": test_sheet_sha256,
        "dish_tag_version": DISH_TAG_VERSION, "entries": entries, "summary": {"slots_tagged": len(latest), **counts}, **_ZERO_WRITES,
    }
    write_private_json_new(Path(out_path), ledger)
    return ledger


PAGE_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>C500G dish_present 태깅</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#0f1317; --panel:#161c22; --line:#2a343e; --text:#e4e9ee; --muted:#8b97a3; --ok:#7ad3a1; --warn:#f0b35a; --acc:#5ad0ff; }
  body { margin:0; background:var(--bg); color:var(--text); font:14px/1.5 "IBM Plex Sans KR","Apple SD Gothic Neo",system-ui,sans-serif; }
  header { display:flex; gap:16px; align-items:center; padding:10px 16px; border-bottom:1px solid var(--line); background:var(--panel); position:sticky; top:0; }
  header h1 { font-size:15px; margin:0; } .muted { color:var(--muted); font-size:12px; }
  main { display:grid; grid-template-columns: 220px minmax(0,1fr); gap:12px; padding:12px 16px; }
  nav { max-height: calc(100vh - 80px); overflow:auto; border:1px solid var(--line); border-radius:6px; background:var(--panel); }
  nav button { display:block; width:100%; text-align:left; background:transparent; color:var(--muted); border:0; border-bottom:1px solid var(--line); padding:6px 10px; font:inherit; cursor:pointer; }
  nav button.cur { color:var(--text); background:#1d252d; } nav button.done { color:var(--ok); }
  .stage img { width:100%; height:auto; display:block; border:1px solid var(--line); border-radius:4px; background:#000; }
  .enc { display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; margin-top:10px; }
  .enc div { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px; }
  .enc h3 { margin:0 0 6px; font-size:13px; }
  .enc button { font:inherit; padding:6px 10px; margin-right:6px; border-radius:4px; border:1px solid var(--line); background:transparent; color:var(--muted); cursor:pointer; }
  .enc button.on { background:var(--acc); color:#08131a; border-color:var(--acc); }
  .bar { display:flex; gap:10px; align-items:center; margin-top:10px; flex-wrap:wrap; }
  .primary { background:var(--acc); color:#08131a; border:0; border-radius:6px; padding:8px 16px; font:inherit; font-weight:600; cursor:pointer; }
  .ghost { background:transparent; color:var(--text); border:1px solid var(--line); border-radius:6px; padding:8px 12px; font:inherit; cursor:pointer; }
  kbd { border:1px solid var(--line); border-radius:3px; padding:0 5px; font-size:11px; color:var(--muted); }
</style></head><body>
<header><h1>C500G dish_present 태깅</h1><span class="muted" id="prog">불러오는 중…</span>
<span class="muted">키: <kbd>A</kbd> 셋 다 없음+저장 · <kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> 왼/가운데/오른 있음 토글 · <kbd>Enter</kbd> 저장·다음 · <kbd>←</kbd><kbd>→</kbd> 이동 · <kbd>N</kbd> 다음 미태깅</span></header>
<main>
  <nav id="list"></nav>
  <section>
    <div class="stage"><img id="img" alt="슬롯 썸네일"></div>
    <div class="muted" id="meta" style="margin-top:6px"></div>
    <div class="enc" id="enc"></div>
    <div class="bar"><button class="primary" id="save">저장 · 다음</button><button class="ghost" id="next">다음 미태깅 (N)</button><span class="muted" id="stat"></span></div>
  </section>
</main>
<script>
(() => {
  const ENC = [["left","왼쪽"],["middle","가운데"],["right","오른쪽"]];
  const VALS = [[true,"먹이 있음"],[false,"없음"],[null,"불명"]];
  let slots = [], idx = 0, cur = {left:false, middle:false, right:false};
  const $ = (id) => document.getElementById(id);
  async function load() {
    const d = await (await fetch("/api/slots")).json();
    slots = d.slots; $("prog").textContent = `${d.tagged}/${d.total} 태깅됨`;
    renderList(); show(Math.max(0, firstUntagged()));
  }
  function firstUntagged(from = 0) { for (let i = from; i < slots.length; i++) if (slots[i].tags === null) return i; return -1; }
  function renderList() {
    $("list").innerHTML = slots.map((s, i) => `<button data-i="${i}" class="${i === idx ? "cur" : ""} ${s.tags ? "done" : ""}">${s.camera_key} ${s.night_date} ${s.slot.slice(9, 13)}${s.tags ? " ✓" : ""}</button>`).join("");
    for (const b of $("list").querySelectorAll("button")) b.addEventListener("click", () => show(Number(b.dataset.i)));
  }
  function show(i) {
    idx = i; const s = slots[i]; if (!s) return;
    cur = s.tags ? { ...s.tags } : { left: false, middle: false, right: false };
    $("img").src = "/api/thumb?ref=" + encodeURIComponent(s.source_ref);
    $("meta").textContent = `${s.camera_key} · ${s.night_date} · ${s.slot} · ${s.role}${s.tags ? " · 이미 태깅됨(수정 = 새 엔트리)" : ""}`;
    renderEnc(); renderList();
    const el = $("list").querySelector(".cur"); if (el) el.scrollIntoView({ block: "nearest" });
  }
  function renderEnc() {
    $("enc").innerHTML = ENC.map(([k, name], n) => `<div><h3>${n + 1}. ${name} 사육장</h3>${VALS.map(([v, label]) => `<button data-k="${k}" data-v="${v}" class="${cur[k] === v ? "on" : ""}">${label}</button>`).join("")}</div>`).join("");
    for (const b of $("enc").querySelectorAll("button")) b.addEventListener("click", () => { cur[b.dataset.k] = b.dataset.v === "true" ? true : b.dataset.v === "false" ? false : null; renderEnc(); });
  }
  async function save(advance = true) {
    const s = slots[idx];
    const r = await fetch("/api/tag", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ source_ref: s.source_ref, tags: cur }) });
    if (!r.ok) { $("stat").textContent = "저장 실패 " + r.status; return; }
    s.tags = { ...cur }; $("stat").textContent = "저장됨 " + new Date().toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul" });
    $("prog").textContent = `${slots.filter((x) => x.tags).length}/${slots.length} 태깅됨`;
    if (advance) { const n = firstUntagged(idx + 1); show(n >= 0 ? n : Math.min(idx + 1, slots.length - 1)); } else renderList();
  }
  $("save").addEventListener("click", () => save(true));
  $("next").addEventListener("click", () => { const n = firstUntagged(idx + 1); if (n >= 0) show(n); });
  document.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "INPUT") return;
    const k = ev.key.toLowerCase();
    if (k === "a") { cur = { left: false, middle: false, right: false }; renderEnc(); save(true); }
    else if (k === "1" || k === "2" || k === "3") { const key = ENC[Number(k) - 1][0]; cur[key] = cur[key] === true ? false : true; renderEnc(); }
    else if (k === "enter") save(true);
    else if (k === "arrowright") show(Math.min(idx + 1, slots.length - 1));
    else if (k === "arrowleft") show(Math.max(idx - 1, 0));
    else if (k === "n") { const n = firstUntagged(idx + 1); if (n >= 0) show(n); }
    else return;
    ev.preventDefault();
  });
  load();
})();
</script></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dish_tag_server", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="127.0.0.1 로컬 태깅 서버")
    serve.add_argument("--attempt", required=True)
    serve.add_argument("--mirror", required=True, help="미러 루트 (그 아래 recordings/…)")
    serve.add_argument("--test-sheet-sha256", required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--tagger", default="owner")
    comp = sub.add_parser("compile", help="entries → attempt/dish/dish-tags-v1.private.json")
    comp.add_argument("--attempt", required=True)
    comp.add_argument("--test-sheet-sha256", required=True)
    args = parser.parse_args(argv)
    attempt = Path(args.attempt)
    if args.command == "compile":
        ledger = compile_dish_tags(attempt / "dish", attempt / "dish" / "dish-tags-v1.private.json", test_sheet_sha256=args.test_sheet_sha256)
        print(json.dumps({"status": ledger["status"], **ledger["summary"]}, ensure_ascii=False, sort_keys=True))  # type: ignore[arg-type]
        return 0
    import uvicorn

    app = create_app(
        roles_path=attempt / "roles" / "role-freeze.private.json", mirror_root=Path(args.mirror), ledger_dir=attempt / "dish",
        test_sheet_sha256=args.test_sheet_sha256, tagger=args.tagger,
    )
    print(f"dish tagging: http://127.0.0.1:{args.port}/  (Ctrl+C 로 종료, 태그는 {attempt / 'dish' / 'entries'})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
