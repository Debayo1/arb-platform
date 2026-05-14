import time
import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

import os

# Production-ready configuration with environment variable fallbacks
PHP_API_URL = os.getenv("PHP_API_URL", "http://localhost:8000/api/receive_odds.php")
API_KEY = os.getenv("API_KEY", "ARB_SECRET_KEY_12345")

def normalize_team_name(name):
    if not name: return ""
    # Convert to lowercase and strip whitespace
    n = name.lower().strip()
    # Remove common suffixes/prefixes
    removals = [
        "fc", "fk", "afc", "sc", "rc", "u21", "u23", "u19", "u18", "women", "fem", 
        "youth", "reserve", "res.", "limited", "ltd", "city", "united", "town", 
        "hotspur", "wanderers", "athletic", "rovers", "albion", "county"
    ]
    for r in removals:
        # Match as whole word or at ends
        n = n.replace(f" {r}", "").replace(f"{r} ", "")
    
    # Remove special chars and punctuation
    import re
    n = re.sub(r'[^a-z0-9]', '', n)
    return n

def scrape_sportybet(page):
    print("[SportyBet] Fetching odds via Network Interception...")
    events_data = []
    
    def handle_response(response):
        url = response.url
        if "sportybet.com" in url and "api/" in url and "pcUpcomingEvents" in url:
            try:
                if response.status == 200:
                    data = response.json()
                    events_list = []
                    # Sportybet pcUpcomingEvents structure
                    if "data" in data and isinstance(data["data"], dict) and "tournaments" in data["data"]:
                        for tournament in data["data"]["tournaments"]:
                            if "events" in tournament:
                                events_list.extend(tournament["events"])
                    # Fallback structures
                    elif "data" in data and isinstance(data["data"], list):
                        events_list = data["data"]
                    elif "data" in data and "events" in data["data"]:
                        events_list = data["data"]["events"]
                    
                    if not events_list:
                        return

                    for event in events_list:
                        home = event.get("homeTeamName")
                        away = event.get("awayTeamName")
                        timestamp = event.get("estimateStartTime")
                        if not home or not away or not timestamp: continue
                        
                        dt = datetime.fromtimestamp(timestamp / 1000)
                        odds = {}
                        markets = event.get("markets", [])
                        for market in markets:
                            if market.get("id") == "1" or market.get("name") == "1X2" or market.get("desc") == "1X2":
                                for outcome in market.get("outcomes", []):
                                    desc = str(outcome.get("desc", "")).lower()
                                    val = float(outcome.get("odds", 0))
                                    if "home" in desc or desc == "1": odds["home"] = val
                                    elif "draw" in desc or desc == "x": odds["draw"] = val
                                    elif "away" in desc or desc == "2": odds["away"] = val
                                break
                        if len(odds) == 3:
                            events_data.append({
                                "sport_id": 1,
                                "home_team": home,
                                "away_team": away,
                                "commence_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                "league": event.get("tournament", {}).get("name", "Unknown"),
                                "odds": {"sportybet": odds}
                            })
            except:
                pass

    page.on("response", handle_response)
    
    try:
        # domcontentloaded is safer than networkidle for betting sites which are never truly "idle"
        page.goto("https://www.sportybet.com/ng/sport/football", wait_until="domcontentloaded", timeout=60000)
        # Give it 15 seconds to trigger the initial background API calls
        page.wait_for_timeout(15000)
        for _ in range(4):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(3000)
    except Exception as e:
        print(f"[SportyBet] Navigation/Wait Error: {e}")
        
    # Fallback: Extract from window.__INITIAL_STATE__ if interception found 0
    if not events_data:
        try:
            print("[SportyBet] Interception found 0 events, attempting DOM extraction fallback...")
            state = page.evaluate("window.__INITIAL_STATE__")
            if state and "match" in state:
                for event in state["match"].get("eventList", []):
                    home = event.get("homeTeamName")
                    away = event.get("awayTeamName")
                    timestamp = event.get("estimateStartTime")
                    if not home or not away or not timestamp: continue
                    
                    dt = datetime.fromtimestamp(timestamp / 1000)
                    odds = {}
                    for market in event.get("markets", []):
                        if market.get("name") == "1X2" or str(market.get("id")) == "1":
                            for outcome in market.get("outcomes", []):
                                desc = str(outcome.get("desc", "")).lower()
                                val = float(outcome.get("odds", 0))
                                if "home" in desc or desc == "1": odds["home"] = val
                                elif "draw" in desc or desc == "x": odds["draw"] = val
                                elif "away" in desc or desc == "2": odds["away"] = val
                            break
                    if len(odds) == 3:
                        events_data.append({
                            "sport_id": 1,
                            "home_team": home,
                            "away_team": away,
                            "commence_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "league": event.get("tournament", {}).get("name", "Unknown"),
                            "odds": {"sportybet": odds}
                        })
        except Exception as e:
            print(f"[SportyBet] Fallback parsing failed: {e}")

    # Deduplicate events using normalized names
    unique_events = {}
    for e in events_data:
        key = normalize_team_name(e["home_team"]) + "_" + normalize_team_name(e["away_team"])
        if key not in unique_events:
            unique_events[key] = e
    return list(unique_events.values())

