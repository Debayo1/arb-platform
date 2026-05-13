import time
import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

# The URL of your PHP site (Change this when you move to live hosting)
# For local testing, use your ngrok or local network IP if possible, 
# or just print the output if testing purely locally without PHP server access.
PHP_API_URL = "http://localhost:8000/api/receive_odds.php"
API_KEY = "ARB_SECRET_KEY_12345"

def scrape_sportybet(page):
    print("[SportyBet] Fetching odds via Network Interception...")
    events_data = []
    
    # We will listen to all network responses
    def handle_response(response):
        try:
            # Look for API responses containing "factsCenter" or "events"
            if "factsCenter" in response.url and response.status == 200:
                data = response.json()
                if "data" in data and isinstance(data["data"], list):
                    # Sometimes sportybet returns a list of events directly in data
                    events_list = data["data"]
                elif "data" in data and "events" in data["data"]:
                    events_list = data["data"]["events"]
                else:
                    return

                for event in events_list:
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
        except:
            pass

    page.on("response", handle_response)
    
    try:
        page.goto("https://www.sportybet.com/ng/sport/football", wait_until="networkidle", timeout=30000)
        page.evaluate("window.scrollBy(0, 1000)")
        time.sleep(4)
    except Exception as e:
        print(f"[SportyBet] Goto Error ignored: {e}")
        
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

    # Deduplicate events
    unique_events = {e["home_team"] + e["away_team"]: e for e in events_data}
    return list(unique_events.values())

def scrape_bet9ja(page):
    print("[Bet9ja] Fetching odds via Network Interception...")
    events_data = []
    
    def handle_response(response):
        try:
            if "events/search" in response.url or "marketIds=1" in response.url or "prematch" in response.url:
                if response.status == 200:
                    data = response.json()
                    events_list = data.get("data", []) if "data" in data else data
                    if isinstance(events_list, dict) and "events" in events_list:
                        events_list = events_list["events"]
                        
                    for event in events_list:
                        home = event.get("homeTeam", {}).get("name") or event.get("home")
                        away = event.get("awayTeam", {}).get("name") or event.get("away")
                        start_str = event.get("startDateTime") or event.get("time")
                        if not home or not away or not start_str: continue
                        
                        try:
                            if "T" in str(start_str):
                                dt = datetime.strptime(str(start_str).split('.')[0], "%Y-%m-%dT%H:%M:%S")
                            else:
                                dt = datetime.fromtimestamp(int(start_str)/1000)
                        except:
                            continue
                        
                        odds = {}
                        for market in event.get("markets", []):
                            if str(market.get("marketId")) == "1" or market.get("name") == "1X2":
                                for outcome in market.get("outcomes", []):
                                    desc = str(outcome.get("type", outcome.get("name", ""))).lower()
                                    val = float(outcome.get("price", outcome.get("odds", 0)))
                                    if desc == "1": odds["home"] = val
                                    elif desc == "x": odds["draw"] = val
                                    elif desc == "2": odds["away"] = val
                                break
                                
                        if len(odds) == 3:
                            events_data.append({
                                "sport_id": 1,
                                "home_team": home,
                                "away_team": away,
                                "commence_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                "league": event.get("tournament", {}).get("name", "Unknown"),
                                "odds": {"bet9ja": odds}
                            })
        except:
            pass

    page.on("response", handle_response)
    
    try:
        # Bet9ja blocks HTTP/2 aggressively, but our launch args disable it.
        # Use sports.bet9ja.com as it's the direct sports app
        page.goto("https://sports.bet9ja.com/soccer", wait_until="domcontentloaded", timeout=30000)
        time.sleep(6) # Bet9ja takes a moment to load XHRs
    except Exception as e:
        print(f"[Bet9ja] Goto Error ignored: {e}")
        
    unique_events = {e["home_team"] + e["away_team"]: e for e in events_data}
    return list(unique_events.values())

def main():
    print(f"=== Starting Hybrid Scraper at {datetime.now()} ===")
    
    all_events = []
    
    with sync_playwright() as p:
        # Launch headless browser with anti-bot arguments
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-http2", # Bypasses HTTP/2 fingerprinting (fixes Bet9ja)
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--window-size=1920,1080"
            ]
        )
        # Use a realistic user agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True
        )
        page = context.new_page()
        
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
