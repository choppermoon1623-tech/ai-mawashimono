"""Google ドライブの「AI通信」フォルダを見て、新しい号をサイトに取り込む。

- フォルダは「リンクを知っている全員が閲覧可」なので、API キーなしで
  embeddedfolderview から一覧を取れる。
- 新しい号・差し替えられた号だけ PDF をダウンロードし、
  表紙画像 (covers/No○○.jpg)、発行日、テーマ、本文テキストを取り出す。
- 結果は data/issues.json（一覧）と data/search.json（全文検索用）に保存。

GitHub Actions から定期実行する。手元でも `python scripts/sync.py` で動く。
"""

import hashlib
import html
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pymupdf as fitz

FOLDER_ID = "19BDyPjDF4oYOL-E4d4OZybZ4KHDLABZC"
LIST_URL = f"https://drive.google.com/embeddedfolderview?id={FOLDER_ID}"
DOWNLOAD_URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COVERS = ROOT / "covers"
ISSUES_JSON = DATA / "issues.json"
SEARCH_JSON = DATA / "search.json"
OVERRIDES_JSON = DATA / "overrides.json"
COVER_WIDTH = 640
JST = timezone(timedelta(hours=9))


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ai-mawashimono sync)"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return res.read()


def list_folder() -> list[dict]:
    page = fetch(LIST_URL).decode("utf-8")
    pattern = re.compile(
        r'<div class="flip-entry" id="entry-(?P<id>[^"]+)".*?'
        r'<div class="flip-entry-title">(?P<title>[^<]*)</div>.*?'
        r'<div class="flip-entry-last-modified"><div>(?P<mod>[^<]*)</div>',
        re.S,
    )
    files = []
    for m in pattern.finditer(page):
        title = html.unescape(m["title"]).strip()
        if not title.lower().endswith(".pdf"):
            continue
        num = re.search(r"No\.?\s*0*(\d+)", unicodedata.normalize("NFKC", title))
        if not num:
            print(f"  号数が読めないのでスキップ: {title}")
            continue
        files.append({"no": int(num[1]), "id": m["id"], "file": title, "modified": m["mod"].strip()})
    return files


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(text: str) -> str | None:
    m = re.search(r"令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", text)
    if not m:
        return None
    y, mo, d = 2018 + int(m[1]), int(m[2]), int(m[3])
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_theme(lines: list[str]) -> str:
    for i, line in enumerate(lines):
        if "今号のテーマ" in line:
            rest = line.split("今号のテーマ", 1)[1]
            rest = re.sub(r"^[\s】\]:：▶►▷・]+", "", rest).strip()
            if not rest:
                rest = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
            return rest[:120]
    for line in lines:
        if "今号の主役" in line:
            return re.sub(r"^.*今号の主役[:：]?\s*", "", line).strip()[:120]
    # テーマ欄のない号（記念号など）は、発行日の行の直後の見出しを使う
    for i, line in enumerate(lines):
        if "発行" in line:
            heads = [l for l in lines[i + 1:i + 5]
                     if not re.search(r"教務主任|三浦|つぶやき|^第?\s*\d+\s*号$", l)]
            return re.sub(r"\s*★\s*", " ", " ".join(heads[:2])).strip()[:120]
    return ""


def parse_subtitle(lines: list[str]) -> str:
    """テーマの次に来る「〜 … 〜」の副題（あれば）。"""
    for i, line in enumerate(lines):
        if "今号のテーマ" in line:
            for l in lines[i + 1:i + 4]:
                m = re.match(r"^[〜~～]\s*(.+?)\s*[〜~～]$", l.strip())
                if m:
                    return m[1]
            break
    return ""


def process(entry: dict) -> tuple[dict, str]:
    pdf = fetch(DOWNLOAD_URL.format(id=entry["id"]))
    if not pdf.startswith(b"%PDF"):
        raise RuntimeError(f"PDF を取得できませんでした: {entry['file']}")
    doc = fitz.open(stream=pdf, filetype="pdf")

    raw = "\n".join(page.get_text() for page in doc)
    lines = [clean(l) for l in raw.splitlines()]
    lines = [l for l in lines if l]
    full = clean(raw)

    page = doc[0]
    zoom = COVER_WIDTH / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    COVERS.mkdir(exist_ok=True)
    (COVERS / f"No{entry['no']}.jpg").write_bytes(pix.tobytes("jpeg", jpg_quality=78))

    issue = {
        **entry,
        "date": parse_date(full),
        "theme": parse_theme(lines),
        "subtitle": parse_subtitle(lines),
        "pages": doc.page_count,
        "landscape": page.rect.width > page.rect.height,
        "rev": hashlib.sha1(pdf).hexdigest()[:8],
    }
    return issue, full


def main() -> int:
    DATA.mkdir(exist_ok=True)
    old = {i["no"]: i for i in json.loads(ISSUES_JSON.read_text("utf-8"))["issues"]} if ISSUES_JSON.exists() else {}
    search = json.loads(SEARCH_JSON.read_text("utf-8")) if SEARCH_JSON.exists() else {}

    files = list_folder()
    if not files:
        print("フォルダの一覧が取れませんでした（0件）。何も変更せずに終了します。")
        return 1
    print(f"ドライブ上の号: {len(files)} 件")

    # 同じ号数のファイルが複数あるときは、あとに並んだ方（通常は新しい方）を使う
    by_no = {f["no"]: f for f in files}

    issues, changed = [], False
    for no, entry in sorted(by_no.items()):
        prev = old.get(no)
        if prev and prev["id"] == entry["id"] and prev["modified"] == entry["modified"] and str(no) in search:
            issues.append(prev)
            continue
        print(f"  取り込み: 第{no}号 ({entry['file']})")
        try:
            issue, text = process(entry)
        except Exception as e:  # 1号の失敗で全体を止めない
            print(f"  !! 第{no}号の取り込みに失敗: {e}")
            if prev:
                issues.append(prev)
            continue
        issues.append(issue)
        search[str(no)] = text
        changed = True

    live = {i["no"] for i in issues}
    for no in set(old) - live:
        print(f"  削除: 第{no}号（ドライブから消えたため）")
        (COVERS / f"No{no}.jpg").unlink(missing_ok=True)
        changed = True
    for key in [k for k in search if int(k) not in live]:
        del search[key]

    # 自動で読み取ったテーマや日付がおかしいときは data/overrides.json で上書きできる
    #   例: {"30": {"theme": "30号記念 回し続ける理由"}}
    overrides = json.loads(OVERRIDES_JSON.read_text("utf-8")) if OVERRIDES_JSON.exists() else {}
    for issue in issues:
        for key, value in overrides.get(str(issue["no"]), {}).items():
            if issue.get(key) != value:
                issue[key] = value
                changed = True

    if not changed:
        print("変更なし")
        return 0

    issues.sort(key=lambda i: i["no"], reverse=True)
    latest = issues[0]
    (COVERS / "latest.jpg").write_bytes((COVERS / f"No{latest['no']}.jpg").read_bytes())

    payload = {
        "updated": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "folder": f"https://drive.google.com/drive/folders/{FOLDER_ID}",
        "issues": issues,
    }
    ISSUES_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    SEARCH_JSON.write_text(json.dumps(dict(sorted(search.items(), key=lambda kv: int(kv[0]))), ensure_ascii=False), "utf-8")
    print(f"更新しました（最新: 第{latest['no']}号）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
