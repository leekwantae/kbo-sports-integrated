from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads(
    (ROOT / "sources.json").read_text(encoding="utf-8")
)

API = "https://mapi.ticketlink.co.kr/mapi/sports/schedules"
KST = timezone(timedelta(hours=9), name="KST")


def ms_to_dt(value: Any):
    if value in (None, "", 0):
        return None

    try:
        number = int(value)

        if number < 100_000_000_000:
            number *= 1000

        return datetime.fromtimestamp(number / 1000, KST)

    except Exception:
        return None


def team_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""

    return str(
        value.get("teamName")
        or value.get("teamShortName")
        or value.get("name")
        or ""
    ).strip()


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": "https://www.ticketlink.co.kr/",
            "Origin": "https://www.ticketlink.co.kr",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=40
    ) as response:

        response_text = response.read().decode(
            "utf-8",
            errors="replace"
        )

        print(f"HTTP 상태: {response.status}")
        print(f"응답 길이: {len(response_text)}자")
        print("응답 앞부분:")
        print(response_text[:1000])

        return json.loads(response_text)


def find_schedules(payload: Any) -> list:
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")

    if isinstance(data, dict):
        schedules = data.get("schedules")

        if isinstance(schedules, list):
            return schedules

    schedules = payload.get("schedules")

    if isinstance(schedules, list):
        return schedules

    return []


def parse_item(
    item: dict[str, Any],
    source: dict[str, Any]
):
    game = ms_to_dt(item.get("scheduleDate"))

    if not game:
        return None

    reserve = ms_to_dt(
        item.get("reserveOpenDateTime")
        or item.get("reserveOpenDate")
        or item.get("reservePreOpenDateTime")
    )

    status = str(
        item.get("reserveButtonStatus")
        or ""
    ).upper()

    if status == "ON_SALE":
        booking = "예매중"
    elif reserve:
        booking = reserve.strftime("%Y-%m-%d %H:%M")
    else:
        booking = ""

    schedule_id = str(
        item.get("scheduleId")
        or ""
    )

    away = team_name(item.get("awayTeam"))
    home = team_name(item.get("homeTeam"))

    event = {
        "sport": source.get("sport", "baseball"),
        "team": source["team"],
        "date": game.strftime("%Y-%m-%d"),
        "time": game.strftime("%H:%M"),
        "away": away,
        "home": home,
        "venue": str(
            item.get("venueName")
            or ""
        ).strip(),
        "title": str(
            item.get("matchTitle")
            or ""
        ).strip(),
        "league": str(
            item.get("leagueName")
            or ""
        ).strip(),
        "booking": booking,
        "reserveButtonStatus": status,
        "scheduleId": schedule_id,
        "productId": str(
            item.get("productId")
            or ""
        ),
        "link": source.get("pageUrl", "")
    }

    event["id"] = (
        schedule_id
        or "|".join(
            [
                event["date"],
                event["time"],
                away,
                home,
                event["venue"]
            ]
        )
    )

    return event


def main():
    now = datetime.now(KST)
    end = now + timedelta(
        days=int(CONFIG.get("rangeDays", 92))
    )

    all_events = []
    source_status = []

    for source in CONFIG.get("sources", []):
        params = urllib.parse.urlencode(
            {
                "categoryId": source["categoryId"],
                "teamId": source["teamId"],
                "startDate": now.strftime("%Y%m%d"),
                "endDate": end.strftime("%Y%m%d")
            }
        )

        url = f"{API}?{params}"

        print("")
        print("=" * 70)
        print(f'구단: {source["team"]}')
        print(f"요청 주소: {url}")
        print("=" * 70)

        status = {
            "team": source["team"],
            "success": False,
            "count": 0,
            "checkedAt": datetime.now(KST).isoformat(
                timespec="seconds"
            ),
            "message": ""
        }

        try:
            payload = fetch_json(url)

            print(
                "최상위 키:",
                list(payload.keys())
                if isinstance(payload, dict)
                else type(payload)
            )

            schedules = find_schedules(payload)

            print(f"schedules 원본 건수: {len(schedules)}")

            # 구단별 원본 응답 저장
            debug_name = (
                "debug_"
                + str(source["teamId"])
                + ".json"
            )

            (ROOT / debug_name).write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf-8"
            )

            events = []
            seen = set()

            for item in schedules:
                if not isinstance(item, dict):
                    continue

                event = parse_item(item, source)

                if not event:
                    continue

                if event["id"] in seen:
                    continue

                seen.add(event["id"])
                events.append(event)

            all_events.extend(events)

            status["success"] = True
            status["count"] = len(events)
            status["message"] = (
                f"원본 {len(schedules)}건, "
                f"변환 {len(events)}건"
            )

            print(
                f'{source["team"]}: '
                f'원본 {len(schedules)}건 / '
                f'변환 {len(events)}건'
            )

        except Exception as exc:
            status["message"] = str(exc)

            print(
                f'{source["team"]}: 오류 - {exc}'
            )

        source_status.append(status)

    dedup = {}

    for event in all_events:
        key = (
            event.get("scheduleId")
            or event["id"]
        )

        dedup[key] = event

    events = sorted(
        dedup.values(),
        key=lambda event: (
            f'{event.get("date", "")}'
            f'T{event.get("time", "00:00")}'
        )
    )

    output = {
        "updatedAt": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "queryRange": {
            "startDate": now.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "rangeDays": int(
                CONFIG.get("rangeDays", 92)
            )
        },
        "sourceStatus": source_status,
        "events": events
    }

    (ROOT / "data.js").write_text(
        "window.SPORTS_DATA = "
        + json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        )
        + ";\n",
        encoding="utf-8"
    )

    print("")
    print(f"티켓링크 총 {len(events)}건 생성")


if __name__ == "__main__":
    main()
