"""Minimal cache-aware adapter pattern for any Python agent host."""

from aetnamem import Memory


memory = Memory("agent-memory.db")
subject_id = "user-42"  # Derive this from authenticated host identity.
query = "Which airport should I use?"

pack = memory.build_context_pack(subject_id, query, session_id="session-7")

# Pass these to the host's prompt builder; AetnaMem does not call the model.
stable_system_context = pack["stable_context"]
current_turn_context = pack["dynamic_context"]

print(stable_system_context)
print(current_turn_context)
