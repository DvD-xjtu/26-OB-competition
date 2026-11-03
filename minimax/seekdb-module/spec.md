# seekdb module checker: literal conditional include filtering

Source: tools/module_check/unittest_module_check.py, iter_active_includes.
Existing contract: yield direct includes outside comments and literal #if 0 blocks, preserve line numbers. Existing unittest_module_check_test.py is retained unchanged.

SPEC-001: In a literal #if 0 conditional chain, #elif 0 remains disabled; #else becomes active only when no previous branch was taken.
SPEC-002: A literal #elif 1 activates its branch and disables subsequent #elif/#else branches in that chain.
SPEC-003: Nested conditionals inside a disabled parent never reactivate includes. Existing handling of unknown conditions must remain conservative: inspect potentially active branches.
SPEC-004: Keep the public API and existing regression suite passing; do not alter tests to obtain a pass.
