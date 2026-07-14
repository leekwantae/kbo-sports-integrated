#!/usr/bin/env python3
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

TEAMS = {
    "bears": {"name": "두산 베어스", "pageUrl": "https://nol.yanolja.com/ticket/genre/sports/bears"},
    "heroes": {"name": "키움 히어로즈", "pageUrl": "https://nol.yanolja.com/ticket/genre/sports/heroes"},
}
OUT_FILE = Path("games.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

def download_page(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")

def decode_next_chunks(page: str) -> str:
    chunks = []
    pattern = re.compile(r'self\.__next_f\.push\(\[1,\s*("(?:\\.|[^"\\])*")\]\)', re.DOTALL)
    for match in pattern.finditer(page):
        try:
            chunks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    return page + "\n" + "\n".join(chunks)

def extract_goods_objects(text: str) -> list[dict]:
    text = html.unescape(text)
    decoder, games, seen = json.JSONDecoder(), [], set()
    candidate_texts = [text, text.replace(r'\"','"').replace(r'\/','/').replace(r'\\u0026','&')]
    for source in candidate_texts:
        start = 0
        while True:
            pos = source.find('{"goodsCode":"', start)
            if pos < 0:
                break
            try:
                obj, consumed = decoder.raw_decode(source[pos:])
            except json.JSONDecodeError:
                start = pos + 14
                continue
            if isinstance(obj, dict) and obj.get("goodsCode"):
                code = str(obj["goodsCode"])
                if code not in seen:
                    seen.add(code)
                    games.append(obj)
            start = pos + max(consumed, 1)
    return games

def simplify(game: dict, source_key: str) -> dict:
    sport = game.get("sport") or {}
    home = sport.get("homeOrganization") or {}
    away = sport.get("awayOrganization") or {}
    pre_sales = game.get("preSales") or []
    first_pre = pre_sales[0] if pre_sales else {}
    return {
        "sourceTeamKey": source_key,
        "sourceTeamName": TEAMS[source_key]["name"],
        "sourcePage": TEAMS[source_key]["pageUrl"],
        "goodsCode": game.get("goodsCode"),
        "goodsName": game.get("goodsName"),
        "playDate": sport.get("playDate") or game.get("playStartDate"),
        "playTime": sport.get("playTime"),
        "homeTeam": home.get("name"),
        "homeTeamCode": home.get("teamCode"),
        "awayTeam": away.get("name"),
        "awayTeamCode": away.get("teamCode"),
        "placeName": game.get("placeName"),
        "bookingOpenTime": game.get("bookingOpenTime"),
        "bookingEndTime": game.get("bookingEndTime"),
        "preBookingName": first_pre.get("preBookingKindName"),
        "preBookingOpenTime": first_pre.get("minBookingOpenTime"),
        "preBookingEndTime": first_pre.get("maxBookingEndTime"),
        "posterImageUrl": game.get("posterImageUrl"),
    }

def main():
    all_games, sources = [], []
    for key, info in TEAMS.items():
        page = download_page(info["pageUrl"])
        raw_games = extract_goods_objects(decode_next_chunks(page))
        if not raw_games:
            raise RuntimeError(f"{info['name']} 페이지에서 경기정보를 찾지 못했습니다.")
        team_games = [simplify(g, key) for g in raw_games]
        all_games.extend(team_games)
        sources.append({"key":key,"name":info["name"],"pageUrl":info["pageUrl"],"count":len(team_games)})

    unique = {str(g.get("goodsCode")): g for g in all_games}
    games = list(unique.values())
    games.sort(key=lambda g: (g.get("playDate") or "", g.get("playTime") or "", g.get("goodsCode") or ""))
    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "totalElements": len(games),
        "sources": sources,
        "games": games
    }
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"NOL 총 경기 {len(games)}건 저장 완료")

if __name__ == "__main__":
    main()
