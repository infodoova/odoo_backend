import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("ANTHROPIC_API_KEY")
print(f"Testing key: {key[:15]}...{key[-5:]}")

client = Anthropic(api_key=key)

try:
    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[{"role": "user", "content": "hi"}]
    )
    print("Key is VALID!")
    print(message.content)
except Exception as e:
    print(f"Key is INVALID: {e}")
