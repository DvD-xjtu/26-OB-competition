"""Render a native LLM's bounded scene plan against authoritative rule facts.

No model-authored natural language is displayed or persisted. The model selects
imagery, a historical callback and a suggested next action; Code renders their
meaning. An invalid plan fails before the HTTP save, rather than silently
pretending that a fixed response was a successful model run.
"""
import hashlib
import json

SCENES = {
    "brass": "黄铜灯罩映着细密的划痕，光晕像一枚旧硬币，在桌沿缓缓转动。",
    "ink": "账页上的墨色深浅相间，纸的纹路仿佛一条通向昨天的小路。",
    "rain": "窗影里浮着雨丝般的银线，远处的滴答声为这场旅程伴奏。",
    "shadow": "长短不一的钟影交叠在墙上，像几条尚未写完的故事线。",
}
MOTIFS = {
    "hands": "那些装饰钟的指针沿逆时针方向行进，怀表则只按实际消费倒走。",
    "sand": "装饰沙漏里的沙粒向上飘动，怀表的读数仍由时间账本决定。",
    "steam": "钟形壁画上的蒸汽仿佛正回到壶嘴，真实的时间收支仍记在账本里。",
    "chime": "装饰钟的报时音符倒着排列，怀表仍只随着已结算的消费转动。",
}


def render_story(plan_json: str, turn_prompt: str, state_json: str) -> dict:
    """Validate an LLM plan and render facts once for both save and display."""
    if not isinstance(plan_json, str) or len(plan_json) > 2000:
        raise ValueError("叙事计划格式错误，本轮尚未保存，请重试。")
    text = plan_json.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4].strip()
    try:
        plan = json.loads(text)
        context = json.loads(turn_prompt)
        state = json.loads(state_json)
    except (ValueError, TypeError):
        raise ValueError("模型未返回有效的叙事计划，本轮尚未保存，请重试。")
    keys = {"scene", "motif", "callback_turn", "next_choice"}
    if not isinstance(plan, dict) or set(plan) != keys:
        raise ValueError("模型计划包含未授权字段，本轮尚未保存。")
    if not isinstance(plan["scene"], str) or plan["scene"] not in SCENES:
        raise ValueError("模型场景不在允许范围，本轮尚未保存。")
    if not isinstance(plan["motif"], str) or plan["motif"] not in MOTIFS:
        raise ValueError("模型意象不在允许范围，本轮尚未保存。")
    if context["state"] != state or context["rules"]["branch"] == "guide":
        raise ValueError("叙事状态与本轮结算不一致，本轮尚未保存。")
    if state["minutes"] != 45 + state["earned"] - state["spent"]:
        raise ValueError("时间账本不平，本轮尚未保存。")
    rule = context["rules"]
    before = context["before"]
    if (state["turn"] != before["turn"] + 1
            or rule["minute_change"] != state["minutes"] - before["minutes"]
            or rule["cost"] != state["spent"] - before["spent"]
            or rule["income"] != state["earned"] - before["earned"]):
        raise ValueError("叙事收支与本轮结算不一致，本轮尚未保存。")
    last = state["events"][-1] if state["events"] else None
    bounded_outcome = rule["outcome"].encode("utf-8")[:600].decode("utf-8", errors="ignore")
    if not last or last["turn"] != state["turn"] or last["outcome"] != bounded_outcome:
        raise ValueError("叙事结论与本轮账页不一致，本轮尚未保存。")
    choices = context["available_choices"]
    choice = plan["next_choice"]
    if type(choice) is not int or not 0 <= choice < len(choices):
        raise ValueError("模型建议不在本轮可用行动中，本轮尚未保存。")
    past = {e["turn"]: e for e in state["events"] if e["turn"] < state["turn"]}
    callback = plan["callback_turn"]
    if type(callback) is not int or (callback != 0 and callback not in past):
        raise ValueError("模型引用了不存在的前情，本轮尚未保存。")
    parts = [SCENES[plan["scene"]] + MOTIFS[plan["motif"]]]
    if callback:
        # Explicit past tense: historical outcomes must never become current facts.
        event = past[callback]
        quoted = json.dumps(event["outcome"], ensure_ascii=False)
        parts.append("翻阅第 %d 轮账页，当时的记录是：%s。那是过去的记录；现在的结果与归属以下文为准。" % (callback, quoted))
    parts.append("本轮结算：" + context["rules"]["outcome"])
    parts.append("此刻你在%s，余额 %d 分钟，怀表 %02d:%02d。" % (
        state["location"], state["minutes"], state["clock"] // 60, state["clock"] % 60))
    # List each memory's CURRENT ownership, overriding even poisoned legacy prose.
    if state["memories"]:
        owned = [m for m in state["memories"] if m["status"] != "pledged"]
        pledged = [m for m in state["memories"] if m["status"] == "pledged"]
        def labels(items):
            return "、".join(json.dumps(m["label"], ensure_ascii=False) for m in items)
        if owned:
            parts.append("现在归你持有的记忆：%s；它们不在抵押柜中，无需再付赎回费。%s" % (
                labels(owned), "本次旅程已结束。" if state["closed"] else "今后主动回忆每次花 2 分钟，本句不产生额外收费。"))
        if pledged:
            parts.append("现在仍抵押的记忆：%s；%s" % (
                labels(pledged), "它们留在旅店，本次旅程已结束。" if state["closed"] else "赎回前无法回忆，可另行支付 25 分钟赎回一段。"))
    parts.append("随身物品：" + "、".join(state["inventory"]) + "。")
    if state["watch_name"]:
        parts.append("表盖刻字：" + json.dumps(state["watch_name"], ensure_ascii=False) + "。")
    parts.append("下一步可选（尚未执行）：" + choices[choice])
    story = "\n\n".join(parts)
    # Never truncate away a conclusion or ownership clarification.
    if len(story.encode("utf-8")) > 6000:
        raise ValueError("本轮叙事超过存储容量，本轮尚未保存。")
    audit = {
        "renderer": "bounded-plan-v1", "validated": True, "plan": plan,
        "state_turn": state["turn"], "balance": state["minutes"],
        "memory_statuses": {m["id"]: m["status"] for m in state["memories"]},
        "story_sha256": hashlib.sha256(story.encode("utf-8")).hexdigest(),
        "model_prose_used": False,
    }
    return {"story": story, "audit": json.dumps(audit, ensure_ascii=False, sort_keys=True)}
