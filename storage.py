import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def _load() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_destination() -> dict | None:
    """
    Возвращает текущее место назначения заявок:
    {"chat_id": int, "type": "private"|"group", "title": str}
    или None, если ещё не настроено.
    """
    data = _load()
    return data.get("destination")


def set_destination(chat_id: int, dest_type: str, title: str) -> None:
    data = _load()
    data["destination"] = {"chat_id": chat_id, "type": dest_type, "title": title}
    _save(data)
