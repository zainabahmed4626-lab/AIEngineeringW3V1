"""Gradio UI for interactive testing of the multi-agent customer support stack.

Run from ``multi_agent_customer_support/`` (with ``.env`` configured)::

    python -m src.gradio_app

Uses the same :class:`RouterAgent` instance as ``src.main`` (in-process; no separate
FastAPI process required). For returns flows, run the returns A2A service on port 8081.
"""

from __future__ import annotations

import html
import json
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

# ``multi_agent_customer_support/`` (directory that contains the ``src`` package).
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


def _load_dotenv() -> None:
    """Load the first existing ``.env`` so the UI works from repo root or package dir."""
    for candidate in (_PKG_ROOT / ".env", _PKG_ROOT.parent / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            load_dotenv(candidate)
            return
    load_dotenv()


_load_dotenv()

import gradio as gr

from src.main import get_supabase_mcp_toolset, router_agent

# Match CLI: ensure MCP toolset singleton is initialized for this process.
_ = get_supabase_mcp_toolset()

# Prefer a seeded customer from schema_and_seed.sql so billing/support tools return data.
_DEFAULT_SEEDED = "ava.thompson@example.com"
DEFAULT_CUSTOMER = (os.getenv("CLI_CUSTOMER_ID") or _DEFAULT_SEEDED).strip() or _DEFAULT_SEEDED
RETURNS_URL = os.getenv("RETURNS_SERVICE_URL", "http://127.0.0.1:8081")

CUSTOM_CSS = """
.gradio-container { max-width: 1120px !important; margin-left: auto !important; margin-right: auto !important; }
footer { visibility: hidden; height: 0; }
.hero-wrap {
  border-radius: 14px;
  padding: 1.35rem 1.5rem 1.1rem;
  margin-bottom: 0.35rem;
  background: linear-gradient(135deg, rgba(79, 70, 229, 0.14) 0%, rgba(100, 116, 139, 0.10) 55%, rgba(14, 165, 233, 0.08) 100%);
  border: 1px solid rgba(148, 163, 184, 0.35);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}
.hero-title {
  font-size: 1.55rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  margin: 0 0 0.35rem 0;
  color: #0f172a;
}
.hero-sub {
  margin: 0;
  font-size: 0.95rem;
  color: #475569;
  line-height: 1.45;
}
.pill {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.pill-ok { background: rgba(34, 197, 94, 0.15); color: #166534; }
.pill-warn { background: rgba(234, 179, 8, 0.2); color: #854d0e; }
.answer-card {
  border-radius: 12px;
  padding: 1rem 1.15rem;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid #e2e8f0;
  min-height: 120px;
}
"""

THEME = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="slate",
    radius_size=gr.themes.sizes.radius_md,
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
)


def _escalation_pill(escalated: bool) -> str:
    if escalated:
        return '<span class="pill pill-warn">Escalated</span>'
    return '<span class="pill pill-ok">Not escalated</span>'


