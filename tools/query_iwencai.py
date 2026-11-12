"""Save raw iWenCai responses for UTF-8 question files; no trading rules."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests


ENDPOINT = "https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
)


def table_rows(value):
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            return table_rows(json.loads(value))
        except ValueError:
            return []
    if isinstance(value, list):
        return [row for child in value for row in table_rows(child)]
    if isinstance(value, dict):
        rows = value.get("datas", [])
        rows = list(rows) if isinstance(rows, list) else []
        return rows + [row for key, child in value.items() if key != "datas" for row in table_rows(child)]
    return []


def signing_bundle():
    response = requests.get("https://pypi.org/pypi/pywencai/json", timeout=20)
    response.raise_for_status()
    metadata = response.json()
    version = metadata["info"]["version"]
    if not re.fullmatch(r"[A-Za-z0-9.+-]+", version):
        raise ValueError("Invalid package version")
    cache = Path(tempfile.gettempdir()) / "ultra-board-iwencai"
    cache.mkdir(exist_ok=True)
    destination = cache / f"hexin-v-{version}.js"
    if not destination.exists():
        wheel = next(item for item in metadata["urls"] if item["filename"].endswith(".whl"))
        package = requests.get(wheel["url"], timeout=30)
        package.raise_for_status()
        if hashlib.sha256(package.content).hexdigest() != wheel["digests"]["sha256"]:
            raise ValueError("Package checksum mismatch")
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            destination.write_bytes(archive.read("pywencai/hexin-v.bundle.js"))
    return destination, version


def query(item, output_dir, bundle, version):
    identifier = item["id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
        raise ValueError("Invalid query id")
    destination = output_dir / f"{identifier}.json"
    if destination.exists():
        cached = json.loads(destination.read_text(encoding="utf-8"))
        rows = table_rows(cached.get("response", {}))
        if cached.get("question") == item["question"] and cached.get("response", {}).get("status_code") == 0 and rows:
            return {"id": identifier, "status_code": 0, "data_rows": len(rows),
                    "cached": True, "file": str(destination)}
    token = subprocess.run(
        ["node", str(bundle)], capture_output=True, text=True, check=True, timeout=20
    ).stdout.strip()
    body = {
        "question": item["question"], "perpage": 100, "page": 1,
        "source": "Ths_iwencai_Xuangu", "version": "2.0", "secondary_intent": "stock",
        "add_info": json.dumps({"urp": {"scene": 1, "company": 1, "business": 1},
                                "contentType": "json", "searchInfo": True}),
    }
    response = requests.post(
        ENDPOINT, data=body,
        headers={"hexin-v": token, "User-Agent": USER_AGENT, "Referer": "https://www.iwencai.com/"},
        timeout=30,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"status_code": None, "response_text": response.text}
    result = {
        "question": item["question"], "url": ENDPOINT, "request_format": "form-urlencoded",
        "http_status": response.status_code, "signing_package": f"pywencai {version}",
        "response": payload,
    }
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"id": identifier, "http_status": response.status_code,
            "status_code": payload.get("status_code"), "data_rows": len(table_rows(payload)),
            "file": str(destination)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    items = json.loads(args.questions_file.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    bundle, version = signing_bundle()
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as executor:
        results = list(executor.map(lambda item: query(item, args.output_dir, bundle, version), items))
    print(json.dumps(results, ensure_ascii=True))
    if any(item["status_code"] != 0 or not item["data_rows"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
