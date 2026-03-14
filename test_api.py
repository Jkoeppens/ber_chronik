import os
from dotenv import load_dotenv
import anthropic

load_dotenv()

key = os.environ.get("ANTHROPIC_API_KEY", "")
print(f"API Key: {key[:8]}...{key[-4:] if len(key) > 12 else '(zu kurz)'}")

client = anthropic.Anthropic()

try:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        messages=[{"role": "user", "content": "Hallo"}],
    )
    print("✓ Erfolg!")
    print(f"  Antwort: {response.content[0].text}")
    print(f"  Tokens: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
except anthropic.AuthenticationError:
    print("✗ AuthenticationError – API Key ungültig oder fehlt")
except anthropic.PermissionDeniedError as e:
    print(f"✗ PermissionDeniedError – {e}")
except anthropic.RateLimitError as e:
    print(f"✗ RateLimitError – {e}")
except anthropic.APIStatusError as e:
    print(f"✗ APIStatusError {e.status_code} – {e.message}")
except Exception as e:
    print(f"✗ Unerwarteter Fehler: {type(e).__name__}: {e}")
