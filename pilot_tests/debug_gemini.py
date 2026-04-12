"""Debug: check Gemini grounding response structure."""
import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

grounding_tool = types.Tool(google_search=types.GoogleSearch())
config = types.GenerateContentConfig(tools=[grounding_tool])

response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents="Search the web: What does ARHAUS INC (ARHS) do?",
    config=config,
)

print("=== Text (first 300 chars) ===")
print(response.text[:300] if response.text else "(no text)")

print("\n=== Candidates ===")
for ci, cand in enumerate(response.candidates):
    print(f"  candidate[{ci}]")
    meta = cand.grounding_metadata
    if meta:
        print(f"  grounding_chunks: {len(meta.grounding_chunks) if meta.grounding_chunks else 0}")
        if meta.grounding_chunks:
            for j, chunk in enumerate(meta.grounding_chunks):
                print(f"    chunk[{j}]: {chunk}")
        print(f"  grounding_supports: {len(meta.grounding_supports) if meta.grounding_supports else 0}")
        if meta.grounding_supports:
            for j, sup in enumerate(meta.grounding_supports[:5]):
                print(f"    support[{j}]: {sup}")
        print(f"  search_entry_point: {meta.search_entry_point is not None}")
        print(f"  web_search_queries: {meta.web_search_queries}")
    else:
        print("  (no grounding_metadata)")
