---
name: native-cpp-memory
description: Use this skill when diagnosing or correcting ownership, lifetime, or allocator defects in native C++ code.
metadata:
  version: "1.0.0"
---

# Native C++ Memory

Use current code and a causal reproducer before changing ownership.

## Gotchas

- `deleteLater` does not prove the receiving event loop will run.

## Troubleshooting

- Crash after thread shutdown -> trace object affinity and the final event-loop turn.
