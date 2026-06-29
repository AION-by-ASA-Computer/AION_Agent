# aion-client

```python
import asyncio
from aion_client import AionClient

async def main():
    c = AionClient("http://localhost:8001", "aion_...")
    conv = await c.create_conversation("aion_std", "user1")
    async for ev in c.chat_stream(conv["id"], "hello"):
        print(ev)

asyncio.run(main())
```
