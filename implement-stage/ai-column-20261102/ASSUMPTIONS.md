# Assumption ledger
ASK: never.
- A001 (semantic, user/official task): row state 0=PENDING,1=READY,2=FAILED; unfinished/failed results are NULL. Same-change columns publish together when terminal.
- A002 (interface, default): persist a dedicated JSON ai_column_info field in column schema and two native system tables; do not repurpose comments/default values.
- A003 (interface, default): task state 0=PENDING,1=RUNNING,2=STAGED_SUCCESS,3=RETRY,4=TERMINAL_FAILED. Request IDs and definition versions protect publication; worker uses a leased claim.
- A004 (semantic, user): user performs competition submission; implementer pushes reviewable code, never equates compilation with full test success.
