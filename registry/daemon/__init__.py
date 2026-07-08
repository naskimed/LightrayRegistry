"""The single-writer persistent daemon (TECH_SPEC §5.3).

Threads: writer (the ONLY appender) · HTTP api (127.0.0.1:8377) · inbox poller ·
scheduler (jobs, conditionals, cycles, placebo classification, agent sessions) · heartbeat.
Kill switches: var/HALT (checked before EVERY dispatch), var/READONLY.
"""
