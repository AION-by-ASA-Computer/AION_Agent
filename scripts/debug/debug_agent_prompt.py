import os
import sys
from pathlib import Path

# Setup path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.agent_profile import profile_manager
from src.main import get_agent
import asyncio


async def debug_prompt(profile_name: str):
    print(f"--- DEBUG PROMPT FOR PROFILE: {profile_name} ---")
    profile = profile_manager.get_profile(profile_name)
    if not profile:
        print(f"Profile {profile_name} not found.")
        return

    prompt = profile.generate_system_prompt(user_id="debug_user")
    print(prompt)
    print("--- END PROMPT ---")

    # Check if artifact_protocol is mentioned in the prompt
    if "artifact_protocol" in prompt or "aion_artifact" in prompt:
        print("\n✅ artifact_protocol is PRESENT in the system prompt.")
    else:
        print("\n❌ artifact_protocol is MISSING from the system prompt.")

    # Check skills list
    print(f"\nSkills configured for this profile: {profile.skills}")


if __name__ == "__main__":
    p_name = sys.argv[1] if len(sys.argv) > 1 else "Generic Assistant"
    asyncio.run(debug_prompt(p_name))
