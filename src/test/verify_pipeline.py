import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_pipeline import get_pipeline
import time

def test_pipeline():
    print("--- Testing Chat Pipeline & Memory ---")
    pipeline = get_pipeline()
    
    # Use a unique session for testing
    session_id = f"test_{int(time.time())}"
    print(f"Session ID: {session_id}")
    
    # 1. First Message
    msg1 = "My name is Guido and I am testing memory."
    print(f"\nUser: {msg1}")
    result1 = pipeline.process_request(msg1, session_id=session_id)
    print(f"Agent: {result1['response']}")
    
    # 2. Verify DB Persistence for msg1
    history = pipeline.memory.get_history(session_id)
    assert len(history) >= 2, "History should have at least 2 messages (User + Assistant)"
    assert history[-2]['content'] == msg1, "Last user message should be in history"
    print("\n[OK] Message 1 persisted.")

    # 3. Second Message (Context Check)
    msg2 = "What is my name?"
    print(f"\nUser: {msg2}")
    result2 = pipeline.process_request(msg2, session_id=session_id)
    print(f"Agent: {result2['response']}")
    
    # 4. Simple string check to see if agent remembered
    # Note: Agent response might vary, but should contain "Guido".
    if "Guido" in result2['response']:
        print("\n[OK] Agent remembered the name!")
    else:
        print("\n[WARN] Agent might not have remembered using the exact string 'Guido'. Check response.")

    print("\n--- Test Completed ---")

if __name__ == "__main__":
    test_pipeline()