async def run_support_query(customer_id: str, message: str) -> tuple[str, str, str]:
    cid = (customer_id or "").strip() or DEFAULT_CUSTOMER
    msg = (message or "").strip()
    if not msg:
        empty = (
            '<div class="answer-card"><p style="margin:0;color:#64748b;">Type a message, then <strong>Send</strong>.</p></div>'
        )
        return empty, "", ""

    try:
        out = await router_agent.route_with_meta(cid, msg)
    except Exception as exc:
        detail = html.escape(str(exc), quote=True)
        tb = html.escape(traceback.format_exc(), quote=True)
        err_card = (
            '<div class="answer-card" style="border-color:#fecaca;background:#fef2f2;">'
            f'<p style="margin:0 0 0.5rem 0;color:#991b1b;"><strong>{html.escape(type(exc).__name__)}</strong>: {detail}</p>'
            f'<pre style="margin:0;font-size:0.78rem;white-space:pre-wrap;color:#7f1d1d;">{tb}</pre>'
            "</div>"
        )
        meta = (
            '<p style="color:#64748b;">Fix configuration (Supabase <code>.env</code>, API keys) or retry after rate limits. '
            f"Use a seeded email like <code>{html.escape(_DEFAULT_SEEDED)}</code> for billing/support.</p>"
        )
        raw = json.dumps({"error": type(exc).__name__, "message": str(exc)}, indent=2)
        return err_card, meta, raw
    route_label = str(out.routed_to or "—").replace("<", "&lt;")
    rationale = (out.rationale or "").strip()
    rationale_html = (
        f'<p style="margin:0.5rem 0 0 0;color:#475569;font-size:0.92rem;line-height:1.5;">{rationale}</p>'
        if rationale
        else '<p style="margin:0.35rem 0 0 0;color:#94a3b8;font-size:0.9rem;">No rationale returned.</p>'
    )

    answer_body = out.answer or ""
    # Escape minimal HTML in model output while preserving newlines.
    safe = (
        answer_body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    answer_html = f'<div class="answer-card"><div style="font-size:1.02rem;line-height:1.55;color:#0f172a;">{safe}</div></div>'

    meta_html = f"""<div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;margin-bottom:0.35rem;">
  {_escalation_pill(out.escalated)}
  <span style="color:#64748b;font-size:0.88rem;">Routed to <strong style="color:#334155;">{route_label}</strong></span>
</div>
{rationale_html}"""

    raw_json = (
        "{\n"
        f'  "result": {repr(out.answer)},\n'
        f'  "routed_to": {repr(out.routed_to)},\n'
        f'  "escalated": {out.escalated},\n'
        f'  "rationale": {repr(out.rationale)}\n'
        "}"
    )
    return answer_html, meta_html, raw_json


def build_app() -> gr.Blocks:
    with gr.Blocks(
        theme=THEME,
        css=CUSTOM_CSS,
        title="Customer Support — Multi-Agent",
    ) as demo:
        gr.HTML(
            f"""
<div class="hero-wrap">
  <p class="hero-title">Multi-agent customer support</p>
  <p class="hero-sub">
    Ask billing, support, or returns questions. Router + specialists use the same stack as the FastAPI API.
    Returns A2A target: <code style="background:rgba(148,163,184,0.25);padding:0.1rem 0.35rem;border-radius:6px;">{RETURNS_URL}</code>
  </p>
</div>
            """.strip()
        )

        with gr.Row():
            with gr.Column(scale=5):
                customer = gr.Textbox(
                    label="Customer ID",
                    placeholder="email or UUID from your seed data",
                    value=DEFAULT_CUSTOMER,
                    lines=1,
                )
                message = gr.Textbox(
                    label="Message",
                    placeholder="e.g. I was charged twice for my last order…",
                    lines=6,
                )
                with gr.Row():
                    submit = gr.Button("Send", variant="primary")
                    clear = gr.ClearButton([customer, message])

                gr.Examples(
                    label="Try an example",
                    examples=[
                        [_DEFAULT_SEEDED, "I was charged twice for my last order. Can you check my billing?"],
                        [_DEFAULT_SEEDED, "I want to return order ORD-2026-0008. Am I eligible for a refund?"],
                        [_DEFAULT_SEEDED, "My account was hacked, all my orders are gone, and nobody is helping me."],
                        [_DEFAULT_SEEDED, "Where is my open support ticket about shipping?"],
                    ],
                    inputs=[customer, message],
                )

            with gr.Column(scale=6):
                gr.Markdown("### Answer")
                answer_box = gr.HTML()
                gr.Markdown("### Routing & rationale")
                meta_box = gr.HTML()
                with gr.Accordion("Raw JSON (API shape)", open=False):
                    raw_box = gr.Code(language="json", lines=12, show_label=False)

        gr.Markdown(
            """
<div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #e2e8f0;color:#64748b;font-size:0.88rem;line-height:1.5;">
<strong>Tips:</strong> use a <strong>seeded customer email</strong> from your Supabase SQL (e.g. <code>ava.thompson@example.com</code>) so billing/support tools return rows.
Set <code>GEMINI_API_KEY</code> / <code>GOOGLE_API_KEY</code> in <code>.env</code>; if you hit <strong>429 quota</strong>, the app falls back to tool-only summaries where supported.
Run the returns service on port <strong>8081</strong> for A2A returns. Optional: <code>CLI_CUSTOMER_ID</code> defaults the customer field.
</div>
            """.strip()
        )

        _outs = [answer_box, meta_box, raw_box]
        _ins = [customer, message]
        submit.click(fn=run_support_query, inputs=_ins, outputs=_outs)
        message.submit(fn=run_support_query, inputs=_ins, outputs=_outs)

    return demo


def main() -> None:
    app = build_app()
    app.queue()
    _port_env = os.getenv("GRADIO_SERVER_PORT")
    # When unset, let Gradio pick a free port starting at 7860 (avoids OSError if 7860 is taken).
    server_port = int(_port_env) if _port_env else None
    app.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=server_port,
        show_error=True,
    )


if __name__ == "__main__":
    main()
