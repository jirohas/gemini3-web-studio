import requests
import os

USERNAME = os.getenv("PUTER_USERNAME", "snslinered")
PASSWORD = os.getenv("PUTER_PASSWORD", "Akiyamasns123@")

def test_raw_full_flow():
    # 1. Login
    login_url = "https://puter.com/login"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://puter.com",
        "Referer": "https://puter.com/login",
        "Content-Type": "application/json"
    }
    
    print("Logging in...")
    resp = requests.post(login_url, json={"username": USERNAME, "password": PASSWORD}, headers=headers)
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} {resp.text}")
        return

    token = resp.json().get("token")
    print("Login successful.")

    # 2. Chat
    chat_url = "https://api.puter.com/drivers/call"
    auth_headers = headers.copy()
    auth_headers["Authorization"] = f"Bearer {token}"
    
    payload = {
        "interface": "puter-chat-completion",
        "driver": "claude",
        "method": "complete",
        "args": {
            "messages": [{"role": "user", "content": "Hello, who are you?"}],
            "model": "claude-opus-4-5",
            "stream": False
        }
    }

    print("Sending chat request...")
    chat_resp = requests.post(chat_url, json=payload, headers=auth_headers)
    print(f"Chat Status: {chat_resp.status_code}")
    print(f"Chat Response: {chat_resp.text[:500]}")

if __name__ == "__main__":
    test_raw_full_flow()
