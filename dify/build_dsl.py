"""Build the portable Dify workflow from its Python game rules."""

from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
MODEL_PROVIDER = "langgenius/openai/openai"
MODEL_NAME = "gpt-4o-mini"
nodes = []
edges = []

PREPARE = """
import hashlib
import json
import re

def main(player, chapter, action, save_code, workflow_run_id):
    player = player.strip()
    chapter = chapter.strip()
    action = action.strip()
    resume = bool(save_code and save_code.strip())
    if not player or not chapter or not action:
        raise ValueError("请填写玩家、存档名和行动。")
    if resume:
        code = save_code.strip().lower()
        if not re.fullmatch(r"[a-f0-9]{32}", code):
            raise ValueError("请检查存档码：应为 32 位十六进制字符。")
    else:
        if not workflow_run_id:
            raise ValueError("Dify 未分配运行标识。")
        code = hashlib.sha256(("clockwork-save:" + workflow_run_id).encode()).hexdigest()[:32]
    routing_key = json.dumps([player, chapter, code], ensure_ascii=False, separators=(",", ":"))
    owner = "g2_" + hashlib.sha256(routing_key.encode()).hexdigest()[:48]
    storage_chapter = "clockwork-v2"
    return {
        "body": json.dumps(
            {"player": owner, "chapter": storage_chapter, "recall_query": action},
            ensure_ascii=False,
        ),
        "storage_player": owner,
        "storage_chapter": storage_chapter,
        "save_code": code,
        "resume": "yes" if resume else "no",
    }
""".strip()

RULES_WRAPPER = """

def main(player, chapter, action, recall_json, recall_status, resume):
    if recall_status != 200:
        raise ValueError("PowerContext 读取失败（HTTP %s）。" % recall_status)
    response = json.loads(recall_json)
    if response.get("error") or response.get("memory_status") not in ("ready", "empty"):
        raise ValueError("暂时无法读取存档，请稍后再试。")
    if resume == "yes" and not response.get("latest_turn"):
        return {
            "state_json": "",
            "branch": "guide",
            "rules_text": "未找到该存档。请核对玩家标识、存档名和存档码；开始新游戏时请留空存档码。",
            "system_prompt": "",
            "turn_prompt": "",
            "memory_json": "",
            "continuity_json": "",
            "action_id": "",
            "previous_turn": "",
        }
    return play_turn(player.strip(), chapter.strip(), action.strip(), recall_json)
""".rstrip()

ENCODE_SAVE = """
import json

def excerpt(text, limit):
    return text.encode()[:limit].decode(errors="ignore")

def main(player, chapter, action, story, state_json):
    story = story.strip()
    if not story:
        raise ValueError("掌柜没有返回剧情，本次未写入存档。")
    # The LLM contributes prose. The rule node is the only source of state.
    return {"body": json.dumps(
        {"player": player, "chapter": chapter, "action": excerpt(action.strip(), 900),
         "story": excerpt(story, 2500), "state": json.loads(state_json)},
        ensure_ascii=False,
    )}
""".strip()

RESULT = """
import json

def main(response, status):
    if status != 200:
        raise ValueError("本轮未保存（HTTP %s），请重新读取存档后重试。" % status)
    data = json.loads(response)
    if data.get("saved") is not True or not data.get("citation"):
        raise ValueError(data.get("error", "存档失败，请稍后重试。"))
    return {
        "story": data["story"],
        "citation": json.dumps(data["citation"], ensure_ascii=False),
    }
""".strip()


def node(node_id, kind, title, data, column, row=0):
    position = {"x": column * 310, "y": 220 + row * 240}
    nodes.append({
        "id": node_id, "type": "custom", "position": position,
        "positionAbsolute": position.copy(), "width": 244, "height": 100,
        "sourcePosition": "right", "targetPosition": "left",
        "data": {"type": kind, "title": title, "desc": "", "selected": False, **data},
    })


def link(source, target, handle="source"):
    by_id = {n["id"]: n for n in nodes}
    edges.append({
        "id": f"{source}-{handle}-{target}", "source": source, "target": target,
        "sourceHandle": handle, "targetHandle": "target", "type": "custom",
        "data": {
            "sourceType": by_id[source]["data"]["type"],
            "targetType": by_id[target]["data"]["type"],
            "isInIteration": False,
        },
    })


def code(node_id, title, variables, source, outputs, column):
    node(node_id, "code", title, {
        "code_language": "python3", "code": source,
        "variables": [
            {"variable": name, "value_selector": selector}
            for name, selector in variables.items()
        ],
        "outputs": {name: {"type": "string", "children": None} for name in outputs},
    }, column)


def http(node_id, title, route, encoded_by, column):
    node(node_id, "http-request", title, {
        "method": "post", "url": "{{#env.bridge_url#}}/" + route,
        "authorization": {"type": "api-key", "config": {
            "type": "bearer", "api_key": "{{#env.bridge_token#}}",
        }},
        "headers": "Content-Type:application/json",
        "params": "",
        "body": {"type": "json", "data": [
            {"id": "body", "key": "", "type": "text", "value": "{{#" + encoded_by + ".body#}}"},
        ]},
        "timeout": {"connect": 10, "read": 45, "write": 20},
        "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 1000},
        "ssl_verify": True,
    }, column)


