"""Info builder for node help/information panels.

Extracted from ``base_node.py``; ``pynode.nodes.base_node`` re-exports
``Info`` so existing imports keep working.
"""

import html
from typing import List, Tuple


class Info:
    """
    Helper class for building node information/help content.
    Provides a simple Python interface instead of writing raw HTML.

    Usage:
        info = Info()
        info.add_text("Description of the node.")
        info.add_header("Inputs")
        info.add_bullet("Input 0:", "Description of input 0")
        info.add_bullet("Input 1:", "Description of input 1")
        info.add_header("Example")
        info.add_code("Node1 → Node2").add_text("with some explanation")

    The class automatically escapes text to prevent HTML injection.
    """

    def __init__(self):
        self._content: List[str] = []
        self._inline_buffer: List[str] = []

    def _escape(self, text: str) -> str:
        """Escape HTML special characters for security."""
        return html.escape(str(text))

    def _flush_inline(self):
        """Flush any inline content to a paragraph."""
        if self._inline_buffer:
            self._content.append(f'<p>{"".join(self._inline_buffer)}</p>')
            self._inline_buffer = []

    def add_text(self, text: str) -> 'Info':
        """Add a paragraph of text."""
        self._flush_inline()
        self._content.append(f'<p>{self._escape(text)}</p>')
        return self

    def add_header(self, text: str) -> 'Info':
        """Add a section header."""
        self._flush_inline()
        self._content.append(f'<h4>{self._escape(text)}</h4>')
        return self

    def add_bullet(self, label: str, text: str = '') -> 'Info':
        """
        Add a bullet point. If label and text provided, label is bold.
        Use add_bullets() to add multiple bullets as a list.
        """
        self._flush_inline()
        if text:
            self._content.append(f'<ul><li><strong>{self._escape(label)}</strong> {self._escape(text)}</li></ul>')
        else:
            self._content.append(f'<ul><li>{self._escape(label)}</li></ul>')
        return self

    def add_bullets(self, *items: Tuple[str, str]) -> 'Info':
        """
        Add multiple bullet points as a single list.
        Each item can be a string or a tuple of (label, text).

        Example:
            info.add_bullets(
                ("Input 0:", "Background image"),
                ("Input 1:", "Foreground image"),
            )
        """
        self._flush_inline()
        bullets = []
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                label, text = item
                bullets.append(f'<li><strong>{self._escape(label)}</strong> {self._escape(text)}</li>')
            else:
                bullets.append(f'<li>{self._escape(str(item))}</li>')
        self._content.append(f'<ul>{"".join(bullets)}</ul>')
        return self

    def add_code(self, code: str) -> 'Info':
        """Add inline code. Can be chained with text() for same line."""
        self._inline_buffer.append(f'<code>{self._escape(code)}</code>')
        return self

    def text(self, text: str) -> 'Info':
        """Add inline text (for chaining with code on same line)."""
        self._inline_buffer.append(f' {self._escape(text)}')
        return self

    def end(self) -> 'Info':
        """End the current inline sequence and flush to paragraph."""
        self._flush_inline()
        return self

    def __str__(self) -> str:
        """Convert to HTML string."""
        self._flush_inline()
        return ''.join(self._content)

    def __repr__(self) -> str:
        return f'Info({len(self._content)} elements)'
