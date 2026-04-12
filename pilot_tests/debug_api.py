"""Quick debug: inspect raw OpenAI Responses API output with web_search_preview."""
import os, json
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# search_context_size="high" encourages the model to search more aggressively
response = client.responses.create(
    model="gpt-4o",
    tools=[{"type": "web_search_preview", "search_context_size": "high"}],
    input="Search the web and tell me: What does ARHAUS INC (ARHS) do? Cite your sources.",
)

# Print full response structure
for i, item in enumerate(response.output):
    print(f"\n=== output[{i}] type={item.type} ===")
    if item.type == "web_search_call":
        print(f"  id={item.id}, status={item.status}")
    elif item.type == "message":
        for j, content in enumerate(item.content):
            print(f"  content[{j}] type={content.type}")
            if content.type == "output_text":
                print(f"  text (first 200 chars): {content.text[:200]}")
                print(f"  annotations count: {len(content.annotations) if hasattr(content, 'annotations') and content.annotations else 0}")
                if hasattr(content, 'annotations') and content.annotations:
                    for k, ann in enumerate(content.annotations):
                        print(f"    ann[{k}]: type={ann.type}, url={getattr(ann, 'url', 'N/A')}, title={getattr(ann, 'title', 'N/A')}")
    else:
        # dump everything
        print(f"  {item}")