def scrape_bet9ja(page):
    print("[Bet9ja] Fetching odds via Network Interception...")
    events_data = []
    
    def handle_response(response):
        url = response.url.lower()
        if "bet9ja" in url:
             if "api" in url or "get" in url or "palimp" in url or "highlights" in url:
                 print(f"  [DEBUG] Intercepted Bet9ja URL: {url[:80]}...")

        if ("bet9ja.com" in url or "apigw.bet9ja.com" in url) and ("GetEvents" in url or "Highlights" in url or "GetSports" in url or "Palimpsest" in url or "DailyBundle" in url):
            try:
                if response.status == 200:
                    data = response.json()
                    
                    found_in_payload = 0
                    
                    def process_event(event):
                        nonlocal found_in_payload
                        # Extract Teams
                        name = event.get("N") or event.get("DS", "")
                        if " - " in name:
                            parts = name.split(" - ", 1)
                            home = parts[0].strip()
                            away = parts[1].strip()
                        else:
                            home = event.get("homeTeam", {}).get("name") or event.get("home")
                            away = event.get("awayTeam", {}).get("name") or event.get("away")
                        
                        if not home or not away: return
                        if " - " not in name and len(home) < 2: return # Skip invalid

                        # Extract Time
                        start_str = event.get("D") or event.get("STARTDATE") or event.get("startDateTime") or event.get("time")
                        if not start_str: return
                        
                        try:
                            if "T" in str(start_str):
                                dt = datetime.strptime(str(start_str).split('.')[0], "%Y-%m-%dT%H:%M:%S")
                            elif ":" in str(start_str) and "-" in str(start_str):
                                dt = datetime.strptime(str(start_str), "%Y-%m-%d %H:%M:%S")
                            else:
                                dt = datetime.fromtimestamp(int(start_str)/1000)
                        except:
                            dt = datetime.now()
                        
                        # Odds extraction
                        odds_dict = event.get("O") or event.get("OD") or {}
                        keys_1 = ["S_1X2_1", "LIVES_1X2_1", "1X2_1"]
                        keys_X = ["S_1X2_X", "LIVES_1X2_X", "1X2_X"]
                        keys_2 = ["S_1X2_2", "LIVES_1X2_2", "1X2_2"]
                        
                        h_val = d_val = a_val = None
                        for k in keys_1:
                            val = odds_dict.get(k)
                            if val:
                                h_val = float(val.get("v") if isinstance(val, dict) else val)
                                break
                        for k in keys_X:
                            val = odds_dict.get(k)
                            if val:
                                d_val = float(val.get("v") if isinstance(val, dict) else val)
                                break
                        for k in keys_2:
                            val = odds_dict.get(k)
                            if val:
                                a_val = float(val.get("v") if isinstance(val, dict) else val)
                                break
                                
                        if h_val and d_val and a_val:
                            found_in_payload += 1
                            events_data.append({
                                "sport_id": 1,
                                "home_team": home,
                                "away_team": away,
                                "commence_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                "league": "Unknown",
                                "odds": {"bet9ja": {"home": h_val, "draw": d_val, "away": a_val}}
                            })

                    def find_events_recursive(obj):
                        if isinstance(obj, dict):
                            # If we find an "E" key, it's either a list or a dict of events
                            if "E" in obj:
                                e_data = obj["E"]
                                if isinstance(e_data, list):
                                    for item in e_data: process_event(item)
                                elif isinstance(e_data, dict):
                                    for item in e_data.values(): process_event(item)
                            
                            # Continue searching all other keys
                            for k, v in obj.items():
                                if k != "E": find_events_recursive(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                find_events_recursive(item)

                    find_events_recursive(data)
                    
                    if found_in_payload > 0:
                        print(f"  [Bet9ja] Intercepted {found_in_payload} events from {url[:60]}...")
            except Exception as e:
                pass

    page.on("response", handle_response)
    
    # Split navigation into separate try blocks so one timeout doesn't kill the whole run
    def safe_goto(url, timeout=90000):
        try:
            print(f"[Bet9ja] Visiting: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"[Bet9ja] Goto Timeout/Error (Continuing anyway): {e}")

    safe_goto("https://sports.bet9ja.com/soccer")
    
    safe_goto("https://sports.bet9ja.com/soccer/daily/today")

    # Scroll to trigger lazy loading - carefully check context
    try:
        for i in range(6):
            if page.is_closed(): break
            page.evaluate(f"window.scrollBy(0, {800 + i*400})")
            page.wait_for_timeout(4000)
    except: pass
        
    safe_goto("https://sports.bet9ja.com/live")
    page.wait_for_timeout(20000) 
        
    # Deduplicate events using normalized names
    unique_events = {}
    for e in events_data:
        key = normalize_team_name(e["home_team"]) + "_" + normalize_team_name(e["away_team"])
        if key not in unique_events:
            unique_events[key] = e
    return list(unique_events.values())

def main():
    print(f"=== Starting Hybrid Scraper at {datetime.now()} ===")
    
    all_events = []
    
    with sync_playwright() as p:
        # Launch headless browser with memory optimizations
        is_headless = os.getenv("HEADLESS", "true").lower() == "true"
        browser = p.chromium.launch(
            headless=is_headless,
            args=[
                "--disable-dev-shm-usage", # Crucial for Docker/Render
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-dev-tools",
                "--single-process", # Reduces memory
                "--js-flags='--max-old-space-size=256'" # Limits JS memory
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}, # Smaller viewport = less memory
            ignore_https_errors=True
        )
        page = context.new_page()

        # BLOCK IMAGES, CSS, AND MEDIA TO SAVE MEMORY
        def block_aggressively(route):
            if route.request.resource_type in ["image", "media", "font"]:
                route.abort()
            else:
                route.continue_()
        page.route("**/*", block_aggressively)
        
        # 1. Scrape SportyBet
        try:
            sporty_events = scrape_sportybet(page)
            print(f"[SportyBet] Found {len(sporty_events)} valid events.")
            all_events.extend(sporty_events)
        except Exception as e:
            print(f"[SportyBet] Error: {e}")
            
        # 2. Scrape Bet9ja
        try:
            bet9ja_events = scrape_bet9ja(page)
            print(f"[Bet9ja] Found {len(bet9ja_events)} valid events.")
            all_events.extend(bet9ja_events)
        except Exception as e:
            print(f"[Bet9ja] Error: {e}")
        
        browser.close()
        
    # Send data to PHP Backend
    if all_events:
        payload = {"events": all_events}
        print(f"Sending {len(all_events)} events to PHP Backend...")
        
        try:
            res = requests.post(
                PHP_API_URL, 
                json=payload,
                headers={"X-API-KEY": API_KEY, "Content-Type": "application/json"}
            )
            print(f"PHP Response [{res.status_code}]: {res.text}")
        except Exception as e:
            print(f"Failed to connect to PHP backend: {e}")
    else:
        print("No events found to send.")

if __name__ == "__main__":
    main()
