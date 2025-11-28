from google.genai import types
import inspect

print("Fields in types.Tool:")
print(dir(types.Tool))

try:
    print("\nAttempting to create Tool with google_search:")
    t = types.Tool(google_search=types.GoogleSearch())
    print("Success!")
except Exception as e:
    print(f"Failed: {e}")

try:
    print("\nAttempting to create Tool with google_search_retrieval:")
    t = types.Tool(google_search_retrieval=types.GoogleSearchRetrieval())
    print("Success!")
except Exception as e:
    print(f"Failed: {e}")
