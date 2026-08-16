from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Protocol

from .domain import AssetUsage, Platform, PostDraft

IMAGE_URL_PLACEHOLDER = "{{IMAGE_URL}}"


@dataclass(frozen=True, slots=True)
class RenderedContent:
    platform: Platform
    title: str
    body: str
    content_type: str
    warnings: tuple[str, ...] = ()


class Renderer(Protocol):
    platform: Platform

    def render(self, draft: PostDraft) -> RenderedContent: ...


class WeChatRenderer:
    platform = Platform.WECHAT

    def render(self, draft: PostDraft) -> RenderedContent:
        usage = draft.image_usage[self.platform]
        body = _markdown_to_safe_wechat_html(draft.markdown)
        if usage in (AssetUsage.BODY, AssetUsage.BOTH):
            image = (
                '<p class="lsp-image"><img src="{{IMAGE_URL}}" '
                f'alt="{html.escape(draft.title, quote=True)}"></p>'
            )
            body = image + body
        return RenderedContent(
            platform=self.platform,
            title=draft.title,
            body=f'<section class="lsp-article">{body}</section>',
            content_type="text/html",
        )


class CsdnRenderer:
    platform = Platform.CSDN

    def render(self, draft: PostDraft) -> RenderedContent:
        usage = draft.image_usage[self.platform]
        body = draft.markdown.strip()
        if usage in (AssetUsage.BODY, AssetUsage.BOTH):
            image = f"![{_escape_markdown_alt(draft.title)}]({IMAGE_URL_PLACEHOLDER})"
            body = f"{image}\n\n{body}"
        return RenderedContent(
            platform=self.platform,
            title=draft.title,
            body=body,
            content_type="text/markdown",
        )


class RendererRegistry:
    def __init__(self, renderers: tuple[Renderer, ...] | None = None) -> None:
        selected = renderers or (WeChatRenderer(), CsdnRenderer())
        self._renderers = {renderer.platform: renderer for renderer in selected}

    def render_selected(self, draft: PostDraft) -> dict[Platform, RenderedContent]:
        missing = set(draft.platforms) - set(self._renderers)
        if missing:
            values = ", ".join(sorted(platform.value for platform in missing))
            raise ValueError(f"no renderer registered for: {values}")
        return {platform: self._renderers[platform].render(draft) for platform in draft.platforms}


_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_STRONG_RE = re.compile(r"\*\*([^*]+)\*\*")
_EMPHASIS_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_LINK_RE = re.compile(r"\[([^\]]+)]\((https?://[^\s)]+)\)")


def _inline_markup(value: str) -> str:
    escaped = html.escape(value, quote=True)
    escaped = _INLINE_CODE_RE.sub(r"<code>\1</code>", escaped)
    escaped = _STRONG_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _EMPHASIS_RE.sub(r"<em>\1</em>", escaped)
    escaped = _LINK_RE.sub(r'<a href="\2">\1</a>', escaped)
    return escaped


def _markdown_to_safe_wechat_html(markdown: str) -> str:
    """Render a deliberately small, deterministic Markdown subset.

    Unsupported syntax stays escaped text. JavaScript and raw HTML are never
    copied into the output.
    """

    output: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{'<br>'.join(paragraph)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            output.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items.clear()

    for raw_line in markdown.strip().splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        if line.startswith("### "):
            flush_paragraph()
            flush_list()
            output.append(f"<h3>{_inline_markup(line[4:])}</h3>")
        elif line.startswith("## "):
            flush_paragraph()
            flush_list()
            output.append(f"<h2>{_inline_markup(line[3:])}</h2>")
        elif line.startswith("# "):
            flush_paragraph()
            flush_list()
            output.append(f"<h1>{_inline_markup(line[2:])}</h1>")
        elif line.startswith(("- ", "* ")):
            flush_paragraph()
            list_items.append(_inline_markup(line[2:]))
        else:
            flush_list()
            paragraph.append(_inline_markup(line))

    flush_paragraph()
    flush_list()
    return "".join(output)


def _escape_markdown_alt(value: str) -> str:
    return value.replace("\\", "\\\\").replace("]", "\\]")
