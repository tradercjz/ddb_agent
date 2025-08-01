from typing import Dict
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, Label
from textual.containers import Vertical, Horizontal, VerticalScroll

class MCPEnvEditorScreen(ModalScreen[Dict[str, str]]):
    """一个用于编辑 MCP 服务器环境变量的模态框。"""

    def __init__(self, server_name: str, env_vars: Dict[str, str]):
        super().__init__()
        self.server_name = server_name
        self.env_vars = env_vars.copy()  # 使用副本进行编辑

    def compose(self) -> ComposeResult:
        with Vertical(id="env-editor-container", classes="modal-container"):
            yield Label(f"环境变量 for '{self.server_name}'", id="env-editor-title")
            
            with VerticalScroll(id="env-list"):
                # 为每个现有的环境变量创建一个编辑行
                for key, value in self.env_vars.items():
                    yield self.create_env_row(key, value)
            
            with Horizontal(classes="centered-row"):
                yield Button("+ 添加变量", id="add-env-var", variant="success")
            
            with Horizontal(id="env-editor-buttons"):
                yield Button("保存并重启", id="save-and-restart", variant="primary")
                yield Button("保存", id="save-only")
                yield Button("取消", id="cancel-edit")

    def create_env_row(self, key: str = "", value: str = "") -> Horizontal:
        """创建一个用于输入键值对的行。"""
        # 使用 "with" 语句或者直接在构造函数中传递子组件
        # 这是声明式的，而不是命令式的
        return Horizontal(
            Input(value=key, placeholder="变量名", classes="env-key-input"),
            Static("=", classes="env-separator"),
            Input(value=value, placeholder="变量值", password=True, classes="env-value-input"),
            Button("❌", classes="delete-env-btn"),
            classes="env-row"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-env-var":
            new_row = self.create_env_row()
            self.query_one("#env-list").mount(new_row)
            new_row.scroll_visible() 
        elif event.button.has_class("delete-env-btn"):
            # 删除所在的行
            event.button.parent.remove()
        elif event.button.id == "save-and-restart":
            self.save_and_exit(restart=True)
        elif event.button.id == "save-only":
            self.save_and_exit(restart=False)
        elif event.button.id == "cancel-edit":
            self.dismiss(None) # 返回 None 表示取消

    def save_and_exit(self, restart: bool):
        """收集所有输入，验证并返回结果。"""
        new_env_vars: Dict[str, str] = {}
        for row in self.query(".env-row"):
            key_input = row.query_one(".env-key-input", Input)
            value_input = row.query_one(".env-value-input", Input)
            key = key_input.value.strip()
            if key:  # 只保存有名称的变量
                new_env_vars[key] = value_input.value
        
        # 返回结果字典，其中包含一个特殊键来指示是否需要重启
        result = {"env": new_env_vars, "_restart": restart}
        self.dismiss(result)