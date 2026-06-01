"""DOM audit: action JSON nodes vs content-script selectors."""

from __future__ import annotations

from ..gemini_ui import audit_action_dom
from ..harness import connect, reload_extension, set_agent_active
from ..pipeline_assert import PipelineFailure


def run_dom_audit(port: int) -> None:
    sess = connect(port)
    try:
        reload_extension(sess)
        set_agent_active(sess)
        report = audit_action_dom(sess)
        print("DOM audit report:")
        for line in report.get("lines", []):
            print(f"  {line}")
        uncovered = report.get("uncoveredWithAction", [])
        if uncovered:
            raise PipelineFailure(
                "stage1",
                f"{len(uncovered)} node(s) with action JSON outside scanner selectors: "
                f"{uncovered[:2]}",
            )
        print("PASS dom_audit")
    finally:
        sess.close()
