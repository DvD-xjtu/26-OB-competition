# Assumptions (ASK never, effort lite)

- Semantic/user: one-factor memory-backed staging to reduce remaining build time; never skip final persistence or shift work outside timing.
- Interface/default: Linux SYS_memfd_create with MFD_CLOEXEC, fdopen in binary read/write mode; close failed fdopen descriptor and fall back to original tmpfile. Non-Linux stays tmpfile.
- Semantic/default: anonymous staging is per operation and closed on scope exit, never a cached previous graph. It may consume additional RAM; formal resource gates remain required. Graph/search/Recall settings unchanged.
- Semantic/default: host emulation tests exercise Linux control flow, not an actual Linux kernel syscall or ROCm runtime. Syntax checks do not establish end-to-end performance.
