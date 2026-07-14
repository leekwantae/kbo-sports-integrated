from __future__ import annotations
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
API = "https://mapi.ticketlink.co.kr/mapi/sports/schedules"
KST = timezone(timedelta(hours=9), name="KST")

def ms_to_dt(value: Any):
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, KST)
    except Exception:
        return None

def team_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("teamName") or value.get("teamShortName") or "").strip()
    return ""

def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.ticketlink.co.kr/"
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))

def parse_item(item: dict[str, Any], source: dict[str, Any]):
    game = ms_to_dt(item.get("scheduleDate"))
    if not game:
        return None
    reserve = ms_to_dt(
        item.get("reserveOpenDateTime")
        or item.get("reserveOpenDate")
        or item.get("reservePreOpenDateTime")
    )
    status = str(item.get("reserveButtonStatus") or "").upper()
    booking = "예매중" if status == "ON_SALE" else (
        reserve.strftime("%Y-%m-%d %H:%M") if reserve else ""
    )
    schedule_id = str(item.get("scheduleId") or "")
    away = team_name(item.get("awayTeam"))
    home = team_name(item.get("homeTeam"))
    event = {
        "sport": source.get("sport", "baseball"),
        "team": source["team"],
        "date": game.strftime("%Y-%m-%d"),
        "time": game.strftime("%H:%M"),
        "away": away,
        "home": home,
        "venue": str(item.get("venueName") or "").strip(),
        "title": str(item.get("matchTitle") or "").strip(),
        "league": str(item.get("leagueName") or "").strip(),
        "booking": booking,
        "reserveButtonStatus": status,
        "scheduleId": schedule_id,
        "productId": str(item.get("productId") or ""),
        "link": source.get("pageUrl", "")
    }
    event["id"] = schedule_id or "|".join([
        event["date"], event["time"], away, home, event["venue"]
    ])
    return event

def main():
    now = datetime.now(KST)
    end = now + timedelta(days=int(CONFIG.get("rangeDays", 92)))
    all_events = []
    source_status = []

    for source in CONFIG.get("sources", []):
        params = urllib.parse.urlencode({
            "categoryId": source["categoryId"],
            "teamId": source["teamId"],
            "startDate": now.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d")
        })
        url = f"{API}?{params}"
        status = {
            "team": source["team"], "success": False, "count": 0,
            "checkedAt": datetime.now(KST).isoformat(timespec="seconds"),
            "message": ""
        }
        try:
            payload = fetch_json(url)
            schedules = payload.get("data", {}).get("schedules", [])
            if not isinstance(schedules, list):
                raise RuntimeError("data.schedules 배열이 없습니다.")
            events, seen = [], set()
            for item in schedules:
                if not isinstance(item, dict):
                    continue
                event = parse_item(item, source)
                if event and event["id"] not in seen:
                    seen.add(event["id"])
                    events.append(event)
            all_events.extend(events)
            status["success"] = True
            status["count"] = len(events)
            status["message"] = "API 조회 성공"
        except Exception as exc:
            status["message"] = str(exc)
        source_status.append(status)

    dedup = {}
    for event in all_events:
        key = event.get("scheduleId") or event["id"]
        dedup[key] = event

    events = sorted(dedup.values(), key=lambda e: f"{e.get('date','')}T{e.get('time','00:00')}")
    payload = {
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "queryRange": {
            "startDate": now.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "rangeDays": int(CONFIG.get("rangeDays", 92))
        },
        "sourceStatus": source_status,
        "events": events
    }
    (ROOT / "data.js").write_text(
        "window.SPORTS_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8"
    )
    print(f"티켓링크 총 {len(events)}건 생성")

if __name__ == "__main__":
    main()
