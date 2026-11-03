# Catalogue contract

SPEC-001: list_items(items, category=None) returns all original items when category is None, preserving order and leaving input unchanged.
SPEC-002: When category is supplied, return only items whose category equals that string. Matching is case-sensitive. An empty string is a valid category, not the absence of a filter. Missing category fields never match a string filter.
SPEC-003: An unknown category returns an empty list. Original item values must not be modified.

