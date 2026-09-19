import os
import traceback
from dotenv import load_dotenv
import anthropic

load_dotenv()

print("anthropic package version:", anthropic.__version__)
print("Key loaded:", "ANTHROPIC_API_KEY" in os.environ)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

try:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{"role": "user", "content": "Say hello in one word."}],
    )
    print("SUCCESS:", response.content[0].text)
except Exception as e:
    print("FAILED with exception type:", type(e).__name__)
    print("Full traceback:")
    traceback.print_exc()
