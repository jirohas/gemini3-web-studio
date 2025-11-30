#!/usr/bin/env python3
"""
Clean empty sessions from chat_sessions.json
"""
import json
from pathlib import Path

# Path to sessions file
sessions_file = Path(__file__).parent / "chat_sessions.json"

# Load sessions
with open(sessions_file, "r", encoding="utf-8") as f:
    data = json.load(f)

sessions = data.get("sessions", [])

# Keep only sessions with messages OR that are non-empty
cleaned_sessions = []
for session in sessions:
    if session.get("messages") and len(session["messages"]) > 0:
        cleaned_sessions.append(session)

print(f"Original sessions: {len(sessions)}")
print(f"Cleaned sessions: {len(cleaned_sessions)}")

# Save cleaned sessions
data["sessions"] = cleaned_sessions
with open(sessions_file, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print("✅ Cleanup complete!")
