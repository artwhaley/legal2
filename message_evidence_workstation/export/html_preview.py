"""HTML export preview for workstation conversations (T21)."""

from __future__ import annotations

import html
from pathlib import Path

from message_evidence_workstation.domain.constants import (
    HIGHLIGHT_CONTEXT,
    HIGHLIGHT_HIT,
    HIGHLIGHT_RELEVANT,
)
from message_evidence_workstation.domain.models import OutputConversationContext, ProcessLogEntry
from message_evidence_workstation.output.display_states import messages_in_export_window
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


_STYLE = """
body { font-family: Georgia, serif; margin: 2rem; color: #111; }
h1, h2 { font-family: Arial, sans-serif; }
.meta { color: #444; margin-bottom: 1.5rem; }
.message { border-left: 4px solid #ddd; padding: 0.5rem 1rem; margin: 0.75rem 0; }
.message.hit { border-color: #1a7a1a; background: #f3fff3; font-weight: 700; }
.message.relevant { border-color: #1a4a7a; background: #f3f7ff; font-weight: 600; }
.message.context { border-color: #888; background: #f7f7f7; color: #444; }
.message.none { border-color: #eee; }
.timestamp { color: #666; font-size: 0.9rem; }
.sender { font-weight: 600; }
.boundary { color: #8a4b00; font-size: 0.85rem; text-transform: uppercase; }
.notes, .audit { margin-top: 2rem; white-space: pre-wrap; }
"""


def _state_class(state: str) -> str:
    if state == HIGHLIGHT_HIT:
        return "hit"
    if state == HIGHLIGHT_RELEVANT:
        return "relevant"
    if state == HIGHLIGHT_CONTEXT:
        return "context"
    return "none"


def render_conversation_html(
    context: OutputConversationContext,
    *,
    include_audit: bool = False,
    audit_entries: list[ProcessLogEntry] | None = None,
) -> str:
    conversation = context.conversation
    display_states = context.display_states or {}
    boundary_labels = context.boundary_labels or {}
    export_messages = messages_in_export_window(context.messages, context.conversation_range)
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>{html.escape(conversation.title)}</title>",
        f"<style>{_STYLE}</style>",
        "</head><body>",
        f"<h1>{html.escape(conversation.title)}</h1>",
        "<div class='meta'>",
        f"<div><strong>Category:</strong> {html.escape(context.category_name)}</div>",
        f"<div><strong>Source thread:</strong> {html.escape(context.thread_display_title)} "
        f"({html.escape(context.source_platform)} / {html.escape(conversation.source_thread_id)})</div>",
        f"<div><strong>Status:</strong> {html.escape(conversation.status)}</div>",
        f"<div><strong>Created by:</strong> {html.escape(conversation.created_by)}</div>",
        "</div>",
    ]
    for message in export_messages:
        state = display_states.get(message.message_id, "none")
        boundary = boundary_labels.get(message.message_id, "")
        boundary_html = (
            f"<div class='boundary'>{html.escape(boundary)}</div>" if boundary else ""
        )
        parts.append(
            f"<div class='message {_state_class(state)}'>"
            f"{boundary_html}"
            f"<div class='timestamp'>{html.escape(message.timestamp)}</div>"
            f"<div><span class='sender'>{html.escape(message.sender_display)}:</span> "
            f"{html.escape(message.body)}</div>"
            f"<div class='timestamp'>message_id={html.escape(message.message_id)}</div>"
            "</div>"
        )
    if conversation.user_notes.strip():
        parts.append(
            f"<h2>Notes</h2><div class='notes'>{html.escape(conversation.user_notes)}</div>"
        )
    if include_audit and audit_entries:
        parts.append("<h2>Audit appendix</h2><div class='audit'>")
        for entry in audit_entries[-50:]:
            parts.append(
                f"<div>[{html.escape(entry.timestamp)}] "
                f"{html.escape(entry.severity)} {html.escape(entry.component)}."
                f"{html.escape(entry.operation)}: {html.escape(entry.message)}</div>"
            )
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def write_conversation_html(
    context: OutputConversationContext,
    output_path: Path,
    logger: ProcessLogger,
    *,
    include_audit: bool = False,
    audit_entries: list[ProcessLogEntry] | None = None,
) -> int:
    html_text = render_conversation_html(
        context,
        include_audit=include_audit,
        audit_entries=audit_entries,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    size = output_path.stat().st_size
    logger.info(
        component="export.html_preview",
        operation="html_export_written",
        message=f"Wrote HTML preview to {output_path}",
        details={
            "workstation_conversation_id": context.conversation.workstation_conversation_id,
            "output_path": str(output_path),
            "bytes": size,
            "include_audit": include_audit,
        },
        dataset_id=context.conversation.dataset_id,
    )
    return size
