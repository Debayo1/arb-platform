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
    print("[SportyBet] Fetching odds...")
    events_data = []
    
    # We load the main page first to get cookies and bypass Cloudflare
    page.goto("https://www.sportybet.com/ng/sport/football", wait_until="domcontentloaded")
    time.sleep(3) # Wait for anti-bot checks
    
    # Now we hit the API endpoint directly using the browser's authorized context
    response = page.request.get("https://www.sportybet.com/api/ng/factsCenter/popularSportEvents?sportId=sr:sport:1&timeFilter=today&pageSize=50&pageNum=1")
    if response.ok:
        try:
            data = response.json()
            if "data" in data and "events" in data["data"]:
                events_list = data["data"]["events"]
                print(f"[SportyBet] Endpoint returned {len(events_list)} raw events.")
                for event in events_list:
                    home = event.get("homeTeamName")
                    away = event.get("awayTeamName")
                    timestamp = event.get("estimateStartTime")
                    if not home or not away or not timestamp:
                        continue
                        
                    dt = datetime.fromtimestamp(timestamp / 1000)
                    
                    # Find 1x2 market
                    odds = {}
                    for market in event.get("markets", []):
                        if market.get("name") == "1X2" or market.get("id") == "1":
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
                            "odds": {
                                "sportybet": odds
                            }
                        })
            else:
                print(f"[SportyBet] 'data' or 'events' missing. Keys found: {list(data.keys())}")
        except Exception as e:
            print(f"[SportyBet] JSON parse error: {e}")
    else:
        print(f"[SportyBet] Request failed! HTTP Status: {response.status}")
    return events_data

def scrape_bet9ja(page):
    print("[Bet9ja] Fetching odds...")
    events_data = []
    
    page.goto("https://sports.bet9ja.com/soccer", wait_until="domcontentloaded")
    time.sleep(3)
    
    response = page.request.get("https://sports-api.bet9ja.com/v3/sportsbook/events/search?sportId=1&marketIds=1&limit=50")
    if response.ok:
        try:
            data = response.json()
            events_list = data.get("data", [])
            print(f"[Bet9ja] Endpoint returned {len(events_list)} raw events.")
            
            for event in events_list:
                home = event.get("homeTeam", {}).get("name")
                away = event.get("awayTeam", {}).get("name")
                start_str = event.get("startDateTime")
                if not home or not away or not start_str: continue
                
                try:
                    dt = datetime.strptime(start_str.split('.')[0], "%Y-%m-%dT%H:%M:%S")
                except:
                    continue
                
                odds = {}
                for market in event.get("markets", []):
                    if market.get("marketId") == 1: # 1X2 market
                        for outcome in market.get("outcomes", []):
                            desc = str(outcome.get("type", "")).lower()
                            val = float(outcome.get("price", 0))
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
                        "odds": {
                            "bet9ja": odds
                        }
                    })
        except Exception as e:
            print(f"[Bet9ja] JSON parse error: {e}")
    else:
        print(f"[Bet9ja] Request failed! HTTP Status: {response.status}")
    return events_data

def main():
    print(f"=== Starting Hybrid Scraper at {datetime.now()} ===")
    
    all_events = []
    
    with sync_playwright() as p:
        # Launch headless browser
        browser = p.chromium.launch(headless=True)
        # Use a realistic user agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
