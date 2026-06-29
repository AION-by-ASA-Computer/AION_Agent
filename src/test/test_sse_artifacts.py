import asyncio
import httpx
import json
import sys


async def test_sse_artifacts(prompt: str, profile: str = "Generic Assistant"):
    url = "http://localhost:8001/chat"
    payload = {
        "message": prompt,
        "session_id": "test_session_sse",
        "profile": profile,
        "attachments": [],
    }

    print(f"🚀 Sending request to {url}...")
    print(f"📝 Prompt: {prompt}")

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    print(f"❌ Error: {response.status_code}")
                    print(await response.aread())
                    return

                print("📡 Connection established. Listening to SSE stream...")
                artifact_detected = False
                text_buffer = ""

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    print(f"RAW: {line}")  # Debugging raw SSE lines
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            event_type = data.get("type")

                            if event_type == "text" or event_type == "token":
                                content = data.get("content", "")
                                text_buffer += content
                            elif event_type == "artifact_start":
                                artifact_detected = True
                                print(
                                    f"\n✨ ARTIFACT START: {data.get('artifact', {}).get('identifier')} ({data.get('artifact', {}).get('type')})"
                                )
                            elif event_type == "artifact_content":
                                pass
                            elif event_type == "artifact_end":
                                print(
                                    f"\n✅ ARTIFACT END: {data.get('artifact', {}).get('identifier')}"
                                )
                            elif event_type == "tool_event":
                                evt = data.get("event", {})
                                print(
                                    f"\n🛠 TOOL EVENT: {evt.get('type')} - {evt.get('name')}"
                                )
                            elif event_type == "error":
                                print(f"\n❌ AGENT ERROR: {data.get('content')}")
                        except Exception as e:
                            print(f"\n⚠️ Error parsing JSON: {e}")

                print("\n--- STREAM FINISHED ---")
                if artifact_detected:
                    print("✅ Artifact system worked as expected.")
                else:
                    print("❌ No artifacts detected in the stream.")
                    print("\nFull text response received:")
                    print("-" * 40)
                    print(text_buffer)
                    print("-" * 40)

    except Exception as e:
        print(f"❌ Connection failed: {e}")


if __name__ == "__main__":
    test_prompt = "Genera un file HTML completo per una landing page moderna di una startup robotica chiamata DroidX. Usa almeno 50 righe di codice ma massimo 200 righe."
    asyncio.run(test_sse_artifacts(test_prompt))
