"""Verify seven observed cloud turns by exact local PowerContext citations.

The checks compare bytes, deterministic rule replay, and the bounded narrative
template. They are not an LLM semantic review or independent attestation of the
reported cloud node traces. This script never reads save codes and only sends
POWERCONTEXT_TOKEN, when configured, to http://127.0.0.1:8000.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import httpx

import game_rules
import narrative


BALANCES = (65, 65, 55, 43, 18, 16, 16)
LOCATIONS = ("门厅", "门厅", "门厅", "旧信室", "旧信室", "旧信室", "旅店外")
COSTS = (0, 0, 10, 12, 25, 2, 0)
PREFIX = "clockwork story choice consequence\n"
SUCCESS = {"succeeded", "success", "成功", "执行成功"}
PUBLIC_STATE_FIELDS = (
    "schema", "player", "chapter", "turn", "minutes", "earned", "spent", "clock",
    "location", "inventory", "watch_name", "memories", "visited", "events", "closed",
    "last_action_id",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_citation(value):
    citation = json.loads(value) if isinstance(value, str) else value
    if not isinstance(citation, dict):
        raise ValueError("Invalid citation")
    ref = citation.get("memory_ref")
    if not isinstance(ref, dict) or type(ref.get("revision")) is not int:
        raise ValueError("Invalid revision")
    for key in ("entry_id", "entry_version_id"):
        if not isinstance(citation.get(key), str):
            raise ValueError("Incomplete citation")
    # Keep only public reference fields; never serialize unrelated response data.
    return {"memory_ref": {k: ref[k] for k in ("family", "artifact_id", "revision")},
            "entry_id": citation["entry_id"], "entry_version_id": citation["entry_version_id"]}


def public_nodes(value):
    if isinstance(value, dict):
        value = [{"node_id": name, "status": status} for name, status in value.items()]
    if not isinstance(value, list):
        raise ValueError("Expected node statuses")
    nodes = []
    for item in value:
        if isinstance(item, str):
            parts = item.rsplit(None, 1)
            if len(parts) != 2:
                raise ValueError("Incomplete node status")
            item = {"name": parts[0], "status": parts[1]}
        if not isinstance(item, dict):
            raise ValueError("Invalid node status")
        name = item.get("node_id") or item.get("name") or item.get("title")
        status = item.get("status")
        if not isinstance(name, str) or not isinstance(status, str):
            raise ValueError("Incomplete node status")
        nodes.append({"node": name, "status": status})
    return nodes


def identify_plan(story, prompt, state_json):
    """Identify the finite plan, then regenerate and compare the entire story."""
    context = json.loads(prompt)
    paragraphs = story.split("\n\n")
    variants = [
        (scene, motif) for scene, opening in narrative.SCENES.items()
        for motif, detail in narrative.MOTIFS.items()
        if paragraphs[0] == opening + detail
    ]
    if len(variants) != 1:
        raise ValueError("Story does not start with a permitted template")
    callbacks = re.findall(r"^翻阅第 (\d+) 轮账页，当时的记录是：", story, re.M)
    if len(callbacks) > 1:
        raise ValueError("Ambiguous callback")
    callback = int(callbacks[0]) if callbacks else 0
    options = context["available_choices"]
    selected = [i for i, option in enumerate(options)
                if paragraphs[-1] == "下一步可选（尚未执行）：" + option]
    if len(selected) != 1:
        raise ValueError("Story does not end with a permitted next choice")
    scene, motif = variants[0]
    plan = {"scene": scene, "motif": motif, "callback_turn": callback, "next_choice": selected[0]}
    rendered = narrative.render_story(canonical(plan), prompt, state_json)
    return plan, rendered


def verify_turn(client, scope_id, public, run, expected_turn, previous):
    citation = parse_citation(run["citation"])
    nodes = public_nodes(run["node_statuses"])
    for key in ("action", "story", "ledger", "observed_at"):
        if not isinstance(run.get(key), str) or not run[key].strip():
            raise ValueError("Missing public turn field")
    response = client.post("/v1/memory/entries/get", json={"scope_id": scope_id, "citation": citation})
    response.raise_for_status()
    entry = response.json()
    text = entry["text"]
    if not isinstance(text, str) or not text.startswith(PREFIX):
        raise ValueError("Unexpected checkpoint envelope")
    checkpoint = json.loads(text[len(PREFIX):])
    state = checkpoint["state"]
    story = checkpoint["story"]
    action = checkpoint["action"]
    if not isinstance(story, str) or not isinstance(action, str):
        raise ValueError("Invalid checkpoint text")
    # The outer owner is a protected routing ID. Validate only the public state identity.
    game_rules.validate_state(state, public["player"], public["chapter"])
    replay = game_rules.main(
        public["player"], public["chapter"], run["action"],
        canonical({"latest_turn": previous, "history": "", "memory_status": "ready" if previous else "empty"}),
    )
    expected_state = json.loads(replay["state_json"])
    expected_rules = json.loads(replay["turn_prompt"])["rules"]
    status = "pledged" if expected_turn <= 4 else "redeemed"
    current_outcome = expected_rules["outcome"]
    events = state["events"]
    last_event = events[-1] if events else {}

    storage_checks = {
        "citation_exact": parse_citation(entry["citation"]) == citation,
        "entry_active": entry.get("state") == "active",
        "structured_game_envelope": checkpoint.get("game") == "clockwork-inn" and checkpoint.get("schema") == 2,
        "action_utf8_exact": action.encode("utf-8") == run["action"].encode("utf-8"),
        "story_utf8_exact": story.encode("utf-8") == run["story"].encode("utf-8"),
    }
    state_checks = {
        "public_turn_order": type(run.get("turn")) is int and run["turn"] == expected_turn,
        "state_turn": type(state["turn"]) is int and state["turn"] == expected_turn,
        "balance_expected": state["minutes"] == BALANCES[expected_turn - 1],
        "resource_conservation": state["minutes"] == 45 + state["earned"] - state["spent"],
        "full_state_matches_rule_replay": state == expected_state,
        "location_expected": state["location"] == LOCATIONS[expected_turn - 1],
        "closed_only_after_turn_seven": state["closed"] is (expected_turn == 7),
        "one_memory_with_expected_ownership": len(state["memories"]) == 1 and state["memories"][0]["status"] == status,
        "cost_expected": expected_rules["cost"] == COSTS[expected_turn - 1],
        "last_event_matches_current_outcome": last_event.get("turn") == expected_turn
        and last_event.get("outcome") == game_rules._bounded_text(current_outcome, 600),
        "public_ledger_exact": run["ledger"] == replay["rules_text"],
    }

    narrative_checks = {
        "contains_current_outcome": "本轮结算：" + current_outcome in story,
        "contains_current_location_balance_clock": "此刻你在%s，余额 %d 分钟，怀表 %02d:%02d。" %
        (state["location"], state["minutes"], state["clock"] // 60, state["clock"] % 60) in story,
    }
    owned = [m for m in state["memories"] if m["status"] != "pledged"]
    pledged = [m for m in state["memories"] if m["status"] == "pledged"]
    owned_lines = [p for p in story.split("\n\n") if p.startswith("现在归你持有的记忆：")]
    pledged_lines = [p for p in story.split("\n\n") if p.startswith("现在仍抵押的记忆：")]
    if owned:
        labels = "、".join(json.dumps(m["label"], ensure_ascii=False) for m in owned)
        claim = "现在归你持有的记忆：" + labels + "；它们不在抵押柜中，无需再付赎回费。"
        narrative_checks["owned_memory_has_current_no_redemption_claim"] = len(owned_lines) == 1 and owned_lines[0].startswith(claim)
    else:
        narrative_checks["no_spurious_current_owned_claim"] = not owned_lines
    if pledged:
        labels = "、".join(json.dumps(m["label"], ensure_ascii=False) for m in pledged)
        narrative_checks["pledged_memory_has_current_claim"] = len(pledged_lines) == 1 and pledged_lines[0].startswith("现在仍抵押的记忆：" + labels + "；")
    else:
        narrative_checks["no_current_pledge_claim_for_returned_memory"] = not pledged_lines
    if expected_turn == 6:
        label = state["memories"][0]["label"] if state["memories"] else ""
        narrative_checks["turn_six_recalls_returned_memory_for_two_minutes"] = (
            "本轮结算：花 2 分钟回忆“%s”。这段记忆仍归你所有。" % label in story
        )
    plan = None
    audit = None
    try:
        plan, rendered = identify_plan(story, replay["turn_prompt"], replay["state_json"])
        narrative_checks["full_story_matches_bounded_renderer_utf8"] = rendered["story"].encode("utf-8") == story.encode("utf-8")
        audit = json.loads(rendered["audit"])
    except (ValueError, KeyError, TypeError, IndexError):
        narrative_checks["full_story_matches_bounded_renderer_utf8"] = False
    nodes_check = bool(nodes) and all(n["status"].lower() in SUCCESS for n in nodes)
    llm_observed = any(n["node"] in ("narrate", "掌柜选择场景与前情")
                       and n["status"].lower() in SUCCESS for n in nodes)
    result = {
        "turn": expected_turn, "observed_at": run["observed_at"], "checked_at_utc": now(),
        "http_status": response.status_code, "powercontext_request_id": response.headers.get("X-PowerContext-Request-ID"),
        "citation": citation, "entry_version": entry.get("version"),
        "action_sha256_utf8": digest(action), "story_sha256_utf8": digest(story),
        "public_story_sha256_utf8": digest(run["story"]),
        "state_sha256": digest(canonical(state)), "expected_state_sha256": digest(canonical(expected_state)),
        "public_state": {key: state[key] for key in PUBLIC_STATE_FIELDS},
        "current_outcome": current_outcome,
        "recorded_node_statuses": nodes, "recorded_nodes_all_success": nodes_check,
        "recorded_native_llm_success": llm_observed,
        "storage_exact_checks": storage_checks, "storage_exact_pass": all(storage_checks.values()),
        "deterministic_state_checks": state_checks, "deterministic_state_pass": all(state_checks.values()),
        "bounded_template_checks": narrative_checks, "bounded_template_pass": all(narrative_checks.values()),
        "inferred_plan": plan, "locally_recomputed_renderer_audit": audit,
    }
    return result, checkpoint


def verify_all(client, scope_id, public):
    runs = public["runs"]
    results = []
    previous = None
    for number, run in enumerate(runs, 1):
        try:
            result, previous = verify_turn(client, scope_id, public, run, number, previous)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as error:
            # Never copy an exception's text, HTTP body, headers, or credentials into evidence.
            result = {"turn": number, "checked_at_utc": now(), "error_type": type(error).__name__,
                      "storage_exact_pass": False, "deterministic_state_pass": False,
                      "bounded_template_pass": False, "recorded_nodes_all_success": False,
                      "recorded_native_llm_success": False}
            if isinstance(error, httpx.HTTPStatusError):
                result["http_status"] = error.response.status_code
        results.append(result)
    revisions = [r["citation"]["memory_ref"]["revision"] for r in results if "citation" in r]
    ordered = len(revisions) == 7 and all(b > a for a, b in zip(revisions, revisions[1:]))
    summary = {key: len(results) == 7 and all(r[key] for r in results)
               for key in ("storage_exact_pass", "deterministic_state_pass", "bounded_template_pass",
                           "recorded_nodes_all_success", "recorded_native_llm_success")}
    summary["citation_revisions_strictly_increase"] = ordered
    return {
        "checked_at_utc": now(), "scope_id": scope_id,
        "endpoint": "http://127.0.0.1:8000/v1/memory/entries/get",
        "verification_method": {
            "storage": "Exact UTF-8 action/story comparison at the supplied PowerContext citations.",
            "state": "Production rule replay, full JSON-state equality, and explicit seven-turn expected balances/ownership.",
            "narrative": "Exact bounded-renderer reproduction and current-ownership template checks. No LLM semantic judge was used.",
            "cloud_execution": "Node statuses are supplied observations. This script does not independently attest native LLM invocation or token usage.",
            "redaction": "No save code, transport owner, API credential, raw HTTP response, or environment dump is included.",
        },
        "source_sha256": {name: digest((Path(__file__).parent / name).read_text(encoding="utf-8"))
                          for name in ("game_rules.py", "narrative.py")},
        "summary": summary, "all_checks_pass": all(summary.values()), "runs": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope_id", help="Exact observed PowerContext scope ID")
    parser.add_argument("runs", type=Path, help="New-version public-runs.json with seven turns")
    parser.add_argument("--output", type=Path, help="Defaults to cloud-evidence-verification.json beside the input")
    args = parser.parse_args()
    if not re.fullmatch(r"scp_[a-z0-9]{1,80}", args.scope_id):
        parser.error("Invalid PowerContext scope ID")
    try:
        public = json.loads(args.runs.read_text(encoding="utf-8-sig"))
        if not isinstance(public, dict) or not isinstance(public.get("runs"), list) or len(public["runs"]) != 7:
            raise ValueError()
        if public.get("scope_id") != args.scope_id:
            raise ValueError()
        if any(not isinstance(public.get(k), str) or not 1 <= len(public[k]) <= 80 for k in ("player", "chapter")):
            raise ValueError()
    except (OSError, ValueError):
        parser.error("Expected seven runs plus matching scope_id, public player and chapter")
    token = os.getenv("POWERCONTEXT_TOKEN")
    headers = {"Authorization": "Bearer " + token} if token else {}
    with httpx.Client(base_url="http://127.0.0.1:8000", headers=headers, timeout=15, trust_env=False) as client:
        evidence = verify_all(client, args.scope_id, public)
    output = args.output or args.runs.with_name("cloud-evidence-verification.json")
    if output.resolve() == args.runs.resolve():
        parser.error("Output must differ from the observed input record")
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": evidence["all_checks_pass"],
                      "summary": evidence["summary"], "checked_turns": len(evidence["runs"])},
                     ensure_ascii=True))
    return 0 if evidence["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
