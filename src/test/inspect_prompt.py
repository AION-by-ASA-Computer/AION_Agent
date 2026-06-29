import requests
import sys

def inspect_prompt(profile_name: str):
    url = f"http://localhost:8001/debug/prompt/{profile_name}"
    print(f"🔍 Inspecting prompt for profile: {profile_name}...")
    try:
        response = requests.get(url)
        if response.status_code == 200:
            prompt = response.json().get("prompt", "")
            print("-" * 50)
            print(prompt)
            print("-" * 50)
            
            # Checks
            if "aion_artifact" in prompt.lower():
                print("✅ Artifact Protocol DETECTED in prompt.")
            else:
                print("❌ Artifact Protocol MISSING from prompt.")
                
            if "core_protocol" in prompt.lower() or "regola" in prompt.lower():
                print("✅ Core Protocol rules DETECTED.")
            else:
                print("❌ Core Protocol rules MISSING.")
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    p_name = sys.argv[1] if len(sys.argv) > 1 else "Generic Assistant"
    inspect_prompt(p_name)