def end(node_id, title, outputs, column, row=0):
    node(node_id, "end", title, {
        "outputs": [
            {"variable": name, "value_selector": selector}
            for name, selector in outputs.items()
        ],
    }, column, row)


node("start", "start", "进入倒走钟表旅店", {"variables": [
    {"variable": "player", "label": "玩家标识", "type": "text-input",
     "required": True, "max_length": 80, "options": []},
    {"variable": "chapter", "label": "故事存档名", "type": "text-input",
     "required": True, "max_length": 80, "options": []},
    {"variable": "save_code", "label": "存档码（新游戏留空）", "type": "text-input",
     "required": False, "max_length": 32, "options": [], "default": ""},
    {"variable": "action", "label": "行动（例如：观察怀表、典当记忆、买钥匙、进钟室）",
     "type": "paragraph", "required": True, "max_length": 1200, "options": []},
]}, 0)
code("prepare", "派发存档码并按行动检索", {
    "player": ["start", "player"], "chapter": ["start", "chapter"],
    "action": ["start", "action"], "save_code": ["start", "save_code"],
    "workflow_run_id": ["sys", "workflow_run_id"],
}, PREPARE, ["body", "storage_player", "storage_chapter", "save_code", "resume"], 1)
http("recall", "PowerContext 读取当前状态与相关记忆", "recall", "prepare", 2)

rules = (HERE / "game_rules.py").read_text(encoding="utf-8")
rules = rules.replace("def main(player:", "def play_turn(player:", 1)
code("rules", "结算账本、物品、怀表与房间规则", {
    "player": ["start", "player"], "chapter": ["start", "chapter"],
    "action": ["start", "action"], "recall_json": ["recall", "body"],
    "recall_status": ["recall", "status_code"],
    "resume": ["prepare", "resume"],
}, rules + RULES_WRAPPER, ["state_json", "branch", "rules_text", "system_prompt", "turn_prompt",
                           "memory_json", "continuity_json", "action_id", "previous_turn"], 3)

node("route", "if-else", "引导分支或继续剧情", {"cases": [{
    "case_id": "true", "logical_operator": "and", "conditions": [{
        "id": "guide-only", "varType": "string", "variable_selector": ["rules", "branch"],
        "comparison_operator": "is", "value": "guide",
    }],
}]}, 4)
end("help", "显示行动提示", {"guide": ["rules", "rules_text"]}, 5, -1)
node("narrate", "llm", "掌柜叙事", {
    "model": {"provider": MODEL_PROVIDER, "name": MODEL_NAME, "mode": "chat",
              "completion_params": {"temperature": 0.4, "max_tokens": 600}},
    "prompt_template": [
        {"role": "system", "text": "{{#rules.system_prompt#}}"},
        {"role": "user", "text": "{{#rules.turn_prompt#}}"},
    ],
    "context": {"enabled": False, "variable_selector": []},
    "vision": {"enabled": False},
    "variables": [],
}, 5)
code("encode_save", "编码已结算状态和剧情", {
    "player": ["prepare", "storage_player"], "chapter": ["prepare", "storage_chapter"],
    "action": ["start", "action"], "story": ["narrate", "text"],
    "state_json": ["rules", "state_json"],
}, ENCODE_SAVE, ["body"], 6)
http("save", "PowerContext 提交本轮账本", "remember", "encode_save", 7)
code("result", "确认写入与引用", {
    "response": ["save", "body"], "status": ["save", "status_code"],
}, RESULT, ["story", "citation"], 8)
end("end", "展示剧情、账本和存档码", {
    "story": ["result", "story"], "ledger": ["rules", "rules_text"],
    "save_code": ["prepare", "save_code"], "citation": ["result", "citation"],
}, 9)

for source, target in [
    ("start", "prepare"), ("prepare", "recall"), ("recall", "rules"), ("rules", "route"),
    ("narrate", "encode_save"), ("encode_save", "save"), ("save", "result"), ("result", "end"),
]:
    link(source, target)
link("route", "help", "true")
link("route", "narrate", "false")

dsl = {
    "app": {
        "name": "倒走钟表旅店 · 时间账本",
        "description": "用时间作货币，在倒走的旅店交易、开门与赎回记忆。Dify 结算规则并叙事，PowerContext 持久化。",
        "icon": "🕰️", "icon_background": "#E4FBCC", "mode": "workflow",
        "use_icon_as_answer_icon": False,
    },
    "kind": "app", "version": "0.3.0", "dependencies": [],
    "workflow": {
        "conversation_variables": [],
        "environment_variables": [
            {"id": "bridge-url", "name": "bridge_url", "value": "http://host.docker.internal:8766",
             "value_type": "string", "description": "PowerContext 桥接地址"},
            {"id": "bridge-token", "name": "bridge_token", "value": "",
             "value_type": "secret", "description": "与 BRIDGE_TOKEN 一致"},
        ],
        "features": {
            "file_upload": {"enabled": False}, "opening_statement": "",
            "retriever_resource": {"enabled": True}, "sensitive_word_avoidance": {"enabled": False},
            "speech_to_text": {"enabled": False}, "suggested_questions": [],
            "suggested_questions_after_answer": {"enabled": False}, "text_to_speech": {"enabled": False},
        },
        "graph": {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.6}},
    },
}

if __name__ == "__main__":
    (HERE / "clockwork-inn.yml").write_text(
        yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
