import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

from doova_one_view.api.agent.memory import SessionMemory

def test_memory():
    memory = SessionMemory()
    session_id = "test-session-123"
    
    print(f"Creating session {session_id}...")
    memory.add_turn(session_id, "Hello, how are you?", "I am your AI assistant.")
    
    print("Listing sessions...")
    sessions = memory.list_sessions()
    print(f"Found {len(sessions)} sessions.")
    for s in sessions:
        print(f" - {s['title']} ({s['turn_count']} turns)")
    
    print(f"Getting session {session_id}...")
    session = memory.get_session(session_id)
    if session:
        print(f"Session title: {session['title']}")
        print(f"Messages count: {len(session['messages'])}")
        for m in session['messages']:
            print(f"   [{m['role']}] {m['content']}")
    else:
        print("Session not found!")

    print(f"Deleting session {session_id}...")
    memory.delete_session(session_id)
    
    print("Done.")

if __name__ == "__main__":
    test_memory()
