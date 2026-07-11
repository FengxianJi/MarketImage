#!/usr/bin/env python3
"""Local EmergingArt preference annotation server.

The app intentionally uses only the Python standard library so it can run from
the repository without installing frontend or backend dependencies.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import socket
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


APP_ROOT = Path(__file__).resolve().parent
DATASET_ROOT = APP_ROOT / "EmergingArt"
DATA_DIR = DATASET_ROOT / "data"
STATIC_DIR = APP_ROOT / "static"
ANNOTATION_DIR = APP_ROOT / "annotations"
ANNOTATION_FILE = ANNOTATION_DIR / "emergingart_annotations.json"
FOLDER_ID_RE = re.compile(r"^[0-9A-Za-z_-]+$")
DATASET_NAME_RE = re.compile(r"^[0-9A-Za-z_. -]+$")

ANNOTATION_LOCK = threading.Lock()
GROUP_CACHE: dict[str, list[dict[str, Any]]] | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def text_response(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    payload = {"error": message}
    json_response(handler, payload, status)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
        temp_path = Path(file.name)
    temp_path.replace(path)


def relative_to_app(path: Path) -> str:
    return path.resolve().relative_to(APP_ROOT).as_posix()


def normalize_dataset_name(name: str) -> str:
    if not name or not DATASET_NAME_RE.match(name):
        raise ValueError("invalid dataset name")
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        raise ValueError(f"unknown dataset: {name}")
    return name


def normalize_folder_id(folder_id: str | int) -> str:
    value = str(folder_id)
    if not FOLDER_ID_RE.match(value):
        raise ValueError(f"invalid folder id: {value}")
    return value


def normalize_group_limit(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        limit = int(text)
    except ValueError as exc:
        raise ValueError("group limit must be an integer") from exc
    if limit < 1:
        raise ValueError("group limit must be greater than 0")
    return limit


def query_group_limit(query: dict[str, list[str]]) -> int | None:
    return normalize_group_limit(query.get("limit", [""])[0])


def apply_group_limit(groups: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return groups
    return groups[:limit]


def load_groups() -> dict[str, list[dict[str, Any]]]:
    global GROUP_CACHE
    if GROUP_CACHE is not None:
        return GROUP_CACHE

    if not DATA_DIR.exists():
        raise RuntimeError(f"dataset data directory not found: {DATA_DIR}")

    datasets: dict[str, list[dict[str, Any]]] = {}
    for data_file in sorted(DATA_DIR.glob("*.json")):
        dataset_name = data_file.stem
        rows = read_json(data_file)
        grouped: dict[int, list[dict[str, Any]]] = {}
        group_order: list[int] = []
        for dataset_row_index, row in enumerate(rows):
            group_id = int(row["group_id"])
            folder_id = normalize_folder_id(row["folder_id"])
            image_path = DATASET_ROOT / folder_id / "figure" / "1.jpg"
            if group_id not in grouped:
                grouped[group_id] = []
                group_order.append(group_id)
            item = {
                "folder_id": folder_id,
                "price": float(row["price"]),
                "source_folder_path": row.get("folder_path", ""),
                "local_folder_path": relative_to_app(DATASET_ROOT / folder_id),
                "image_path": relative_to_app(image_path),
                "dataset_row_index": dataset_row_index,
                "item_order_index": len(grouped[group_id]),
                "image_exists": image_path.exists(),
            }
            grouped[group_id].append(item)

        groups: list[dict[str, Any]] = []
        for group_order_index, group_id in enumerate(group_order):
            items = grouped[group_id]
            groups.append(
                {
                    "dataset": dataset_name,
                    "group_id": group_id,
                    "group_order_index": group_order_index,
                    "items": items,
                    "item_count": len(items),
                }
            )
        datasets[dataset_name] = groups

    GROUP_CACHE = datasets
    return datasets


def public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "folder_id": item["folder_id"],
        "source_order": item["item_order_index"] + 1,
        "dataset_row_index": item["dataset_row_index"],
        "image_url": f"/image/{item['folder_id']}",
        "image_exists": bool(item.get("image_exists")),
    }


def get_group(dataset: str, group_id: int) -> dict[str, Any]:
    datasets = load_groups()
    if dataset not in datasets:
        raise ValueError(f"unknown dataset: {dataset}")
    for group in datasets[dataset]:
        if group["group_id"] == group_id:
            return group
    raise ValueError(f"unknown group id: {group_id}")


def annotation_key(annotator: str, dataset: str, group_id: int) -> str:
    cleaned = annotator.strip() or "anonymous"
    return f"{cleaned}::{dataset}::{group_id}"


def empty_annotation_store() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_name": "EmergingArt",
        "dataset_root": relative_to_app(DATASET_ROOT),
        "ranking_direction": "rank_1_is_most_preferred",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "records": {},
    }


def load_annotation_store() -> dict[str, Any]:
    if not ANNOTATION_FILE.exists():
        return empty_annotation_store()
    store = read_json(ANNOTATION_FILE)
    store.setdefault("records", {})
    return store


def save_annotation_store(store: dict[str, Any]) -> None:
    store["updated_at"] = now_iso()
    atomic_write_json(ANNOTATION_FILE, store)


def annotation_status(annotator: str) -> dict[str, set[tuple[str, int]]]:
    with ANNOTATION_LOCK:
        store = load_annotation_store()
    completed: set[tuple[str, int]] = set()
    for record in store.get("records", {}).values():
        if record.get("annotator") == annotator:
            completed.add((record.get("dataset"), int(record.get("group_id"))))
    return {"completed": completed}


def find_existing_record(annotator: str, dataset: str, group_id: int) -> dict[str, Any] | None:
    key = annotation_key(annotator, dataset, group_id)
    with ANNOTATION_LOCK:
        store = load_annotation_store()
    record = store.get("records", {}).get(key)
    return record if isinstance(record, dict) else None


def export_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_order": item["item_order_index"] + 1,
        "dataset_row_index": item["dataset_row_index"],
        "folder_id": item["folder_id"],
        "price": item["price"],
        "image_path": item["image_path"],
        "local_folder_path": item["local_folder_path"],
        "source_folder_path": item["source_folder_path"],
    }


class AnnotationHandler(BaseHTTPRequestHandler):
    server_version = "EmergingArtAnnotation/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        try:
            if path == "/":
                self.serve_static(STATIC_DIR / "index.html")
            elif path.startswith("/static/"):
                relative = path.removeprefix("/static/")
                self.serve_static(STATIC_DIR / relative)
            elif path.startswith("/image/"):
                folder_id = normalize_folder_id(path.removeprefix("/image/"))
                self.serve_image(folder_id)
            elif path == "/api/datasets":
                self.handle_datasets(query)
            elif path == "/api/groups":
                self.handle_groups(query)
            elif path == "/api/group":
                self.handle_group(query)
            elif path == "/api/export":
                self.handle_export(query)
            elif path == "/health":
                json_response(self, {"ok": True, "dataset_root": relative_to_app(DATASET_ROOT)})
            else:
                text_response(self, "not found", 404)
        except ValueError as exc:
            text_response(self, str(exc), 400)
        except Exception as exc:  # pragma: no cover - keeps local app debuggable.
            text_response(self, f"server error: {exc}", 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/annotation":
                self.handle_save_annotation()
            else:
                text_response(self, "not found", 404)
        except ValueError as exc:
            text_response(self, str(exc), 400)
        except Exception as exc:  # pragma: no cover
            text_response(self, f"server error: {exc}", 500)

    def serve_static(self, path: Path) -> None:
        resolved = path.resolve()
        if not str(resolved).startswith(str(STATIC_DIR.resolve())):
            text_response(self, "invalid static path", 403)
            return
        if not resolved.exists() or not resolved.is_file():
            text_response(self, "not found", 404)
            return
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_image(self, folder_id: str) -> None:
        path = DATASET_ROOT / folder_id / "figure" / "1.jpg"
        if not path.exists() or not path.is_file():
            text_response(self, "image not found", 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def handle_datasets(self, query: dict[str, list[str]]) -> None:
        annotator = (query.get("annotator", ["anonymous"])[0] or "anonymous").strip()
        group_limit = query_group_limit(query)
        datasets = load_groups()
        completed = annotation_status(annotator)["completed"]
        payload = []
        for name in sorted(datasets):
            scoped_groups = apply_group_limit(datasets[name], group_limit)
            total = len(scoped_groups)
            done = sum(1 for group in scoped_groups if (name, group["group_id"]) in completed)
            payload.append(
                {
                    "name": name,
                    "dataset_groups": len(datasets[name]),
                    "total_groups": total,
                    "completed_groups": done,
                    "remaining_groups": total - done,
                }
            )
        json_response(
            self,
            {
                "datasets": payload,
                "group_limit": group_limit,
                "annotation_file": str(ANNOTATION_FILE),
            },
        )

    def handle_groups(self, query: dict[str, list[str]]) -> None:
        annotator = (query.get("annotator", ["anonymous"])[0] or "anonymous").strip()
        dataset = normalize_dataset_name(query.get("dataset", ["Overall"])[0])
        group_limit = query_group_limit(query)
        completed = annotation_status(annotator)["completed"]
        groups = apply_group_limit(load_groups()[dataset], group_limit)
        first_pending = next((group["group_id"] for group in groups if (dataset, group["group_id"]) not in completed), None)
        payload = [
            {
                "group_id": group["group_id"],
                "group_order": group["group_order_index"] + 1,
                "item_count": group["item_count"],
                "completed": (dataset, group["group_id"]) in completed,
            }
            for group in groups
        ]
        json_response(
            self,
            {
                "dataset": dataset,
                "group_limit": group_limit,
                "total_groups": len(groups),
                "completed_groups": sum(1 for group in payload if group["completed"]),
                "first_pending_group_id": first_pending,
                "groups": payload,
            },
        )

    def handle_group(self, query: dict[str, list[str]]) -> None:
        annotator = (query.get("annotator", ["anonymous"])[0] or "anonymous").strip()
        dataset = normalize_dataset_name(query.get("dataset", ["Overall"])[0])
        group_id = int(query.get("group_id", ["0"])[0])
        group = get_group(dataset, group_id)
        existing = find_existing_record(annotator, dataset, group_id)

        if existing:
            by_id = {item["folder_id"]: item for item in group["items"]}
            ranked_ids = [normalize_folder_id(fid) for fid in existing.get("ranked_folder_ids", [])]
            ordered_items = [by_id[fid] for fid in ranked_ids if fid in by_id]
            ordered_items.extend(item for item in group["items"] if item["folder_id"] not in ranked_ids)
        else:
            ordered_items = list(group["items"])

        json_response(
            self,
            {
                "dataset": dataset,
                "group_id": group_id,
                "group_order": group["group_order_index"] + 1,
                "item_count": group["item_count"],
                "source_ordered_folder_ids": [item["folder_id"] for item in group["items"]],
                "items": [public_item(item) for item in ordered_items],
                "existing_annotation": {
                    "completed": bool(existing),
                    "updated_at": existing.get("updated_at") if existing else None,
                    "notes": existing.get("notes", "") if existing else "",
                    "duration_ms": existing.get("duration_ms") if existing else None,
                },
            },
        )

    def handle_export(self, query: dict[str, list[str]]) -> None:
        annotator = (query.get("annotator", [""])[0] or "").strip()
        with ANNOTATION_LOCK:
            store = load_annotation_store()
        if annotator:
            records = {
                key: value
                for key, value in store.get("records", {}).items()
                if value.get("annotator") == annotator
            }
            store = {**store, "records": records}
        json_response(self, store)

    def handle_save_annotation(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

        annotator = str(payload.get("annotator") or "anonymous").strip() or "anonymous"
        dataset = normalize_dataset_name(str(payload.get("dataset") or "Overall"))
        group_id = int(payload.get("group_id"))
        ranked_folder_ids = [normalize_folder_id(fid) for fid in payload.get("ranked_folder_ids", [])]
        group_limit = normalize_group_limit(payload.get("group_limit"))
        duration_ms = int(payload.get("duration_ms") or 0)
        notes = str(payload.get("notes") or "").strip()

        group = get_group(dataset, group_id)
        expected_ids = {item["folder_id"] for item in group["items"]}
        submitted_ids = set(ranked_folder_ids)
        if len(ranked_folder_ids) != len(group["items"]):
            raise ValueError("ranking length does not match group size")
        if submitted_ids != expected_ids:
            missing = sorted(expected_ids - submitted_ids)
            extra = sorted(submitted_ids - expected_ids)
            raise ValueError(f"ranking ids do not match group; missing={missing}, extra={extra}")

        item_by_id = {item["folder_id"]: item for item in group["items"]}
        timestamp = now_iso()
        key = annotation_key(annotator, dataset, group_id)
        with ANNOTATION_LOCK:
            store = load_annotation_store()
            previous = store.get("records", {}).get(key, {})
            record = {
                "annotation_id": key,
                "annotator": annotator,
                "dataset": dataset,
                "group_id": group_id,
                "group_order": group["group_order_index"] + 1,
                "group_limit": group_limit,
                "item_count": group["item_count"],
                "source_ordered_folder_ids": [item["folder_id"] for item in group["items"]],
                "ranked_folder_ids": ranked_folder_ids,
                "ranked_items": [
                    {
                        "rank": index + 1,
                        **export_item(item_by_id[folder_id]),
                    }
                    for index, folder_id in enumerate(ranked_folder_ids)
                ],
                "source_group": [export_item(item) for item in group["items"]],
                "notes": notes,
                "duration_ms": duration_ms,
                "created_at": previous.get("created_at", timestamp),
                "updated_at": timestamp,
            }
            store.setdefault("records", {})[key] = record
            save_annotation_store(store)

        json_response(
            self,
            {
                "ok": True,
                "annotation_id": key,
                "annotation_file": str(ANNOTATION_FILE),
                "updated_at": timestamp,
            },
        )


def find_port(start_port: int, host: str = "127.0.0.1") -> int:
    for port in range(start_port, start_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no available port found from {start_port}")


def main() -> None:
    parser = argparse.ArgumentParser(description="EmergingArt preference annotation GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    load_groups()
    ANNOTATION_DIR.mkdir(parents=True, exist_ok=True)
    port = find_port(args.port, args.host)
    server = ThreadingHTTPServer((args.host, port), AnnotationHandler)
    print(f"EmergingArt annotation GUI: http://{args.host}:{port}")
    print(f"Dataset root: {relative_to_app(DATASET_ROOT)}")
    print(f"Annotation file: {relative_to_app(ANNOTATION_FILE)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
