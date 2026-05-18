from __future__ import annotations


def format_qa_failure_narrative(
    plan: dict | None,
    *,
    qa_report_relpath: str | None = None,
) -> str:
    """Format a QA report dict into markdown narrative for task.review_comment.

    Accepts model_dump() from QAReportDocument, or a dict loaded from qa_plan.json.
    Falls back to a static string when plan is None or unreadable.
    """
    if not plan:
        return "QA 验证失败（报告不可读）"

    status = plan.get("status", "failed")
    bugs = plan.get("bugs_found") or []
    gaps = plan.get("test_gaps") or []
    risks = plan.get("risks") or []
    commands = plan.get("commands_run") or []
    recommendation = plan.get("final_recommendation") or ""

    def bullets(items: list) -> list[str]:
        return [f"  - {x}" for x in items] if items else ["  （无）"]

    lines: list[str] = [
        f"QA 验证标记为 **{status}**。请在下次 QA 前修复以下每一项问题。",
        "",
    ]
    if recommendation:
        lines += [f"最终建议：{recommendation}", ""]
    lines.append("发现的缺陷：")
    lines.extend(bullets(bugs))
    lines += ["", "测试空白 / 框架注记："]
    lines.extend(bullets(gaps))
    lines += ["", "风险："]
    lines.extend(bullets(risks))
    lines += ["", "QA 实际执行的命令（含退出码）："]
    lines.extend(bullets(commands))
    if qa_report_relpath:
        lines += ["", f"完整 QA 报告：{qa_report_relpath}"]
    return "\n".join(lines)
