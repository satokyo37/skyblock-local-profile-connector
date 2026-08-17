from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import datetime as dt
import getpass
import gzip
import io
import json
import os
from pathlib import Path
import re
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


API_BASE = "https://api.hypixel.net/v2"
CREDENTIAL_TARGET = "HypixelSkyBlockConnector/ApiKey"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "HypixelSkyBlockConnector"
SNAPSHOT_PATH = APP_DIR / "latest.json"
RESOURCE_CACHE_PATH = APP_DIR / "resources.json"
PROFILE_CONFIG_PATH = APP_DIR / "profile.json"


class ConnectorError(RuntimeError):
    pass


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


def _advapi32() -> Any:
    if os.name != "nt":
        raise ConnectorError("APIキーの安全な保存はWindowsでのみ利用できます。")
    api = ctypes.WinDLL("Advapi32.dll")
    api.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(PCREDENTIALW)]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def store_api_key(api_key: str) -> None:
    api_key = api_key.strip()
    if not api_key or len(api_key) < 20:
        raise ConnectorError("APIキーが短すぎるか空です。コピー内容を確認してください。")
    blob = api_key.encode("utf-16-le")
    blob_buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = CREDENTIALW()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = CREDENTIAL_TARGET
    credential.Comment = "Hypixel SkyBlock local read-only connector"
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "Hypixel API"
    if not _advapi32().CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError()


def load_api_key() -> str:
    api = _advapi32()
    pointer = PCREDENTIALW()
    if not api.CredReadW(CREDENTIAL_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        raise ConnectorError("APIキーが未登録です。先に setup-key を実行してください。")
    try:
        credential = pointer.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-16-le")
    finally:
        api.CredFree(pointer)


def delete_api_key() -> None:
    api = _advapi32()
    if not api.CredDeleteW(CREDENTIAL_TARGET, CRED_TYPE_GENERIC, 0):
        error = ctypes.get_last_error()
        if error != 1168:  # ERROR_NOT_FOUND
            raise ctypes.WinError(error)


def normalize_uuid(value: str) -> str:
    normalized = value.strip().replace("-", "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", normalized):
        raise ConnectorError("UUIDは32桁の16進数で入力してください。ハイフンはあっても構いません。")
    return normalized


def store_profile_settings(player: str, uuid: str, profile: str | None) -> None:
    player = player.strip()
    if not player:
        raise ConnectorError("Minecraftプレイヤー名を入力してください。")
    settings = {
        "player": player,
        "uuid": normalize_uuid(uuid),
        "profile": profile.strip() if profile and profile.strip() else None,
    }
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = PROFILE_CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PROFILE_CONFIG_PATH)


