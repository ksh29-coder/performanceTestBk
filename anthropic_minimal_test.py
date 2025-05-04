import os
from dotenv import load_dotenv
import anthropic
import asyncio

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path, override=True)

print("Loaded API Key:", os.getenv('ANTHROPIC_API_KEY'))


async def main():
    client = anthropic.AsyncAnthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    try:
        response = await client.messages.create(
            model="claude-3-7-sonnet-latest",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hello"}]
        )
        print("Response:", response)
    except Exception as e:
        print("Error:", e)

asyncio.run(main()) 