import asyncio
import os
from putergenai import PuterClient

# Load credentials from env or hardcode for testing (since we know them from user prompt)
USERNAME = os.getenv("PUTER_USERNAME", "snslinered")
PASSWORD = os.getenv("PUTER_PASSWORD", "Akiyamasns123@")

async def test_login():
    print(f"Attempting login for user: {USERNAME}")
    try:
        async with PuterClient() as client:
            await client.login(USERNAME, PASSWORD)
            print("Login successful!")
            
            # Try a simple chat to verify
            result = await client.ai_chat(
                messages=[{"role": "user", "content": "Hello"}],
                options={"model": "claude-opus-4-5", "stream": False}
            )
            print("Chat result:", result)
    except Exception as e:
        print(f"Login failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_login())
