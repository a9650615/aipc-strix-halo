# Why

The local mem0 service (memory-mem0, port 7000) stores long-term memories
for every agent on the machine, but the only ways to inspect or prune them
are raw curl / psql — there is no human-facing management surface. The
Control Center portal (system-aipc-portal) is the designated local UI, so
memory browsing/search/deletion belongs there as a modular tab, per the
user's direct request (2026-07-11).
