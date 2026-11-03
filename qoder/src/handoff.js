import { computeStats, ENTRY_TYPES } from "./domain.js";

const TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "Asia/Shanghai",
});

export function formatChinaTime(iso) {
  if (!iso) return "时间未知";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "时间未知";
  const parts = TIME_FORMATTER.formatToParts(date);
  const pick = (type) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}（UTC+8）`;
}

function oneLine(value) {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function code(value) {
  return `\`${String(value ?? "").replace(/`/g, "'")}\``;
}

function tableCell(value) {
  return oneLine(value).replace(/\|/g, "\\|") || "—";
}

export function memoryCitationLabel(entry) {
  const citation = entry?.citation;
  if (!citation) return "无可用记忆引用";
  return [
    `Memory ${code(`${citation.artifactId ?? "?"}@r${citation.artifactRevision ?? "?"}`)}`,
    `entry ${code(citation.entryId ?? "?")}`,
    `version ${code(citation.entryVersionId ?? "?")}`,
  ].join(" · ");
}

export function sourceCitationLabel(source) {
  if (!source) return "无可用 Source 证据";
  const digest = source.digest ? ` · ${code(source.digest)}` : "";
  const position = source.position ? ` · position ${source.position}` : "";
  return `Source ${code(source.sourceId ?? "?")}${position}${digest}`;
}

function entryLines(entries, emptyText, limit) {
  if (!entries.length) return [`- ${emptyText}`];
  const selected = limit ? entries.slice(0, limit) : entries;
  const lines = selected.map((entry) => {
    const parts = [
      `- **${formatChinaTime(entry.createdAt)}** ${oneLine(entry.text)}`,
      `  - 记忆引用：${memoryCitationLabel(entry)}`,
    ];
    if (entry.type === "link" && entry.source) {
      parts.push(`  - 来源证据：${sourceCitationLabel(entry.source)}`);
    }
    return parts.join("\n");
  });
  if (limit && entries.length > limit) {
    lines.push(
      `- 仅展示最近 ${limit} 条；其余 ${entries.length - limit} 条可在 PowerContext Scope 中继续检索。`,
    );
  }
  return lines;
}

function preparedSection(prepared) {
  const status = prepared?.status ?? "empty";
  const lines = [
    "## 六、PowerContext 准备上下文",
    "",
    `- 状态：${code(status)}`,
    "- 请求：`POST /v1/context/prepare`，`max_bytes = 8000`",
  ];

  if (status === "ready" && prepared?.content) {
    const fence = prepared.content.includes("```") ? "````" : "```";
    lines.push(
      "- 说明：以下内容由 PowerContext 返回，属于有界历史上下文；当前实验状态与最新记录优先。",
      "",
      `${fence}text`,
      prepared.content,
      fence,
    );
    return lines.join("\n");
  }

  if (status === "empty") {
    lines.push(
      "- 说明：PowerContext 返回 `empty`，该任务当前没有可用于准备的记忆上下文。",
    );
    return lines.join("\n");
  }

  lines.push(
    `- 说明：准备上下文未完成（${oneLine(prepared?.message || "未知原因")}）。摘要仍只使用本次从 PowerContext 读取的 Memory 与 Source，不使用本地替代数据。`,
  );
  return lines.join("\n");
}

export function composeHandoff({
  task,
  entries,
  sources,
  prepared,
  generatedAt = new Date().toISOString(),
  baseUrl,
  warnings = [],
}) {
  const stats = computeStats(entries);
  const decisions = entries.filter((entry) => entry.type === "decision");
  const observations = entries.filter((entry) => entry.type === "observation");
  const todos = entries.filter((entry) => entry.type === "todo");
  const links = entries.filter((entry) => entry.type === "link");

  const lines = [
    "# 实验续航 · 交接摘要",
    "",
    `> 任务：**${oneLine(task?.title || "未命名研究任务")}**  `,
    `> 生成时间：${formatChinaTime(generatedAt)}  `,
    `> PowerContext Scope：${code(task?.id || "?")}  `,
    `> PowerContext 端点：${code(baseUrl || "未配置")}  `,
    "> 数据来源：PowerContext HTTP API（Memory 记录 + Source 证据）  ",
    "> 本地副本：无。刷新、重启应用或开启新会话后，仍从 PowerContext 重新读取。",
    "",
    "## 一、研究概览",
    "",
    `- 研究摘要：${oneLine(task?.summary || "尚未补充研究摘要。")}`,
    `- 记录总数：${stats.total} 条`,
    `- 类型分布：实验观察 ${stats.observation} 条；研究决策 ${stats.decision} 条；下一步待办 ${stats.todo} 条；原始资料 ${stats.link} 条${stats.other ? `；其他 ${stats.other} 条` : ""}`,
    `- 最近记录：${stats.latestAt ? formatChinaTime(stats.latestAt) : "暂无记录"}`,
    `- Source 证据：${sources.length} 条`,
    "",
    "## 二、关键决策",
    "",
    ...entryLines(decisions, "尚未记录研究决策。", 12),
    "",
    "## 三、实验观察（最近 8 条）",
    "",
    ...entryLines(observations, "尚未记录实验观察。", 8),
    "",
    "## 四、下一步待办",
    "",
    ...entryLines(todos, "尚未记录下一步待办。", 20),
    "",
    "## 五、原始资料",
    "",
    ...entryLines(links, "尚未记录原始资料链接。", 20),
    "",
    preparedSection(prepared),
    "",
  ];

  if (warnings.length > 0) {
    lines.push("## 生成提示", "");
    for (const warning of warnings) {
      lines.push(`- ${oneLine(warning)}`);
    }
    lines.push("");
  }

  lines.push(
    "## 七、来源账本",
    "",
    "| 类型 | 标识 | 版本 / 摘要 |",
    "| --- | --- | --- |",
  );

  if (entries.length === 0) {
    lines.push("| — | — | 尚未写入 Memory 记录 |");
  } else {
    for (const entry of entries) {
      const citation = entry.citation;
      lines.push(
        `| Memory ${tableCell(ENTRY_TYPES[entry.type]?.label || entry.type)} | ${tableCell(
          citation ? `${citation.artifactId}@r${citation.artifactRevision}` : "无引用",
        )} | entry ${tableCell(citation?.entryId)} / version ${tableCell(
          citation?.entryVersionId,
        )} |`,
      );
    }
  }

  if (sources.length === 0) {
    lines.push("| Source | — | 尚未保存 Source 证据 |");
  } else {
    for (const source of sources) {
      lines.push(
        `| Source | ${tableCell(source.sourceId)} | position ${tableCell(
          source.position,
        )} / ${tableCell(source.digest || "摘要未知")} |`,
      );
    }
  }

  lines.push(
    "",
    "---",
    "",
    "由「实验续航 / Research Relay」生成。摘要依据生成时刻的 PowerContext 数据；`/v1/context/prepare` 返回的内容属于不可信历史上下文，请结合当前实验状态核验。",
    "",
  );

  return lines.join("\n");
}