def load_profile_settings() -> dict[str, str | None]:
    if not PROFILE_CONFIG_PATH.exists():
        raise ConnectorError("プロフィールが未登録です。先に setup-profile を実行してください。")
    try:
        settings = json.loads(PROFILE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectorError(f"プロフィール設定を読めません: {exc}") from None
    player = str(settings.get("player") or "").strip()
    uuid = normalize_uuid(str(settings.get("uuid") or ""))
    if not player:
        raise ConnectorError("プロフィール設定にプレイヤー名がありません。")
    profile = settings.get("profile")
    return {"player": player, "uuid": uuid, "profile": str(profile) if profile else None}


def request_json(path: str, *, api_key: str | None = None, params: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    query = urllib.parse.urlencode(params or {})
    url = f"{API_BASE}{path}" + (f"?{query}" if query else "")
    headers = {"Accept": "application/json", "User-Agent": "Kyokk-SkyBlock-Connector/1.0"}
    if api_key:
        headers["API-Key"] = api_key
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
            rate = {
                "limit": response.headers.get("RateLimit-Limit", ""),
                "remaining": response.headers.get("RateLimit-Remaining", ""),
                "reset_seconds": response.headers.get("RateLimit-Reset", ""),
            }
            return data, rate
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            cause = body.get("cause") or body.get("error") or f"HTTP {exc.code}"
        except Exception:
            cause = f"HTTP {exc.code}"
        if exc.code == 403:
            cause = "APIキーが無効・期限切れ、または未承認です"
        elif exc.code == 429:
            cause = "APIのリクエスト上限に達しました"
        raise ConnectorError(str(cause)) from None
    except urllib.error.URLError as exc:
        raise ConnectorError(f"Hypixel APIへ接続できません: {exc.reason}") from None


class NBTReader:
    def __init__(self, data: bytes):
        self.stream = io.BytesIO(data)

    def read_exact(self, size: int) -> bytes:
        value = self.stream.read(size)
        if len(value) != size:
            raise ValueError("NBTデータが途中で終了しました")
        return value

    def number(self, fmt: str) -> int | float:
        return struct.unpack(">" + fmt, self.read_exact(struct.calcsize(">" + fmt)))[0]

    def string(self) -> str:
        length = int(self.number("H"))
        return self.read_exact(length).decode("utf-8", errors="replace")

    def payload(self, tag_type: int) -> Any:
        if tag_type == 1:
            return self.number("b")
        if tag_type == 2:
            return self.number("h")
        if tag_type == 3:
            return self.number("i")
        if tag_type == 4:
            return self.number("q")
        if tag_type == 5:
            return self.number("f")
        if tag_type == 6:
            return self.number("d")
        if tag_type == 7:
            return list(self.read_exact(int(self.number("i"))))
        if tag_type == 8:
            return self.string()
        if tag_type == 9:
            child_type = int(self.number("B"))
            length = int(self.number("i"))
            return [self.payload(child_type) for _ in range(max(0, length))]
        if tag_type == 10:
            compound: dict[str, Any] = {}
            while True:
                child_type = int(self.number("B"))
                if child_type == 0:
                    return compound
                child_name = self.string()
                compound[child_name] = self.payload(child_type)
        if tag_type == 11:
            return [self.number("i") for _ in range(max(0, int(self.number("i"))))]
        if tag_type == 12:
            return [self.number("q") for _ in range(max(0, int(self.number("i"))))]
        raise ValueError(f"未対応のNBTタグです: {tag_type}")

    def root(self) -> Any:
        tag_type = int(self.number("B"))
        if tag_type == 0:
            return None
        self.string()  # root name
        return self.payload(tag_type)


def decode_inventory(data: str | None) -> list[dict[str, Any]]:
    if not data:
        return []
    try:
        raw = base64.b64decode(data)
        try:
            raw = gzip.decompress(raw)
        except gzip.BadGzipFile:
            pass
        root = NBTReader(raw).root()
    except Exception as exc:
        raise ConnectorError(f"インベントリNBTを解析できません: {exc}") from None
    if not isinstance(root, dict):
        return []
    items = root.get("i", [])
    return [normalize_item(item, slot) for slot, item in enumerate(items) if isinstance(item, dict) and item]


def strip_minecraft_format(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    result: list[str] = []
    skip = False
    for char in text:
        if skip:
            skip = False
        elif char == "§":
            skip = True
        else:
            result.append(char)
    return "".join(result)


def normalize_item(item: dict[str, Any], fallback_slot: int) -> dict[str, Any]:
    tag = item.get("tag") if isinstance(item.get("tag"), dict) else {}
    extra = tag.get("ExtraAttributes") if isinstance(tag.get("ExtraAttributes"), dict) else {}
    display = tag.get("display") if isinstance(tag.get("display"), dict) else {}
    enchantments = extra.get("enchantments") if isinstance(extra.get("enchantments"), dict) else {}
    attributes = extra.get("attributes") if isinstance(extra.get("attributes"), dict) else {}
    return {
        "slot": item.get("Slot", fallback_slot),
        "id": extra.get("id") or item.get("id") or "",
        "name": strip_minecraft_format(display.get("Name")) or str(extra.get("id") or item.get("id") or "Unknown"),
        "count": item.get("Count", item.get("count", 1)),
        "rarity_upgrades": extra.get("rarity_upgrades", 0),
        "hot_potato_count": extra.get("hot_potato_count", 0),
        "enchantments": enchantments,
        "attributes": attributes,
        "lore": [strip_minecraft_format(line) for line in display.get("Lore", [])] if isinstance(display.get("Lore"), list) else [],
    }


def find_key_values(value: Any, wanted: set[str]) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in wanted:
                found.append((key, child))
            found.extend(find_key_values(child, wanted))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_key_values(child, wanted))
    return found


def first_path(value: dict[str, Any], paths: list[tuple[str, ...]], default: Any = None) -> Any:
    for path in paths:
        cursor: Any = value
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                break
            cursor = cursor[key]
        else:
            return cursor
    return default


def extract_inventory_sections(member: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    aliases = {
        "armor": {"inv_armor", "inv_armor_data"},
        "equipment": {"equipment_contents", "equipment"},
        "inventory": {"inv_contents", "inventory"},
        "ender_chest": {"ender_chest_contents", "ender_chest"},
        "accessory_bag": {"talisman_bag", "accessory_bag"},
        "fishing_bag": {"fishing_bag"},
        "sacks_bag": {"sacks_bag", "sack_of_sacks"},
        "potion_bag": {"potion_bag"},
        "quiver": {"quiver"},
    }
    output: dict[str, list[dict[str, Any]]] = {}
    for section, keys in aliases.items():
        candidates = find_key_values(member, keys)
        for _, candidate in candidates:
            if isinstance(candidate, str):
                encoded = candidate
            elif isinstance(candidate, dict):
                encoded = candidate.get("data")
            else:
                continue
            if isinstance(encoded, str) and encoded:
                output[section] = decode_inventory(encoded)
                break
        output.setdefault(section, [])
    return output


def extract_sack_counts(member: dict[str, Any]) -> dict[str, int | float]:
    matches = find_key_values(member, {"sacks_counts", "sack_counts"})
    for _, value in matches:
        if isinstance(value, dict):
            return {str(k): v for k, v in sorted(value.items()) if isinstance(v, (int, float)) and v != 0}
    return {}


def fishing_xp(member: dict[str, Any]) -> float | None:
    value = first_path(
        member,
        [
            ("player_data", "experience", "SKILL_FISHING"),
            ("player_data", "experience", "fishing"),
            ("experience_skill_fishing",),
        ],
    )
    return float(value) if isinstance(value, (int, float)) else None


def load_resource_data(max_age_hours: int = 24) -> dict[str, Any]:
    if RESOURCE_CACHE_PATH.exists():
        age = dt.datetime.now(dt.timezone.utc).timestamp() - RESOURCE_CACHE_PATH.stat().st_mtime
        if age < max_age_hours * 3600:
            try:
                cached = json.loads(RESOURCE_CACHE_PATH.read_text(encoding="utf-8"))
                if cached.get("item_names") and cached.get("fishing_levels"):
                    return cached
            except (OSError, json.JSONDecodeError):
                pass

    items_response, _ = request_json("/resources/skyblock/items")
    skills_response, _ = request_json("/resources/skyblock/skills")
    item_names = {
        str(item["id"]): str(item["name"])
        for item in items_response.get("items", [])
        if isinstance(item, dict) and item.get("id") and item.get("name")
    }
    fishing = (skills_response.get("skills") or {}).get("FISHING") or {}
    fishing_levels = [
        {"level": int(level["level"]), "total_xp": float(level["totalExpRequired"])}
        for level in fishing.get("levels", [])
        if isinstance(level, dict) and "level" in level and "totalExpRequired" in level
    ]
    resources = {
        "cached_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "item_names": item_names,
        "fishing_levels": fishing_levels,
    }
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = RESOURCE_CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(resources, ensure_ascii=False), encoding="utf-8")
    temporary.replace(RESOURCE_CACHE_PATH)
    return resources


def skill_progress(xp: float | None, levels: list[dict[str, Any]]) -> dict[str, Any]:
    if xp is None:
        return {"xp": None, "level": None, "next_level": None, "remaining_to_next": None}
    current_level = 0
    current_threshold = 0.0
    next_level: int | None = None
    next_threshold: float | None = None
    for entry in sorted(levels, key=lambda value: int(value["level"])):
        threshold = float(entry["total_xp"])
        if xp >= threshold:
            current_level = int(entry["level"])
            current_threshold = threshold
        else:
            next_level = int(entry["level"])
            next_threshold = threshold
            break
    return {
        "xp": xp,
        "level": current_level,
        "next_level": next_level,
        "progress_in_level": xp - current_threshold,
        "required_in_level": (next_threshold - current_threshold) if next_threshold is not None else None,
        "remaining_to_next": max(0.0, next_threshold - xp) if next_threshold is not None else None,
    }


def profile_member(profile: dict[str, Any], uuid: str) -> dict[str, Any]:
    members = profile.get("members") or {}
    normalized = uuid.replace("-", "").lower()
    for key, value in members.items():
        if key.replace("-", "").lower() == normalized and isinstance(value, dict):
            return value
    raise ConnectorError("指定プレイヤーのプロフィールデータが見つかりません。")


def select_profile(profiles: list[dict[str, Any]], cute_name: str | None) -> dict[str, Any]:
    if cute_name:
        for profile in profiles:
            if str(profile.get("cute_name", "")).lower() == cute_name.lower():
                return profile
        raise ConnectorError(f"プロフィール {cute_name} が見つかりません。")
    for profile in profiles:
        if profile.get("selected"):
            return profile
    if profiles:
        return profiles[0]
    raise ConnectorError("SkyBlockプロフィールがありません。")


def build_snapshot(
    api_data: dict[str, Any],
    uuid: str,
    player: str,
    profile_name: str | None,
    rate: dict[str, str],
    resources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not api_data.get("success"):
        raise ConnectorError(str(api_data.get("cause") or "Hypixel APIの取得に失敗しました。"))
    profiles = api_data.get("profiles")
    if not isinstance(profiles, list):
        raise ConnectorError("プロフィール一覧がAPIレスポンスにありません。")
    profile = select_profile(profiles, profile_name)
    member = profile_member(profile, uuid)
    inventories = extract_inventory_sections(member)
    sack_items = [item for item in inventories.get("sacks_bag", []) if "SACK" in str(item.get("id", "")).upper()]
    sack_counts = extract_sack_counts(member)
    resources = resources or {}
    item_names = resources.get("item_names") or {}
    fishing_value = fishing_xp(member)
    fishing = skill_progress(fishing_value, resources.get("fishing_levels") or [])
    purse = first_path(member, [("currencies", "coin_purse"), ("coin_purse",)], 0)
    snapshot = {
        "schema_version": 1,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "player": {"name": player, "uuid": uuid},
        "profile": {
            "name": profile.get("cute_name"),
            "id": profile.get("profile_id"),
            "selected": bool(profile.get("selected")),
            "game_mode": profile.get("game_mode") or "normal",
        },
        "currency": {
            "purse": purse if isinstance(purse, (int, float)) else 0,
            "bank": first_path(profile, [("banking", "balance")], 0),
        },
        "skills": {"fishing": fishing, "fishing_xp": fishing_value},
        "armor": inventories.get("armor", []),
        "equipment": inventories.get("equipment", []),
        "inventory": inventories.get("inventory", []),
        "ender_chest": inventories.get("ender_chest", []),
        "accessory_bag": inventories.get("accessory_bag", []),
        "fishing_bag": inventories.get("fishing_bag", []),
        "owned_sacks": sack_items,
        "sack_counts": sack_counts,
        "sack_contents": [
            {
                "id": item_id,
                "name": item_names.get(item_id) or item_id.replace("_", " ").title(),
                "count": count,
            }
            for item_id, count in sorted(sack_counts.items(), key=lambda pair: (-float(pair[1]), pair[0]))
        ],
        "api_rate_limit": rate,
        "notes": [
            "APIキーはこのファイルに保存されていません。",
            "Hypixel API設定や同期状況により一部データが空の場合があります。",
        ],
    }
    return snapshot


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SNAPSHOT_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SNAPSHOT_PATH)
    return SNAPSHOT_PATH


def command_setup_key(_: argparse.Namespace) -> int:
    first = getpass.getpass("Hypixel API Key（入力内容は表示されません）: ").strip()
    second = getpass.getpass("確認のためもう一度入力: ").strip()
    if first != second:
        raise ConnectorError("2回の入力が一致しません。保存していません。")
    store_api_key(first)
    print("APIキーをWindows資格情報マネージャーへ保存しました。")
    return 0


def command_delete_key(_: argparse.Namespace) -> int:
    delete_api_key()
    print("保存済みAPIキーを削除しました。")
    return 0


def command_setup_profile(args: argparse.Namespace) -> int:
    player = args.player or input("Minecraftプレイヤー名: ").strip()
    uuid = args.uuid or input("Minecraft UUID（32桁、ハイフン可）: ").strip()
    profile = args.profile
    if profile is None:
        profile = input("SkyBlockプロフィール名（選択中を使う場合は空欄）: ").strip() or None
    store_profile_settings(player, uuid, profile)
    print("プロフィールをローカル設定へ保存しました。")
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    settings = load_profile_settings()
    player = args.player or str(settings["player"])
    uuid = normalize_uuid(args.uuid or str(settings["uuid"]))
    profile = args.profile if args.profile is not None else settings["profile"]
    key = load_api_key()
    data, rate = request_json("/skyblock/profiles", api_key=key, params={"uuid": uuid})
    resources = load_resource_data()
    snapshot = build_snapshot(data, uuid, player, profile, rate, resources)
    path = write_snapshot(snapshot)
    print(json.dumps({
        "success": True,
        "snapshot": str(path),
        "profile": snapshot["profile"]["name"],
        "fetched_at": snapshot["fetched_at"],
        "rate_limit": snapshot["api_rate_limit"],
    }, ensure_ascii=False))
    return 0


def command_status(_: argparse.Namespace) -> int:
    if not SNAPSHOT_PATH.exists():
        print(json.dumps({"available": False, "snapshot": str(SNAPSHOT_PATH)}, ensure_ascii=False))
        return 0
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    print(json.dumps({
        "available": True,
        "snapshot": str(SNAPSHOT_PATH),
        "fetched_at": snapshot.get("fetched_at"),
        "player": snapshot.get("player"),
        "profile": snapshot.get("profile"),
    }, ensure_ascii=False))
    return 0


def command_doctor(_: argparse.Namespace) -> int:
    items, _ = request_json("/resources/skyblock/items")
    print(json.dumps({
        "success": bool(items.get("success")),
        "public_api": "ok" if items.get("success") else "error",
        "items": len(items.get("items", [])),
        "credential_target": CREDENTIAL_TARGET,
        "snapshot": str(SNAPSHOT_PATH),
    }, ensure_ascii=False))
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hypixel SkyBlock会話用データ取得コネクタ")
    subparsers = parser.add_subparsers(dest="command", required=True)
    setup = subparsers.add_parser("setup-key", help="APIキーをWindows資格情報へ安全に保存")
    setup.set_defaults(func=command_setup_key)
    delete = subparsers.add_parser("delete-key", help="保存済みAPIキーを削除")
    delete.set_defaults(func=command_delete_key)
    profile = subparsers.add_parser("setup-profile", help="取得対象プロフィールをローカル設定へ保存")
    profile.add_argument("--player")
    profile.add_argument("--uuid")
    profile.add_argument("--profile")
    profile.set_defaults(func=command_setup_profile)
    fetch = subparsers.add_parser("fetch", help="最新プロフィールを取得")
    fetch.add_argument("--player")
    fetch.add_argument("--uuid")
    fetch.add_argument("--profile")
    fetch.set_defaults(func=command_fetch)
    status = subparsers.add_parser("status", help="最新スナップショットの状態を表示")
    status.set_defaults(func=command_status)
    doctor = subparsers.add_parser("doctor", help="キー不要の接続診断")
    doctor.set_defaults(func=command_doctor)
    return parser


def main() -> int:
    try:
        args = make_parser().parse_args()
        return int(args.func(args))
    except ConnectorError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
