# Why

Hermes can exhaust its compressible history while a large protected tail still
exceeds the compression target. The current failure ends an otherwise valid
task with `Cannot compress further`; increasing the configured window would be
incorrect because the local backend's real ceiling is 131,072 tokens.
