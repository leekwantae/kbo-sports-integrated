  from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads(
    (ROOT / "sources.json").read_text(encoding="utf-8")
)

KST = timezone(timedelta(hours=9), name="KST")


def ms_to_dt(value: Any):
    if value in (None, "", 0):
        return None

    try:
        number = int(value)

        # 초 단위 값이 들어온 경우 밀리초로 변환
        if number < 100_000_000_000:
            number *= 1000

        return datetime.fromtimestamp(
            number / 1000,
            KST
        )

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

        text = response.read().decode(
            "utf-8",
            errors="replace"
        )

        return json.loads(text)


def parse_item(
    item: dict[str, Any],
    source: dict[str, Any],
):
    game = ms_to_dt(
        item.get("scheduleDate")
    )

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
        if datetime.now(KST) >= reserve:
            booking = "예매중"
        else:
            booking = reserve.strftime(
                "%Y-%m-%d %H:%M"
            )
    else:
        booking = ""

    schedule_id = str(
        item.get("scheduleId")
        or ""
    )

    away = team_name(
        item.get("awayTeam")
    )

    home = team_name(
        item.get("homeTeam")
    )

    # 해당 구단의 홈경기만 사용
    source_team_id = str(
        source.get("teamId")
        or ""
    )

    home_team_id = str(
        (
            item.get("homeTeam")
            or {}
        ).get("teamId")
        or ""
    )

    if (
        source_team_id
        and home_team_id
        and source_team_id != home_team_id
    ):
        return None

    event = {
        "sport": source.get(
            "sport",
            "baseball"
        ),
        "team": source["team"],
        "date": game.strftime(
            "%Y-%m-%d"
        ),
        "time": game.strftime(
            "%H:%M"
        ),
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
        "reserveOpenDateTime": (
            reserve.strftime(
                "%Y-%m-%d %H:%M"
            )
            if reserve
            else ""
        ),
        "reserveButtonStatus": status,
        "scheduleId": schedule_id,
        "productId": str(
            item.get("productId")
            or ""
        ),
        "link": source.get(
            "pageUrl",
            ""
        ),
        "bookingSite": "티켓링크",
    }

    event["id"] = (
        schedule_id
        or "|".join(
            [
                event["date"],
                event["time"],
                away,
                home,
                event["venue"],
            ]
        )
    )

    return event


def main():
    all_events = []
    source_status = []

    for source in CONFIG.get(
        "sources",
        []
    ):
        status = {
            "team": source["team"],
            "success": False,
            "count": 0,
            "checkedAt": datetime.now(
                KST
            ).isoformat(
                timespec="seconds"
            ),
            "message": "",
        }

        try:
            # sources.json에 저장된 긴 URL 사용
            url = str(
                source.get("apiUrl")
                or ""
            ).strip()

            if not url:
                raise RuntimeError(
                    "sources.json에 apiUrl이 없습니다."
                )

            payload = fetch_json(url)

            schedules = (
                payload.get("data", {})
                .get("schedules", [])
            )

            if not isinstance(
                schedules,
                list
            ):
                raise RuntimeError(
                    "data.schedules 배열이 없습니다."
                )

            events = []
            seen = set()

            for item in schedules:
                if not isinstance(
                    item,
                    dict
                ):
                    continue

                event = parse_item(
                    item,
                    source
                )

                if not event:
                    continue

                if event["id"] in seen:
                    continue

                seen.add(
                    event["id"]
                )

                events.append(
                    event
                )

            all_events.extend(
                events
            )

            status["success"] = True
            status["count"] = len(
                events
            )
            status["message"] = (
                f"API 조회 성공: "
                f"원본 {len(schedules)}건, "
                f"홈경기 {len(events)}건"
            )

            print(
                f'{source["team"]}: '
                f'원본 {len(schedules)}건 / '
                f'홈경기 {len(events)}건'
            )

        except Exception as exc:
            status["message"] = str(
                exc
            )

            print(
                f'{source["team"]}: '
                f'실패 - {exc}'
            )

        source_status.append(
            status
        )

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
        ),
    )

    payload = {
        "updatedAt": datetime.now(
            KST
        ).isoformat(
            timespec="seconds"
        ),
        "sourceStatus": source_status,
        "events": events,
    }

    (ROOT / "data.js").write_text(
        "window.SPORTS_DATA = "
        + json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + ";\n",
        encoding="utf-8",
    )

    print(
        f"티켓링크 총 "
        f"{len(events)}건 생성"
    )


if __name__ == "__main__":
    main()
