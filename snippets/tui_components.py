from typing import Optional

from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea
from textual.containers import VerticalScroll
from textual.app import ComposeResult

from .snippet_model import Snippet
from .snippet_manager import SnippetManager


class SnippetEditorScreen(ModalScreen[bool]):
    """A modal screen for creating/editing a snippet."""

    def __init__(self, snippet_manager: SnippetManager, snippet_to_edit: Optional[Snippet] = None):
        super().__init__()
        self.snippet_manager = snippet_manager
        self.snippet_to_edit = snippet_to_edit
        self.initial_name = snippet_to_edit.name if snippet_to_edit else ""
        self.initial_content = snippet_to_edit.content if snippet_to_edit else ""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="snippet-editor-container"):
            yield Static("Snippet Name (this is the trigger keyword):", classes="label")
            yield Input(self.initial_name, placeholder="e.g., create_trade_table", id="snippet-name")
            yield Static("Description (optional):", classes="label")
            yield Input(
                self.snippet_to_edit.description if self.snippet_to_edit else "",
                placeholder="A short explanation", 
                id="snippet-description"
            )
            yield Static("Tags (comma-separated, optional):", classes="label")
            yield Input(
                ", ".join(self.snippet_to_edit.tags) if self.snippet_to_edit else "",
                placeholder="e.g., table, trade, sample", 
                id="snippet-tags"
            )
            yield Static("Snippet Content:", classes="label")
            text_area = TextArea(
                text=self.initial_content,
                language="python",
                id="snippet-content"
            )
            text_area.show_line_numbers = True
            yield text_area
            with Static(classes="horizontal-buttons"):
                yield Button("Save", variant="primary", id="save-snippet")
                yield Button("Cancel", id="cancel-snippet")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-snippet":
            name_input = self.query_one("#snippet-name", Input)
            desc_input = self.query_one("#snippet-description", Input)
            tags_input = self.query_one("#snippet-tags", Input)
            content_input = self.query_one("#snippet-content", TextArea)

            if not name_input.value.strip():
                # 可以添加一个错误通知
                return
            
            new_snippet = Snippet(
                name=name_input.value.strip(),
                description=desc_input.value.strip(),
                tags=[tag.strip() for tag in tags_input.value.split(',') if tag.strip()],
                content=content_input.text
            )
            
            if self.snippet_manager.add_or_update_snippet(new_snippet):
                self.app.bell()
                self.dismiss(True)
        elif event.button.id == "cancel-snippet":
            self.dismiss(False)