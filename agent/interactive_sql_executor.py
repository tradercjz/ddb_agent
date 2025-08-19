# FILE: ./agent/interactive_sql_executor.py

import json
import re
from typing import Generator, Dict, Any, List, Optional
from agent.prompts import interactive_sql_agent_prompt
from agent.tool_manager_enhanced import EnhancedToolManager
from rag.rag_entry import DDBRAG
from agent.task_status import TaskStart, TaskEnd, TaskError, ReactThought, ReactAction, ReactObservation
from utils.json_parser import parse_json_string
from llm.llm_prompt import normalize_history_for_llm

class InteractiveSQLExecutor:
    """
    Implements the PLAN/ACT loop for interactive SQL tasks.
    """
    def __init__(self, tool_manager: EnhancedToolManager, rag_system: DDBRAG):
        self.tool_manager = tool_manager
        self.rag = rag_system
        self.max_turns = 15
        
    def _parse_xml_response(self, text: str, known_tools: List[str]) -> Dict[str, Any]:
        """
        A robust regex-based parser that handles transitional text and specifically
        looks for known tool names.

        Args:
            text: The raw text response from the LLM.
            known_tools: A list of valid tool names that the parser should look for.

        Returns:
            A dictionary with 'thought' and 'action' (or None).
        """
        # 1. Extract and remove the thinking block first.
        thought_match = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else "No thought provided."
        
        # Create a "clean" string with the thinking block removed for tool searching
        text_without_thought = text[thought_match.end():] if thought_match else text

        # 2. Search for any of the known tool names in the remaining text.
        tool_name = None
        tool_match = None
        
        # We create a regex pattern like "(tool1|tool2|tool3)"
        tool_pattern = "|".join(re.escape(t) for t in known_tools)
        
        # Find the first occurrence of any known tool tag
        found_tool_match = re.search(f"<({tool_pattern})>", text_without_thought)

        if not found_tool_match:
            return {"thought": thought, "action": None}

        tool_name = found_tool_match.group(1)

        # 3. Once a valid tool is found, extract its full content block.
        action_content_match = re.search(f"<{re.escape(tool_name)}>(.*?)</{re.escape(tool_name)}>", text_without_thought, re.DOTALL)
        
        if not action_content_match:
            # This can happen if the closing tag is missing or malformed.
            return {"thought": thought, "action": None}

        action_content = action_content_match.group(1).strip()
        
        # 4. Parse parameters within the action block.
        params = {}
        param_pattern = r"<([a-zA-Z0-9_]+)>(.*?)</\1>"
        param_matches = re.findall(param_pattern, action_content, re.DOTALL)
        
        for name, value_str in param_matches:
            if name == 'options':
                # The LLM gives us a string that looks like a list. We need to parse it.
                # Using json.loads is safer than eval().
                try:
                    # First, try parsing it as a JSON array
                    parsed_value = json.loads(value_str.strip())
                    if isinstance(parsed_value, list):
                        params[name] = parsed_value
                    else:
                        # If it parses but isn't a list, treat as a single-item list
                        params[name] = [str(parsed_value)]
                except (json.JSONDecodeError, TypeError):
                    # If JSON parsing fails, fall back to a simple string split
                    # This handles cases like: "Option 1, Option 2"
                    params[name] = [opt.strip() for opt in value_str.split(',') if opt.strip()]
            else:
                params[name] = value_str.strip()
        
        return {
            "thought": thought,
            "action": {
                "tool_name": tool_name,
                "arguments": params
            }
        }
    
    def _format_tools_for_prompt(self, tool_defs: List[Dict[str, Any]]) -> str:
        prompt_lines = ["# Tools"]
        reverse_aliases = {v: k for k, v in self.tool_manager.tools.items()}
        for tool in tool_defs:
            name = tool.get("name")
            description = tool.get("description", "")
            prompt_tool_name = reverse_aliases.get(name, name)
            
            prompt_lines.append(f"## {prompt_tool_name}")
            prompt_lines.append(f"Description: {description}")
            
            params = tool.get("parameters", {}).get("properties", {})
            if params:
                prompt_lines.append("Parameters:")
                for param_name, schema in params.items():
                    # Map param names back for the prompt if needed (here we assume they match)
                    prompt_lines.append(f"- {param_name}: ({schema.get('type', 'any')}) {schema.get('description', '')}")
            prompt_lines.append("")
        return "\n".join(prompt_lines)
    
    

    def execute_task(self, user_input: str, agent, conversation_history: List[Dict]) -> Generator[Dict, None, List[Dict]]:
        yield TaskStart(task_description=user_input, message="🚀 Starting Interactive Analyst task...")
        
        try:
            if not conversation_history or conversation_history[-1].get("content") != user_input:
                 conversation_history.append({"role": "user", "content": user_input})
            
            history = conversation_history

            consecutive_errors = 0
            max_consecutive_errors = 5 
            turn_count = 0 

            while True:
                turn_count += 1
                if turn_count > self.max_turns: # 保留一个总轮次上限作为最终保险
                    yield TaskEnd(success=False, final_message=f"Task aborted: Exceeded maximum total turns ({self.max_turns}).", message="❌ Task failed: reached maximum total turns.")
                    return
                
                # 1. Build environment details
                current_mode = agent.get_interactive_mode()
                environment_details = f"""In each user message, the environment_details will specify the current mode. There are two modes:
    - ACT MODE: In this mode, you have access to all tools EXCEPT the plan_mode_response tool.
    - PLAN MODE: In this special mode, you have access to the plan_mode_response tool.
    Current Mode: {current_mode}"""
                
                # 2. Get and format available tools
                tool_defs_list = self.tool_manager.get_tool_definitions(mode=current_mode)
                tools_for_prompt = self._format_tools_for_prompt(tool_defs_list)

                reverse_aliases = {v: k for k, v in self.tool_manager.tools.items()}
                known_tool_names_for_prompt = [reverse_aliases.get(t['name'], t['name']) for t in tool_defs_list]

                # 3. Prepare file context
                available_files = """
    - file_name: kline
    description: 沪深日频K线行情数据 (Shanghai and Shenzhen daily K-line market data)
    Usage: select * from kline as kline;
    """
                normalized_history = normalize_history_for_llm(history)

                # 4. Call LLM with the complete, structured context
                response_generator = interactive_sql_agent_prompt(
                    conversation_history=normalized_history,
                    available_tools=tools_for_prompt,
                    environment_details=environment_details,
                    available_files=available_files,
                )
                
                llm_response = ""
                try:
                    while True: next(response_generator)
                except StopIteration as e:
                    llm_response = e.value.content

                # 5. Parse, yield thought, and update history
                parsed_response = self._parse_xml_response(llm_response, known_tool_names_for_prompt)
                thought = parsed_response["thought"]
                action = parsed_response.get("action")
                
                yield ReactThought(thought=thought, message=f"🤔 Thinking... (Turn {turn_count}, Mode: {current_mode})")
                history.append({"role": "assistant", "content": llm_response})

                if not action:
                    consecutive_errors += 1
                    observation = "Agent did not produce a valid action. Please analyze the history and decide the next step."
                    yield ReactObservation(observation=observation, is_error=True, message="🔍 Observing result...")
                    history.append({"role": "tool_result", "content": observation})
                    if consecutive_errors >= max_consecutive_errors:
                        yield TaskEnd(success=False, final_message=f"Task aborted after {max_consecutive_errors} consecutive errors. The agent was unable to proceed.", message="❌ Task failed: too many consecutive errors.")
                        return
                    continue

                tool_name = action["tool_name"]
                arguments = action["arguments"]

                # 6. Execute action and process result (logic remains the same as before)
                yield ReactAction(tool_name=tool_name, tool_args=arguments, message=f"🎬 Calling tool: {tool_name}")
                exec_result = self.tool_manager.call_tool(tool_name, arguments)
                
                is_error = not exec_result.success
                observation_content = ""
                
                if is_error:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        error_message = exec_result.error_message or "Unknown error."
                        yield TaskEnd(success=False, final_message=f"Task aborted after {max_consecutive_errors} consecutive errors. Last error:\n\n{error_message}", message="❌ Task failed: too many consecutive errors.")
                        return
                    error_message = exec_result.error_message or "An unknown error occurred."

                    # 不再向用户求助，而是将错误信息直接作为观察结果
                    # 这会迫使 LLM 在下一轮思考如何处理这个错误
                    observation_content = (
                        f"Action '{tool_name}' failed with the following error:\n\n"
                        f"```\n{error_message}\n```\n\n"
                        "I need to analyze this error and decide how to fix it. "
                        "I should use tools like `search_knowledge_base` or `get_function_documentation` to get more information before trying again."
                    )
                elif isinstance(exec_result.data, dict) and exec_result.data.get("_is_completion_signal"):
                    consecutive_errors = 0
                    final_payload = exec_result.data
                    yield ReactObservation(observation="Task completion signaled.", is_error=False, message="🔍 Observing result...")
                    yield TaskEnd(success=True, final_message=final_payload['result'], message="✅ Task completed successfully.")
                    return history
                elif isinstance(exec_result.data, dict) and exec_result.data.get("_is_interactive_request"):
                    consecutive_errors = 0
                    interaction_data = exec_result.data
                    user_choice = yield interaction_data
                    if user_choice: # Check if user_choice is not None
                        observation_content = f"User responded with: '{user_choice}'"
                        history.append({"role": "user", "content": user_choice})
                    else:
                        # This branch is now reachable if resumed by next() instead of send()
                        observation_content = "Resumed without user input. Continuing with current plan."
                else:
                    consecutive_errors = 0
                    try:
                        observation_content = json.dumps(exec_result.data, indent=2, ensure_ascii=False) if isinstance(exec_result.data, (dict, list)) else str(exec_result.data)
                    except TypeError:
                        observation_content = str(exec_result.data)

                yield ReactObservation(observation=observation_content, is_error=is_error, message="🔍 Observing result...")

                # 1. 创建上下文前缀，明确告诉模型这是哪个工具的结果
                tool_result_prefix = f"[{tool_name}] Result:"

                # 2. 准备环境详情
                current_mode = agent.get_interactive_mode()
                environment_details_content = f"""<environment_details>
                In each user message, the environment_details will specify the current mode. There are two modes:
                - ACT MODE: In this mode, you have access to all tools EXCEPT the plan_mode_response tool.
                - PLAN MODE: In this special mode, you have access to the plan_mode_response tool.
                Current Mode: {current_mode}
                </environment_details>"""

                # 3. 构建一个和成功日志完全一致的多部分 user 消息
                tool_result_message = {
                    "role": "user",
                    "content": [
                        # 部分 1: 上下文前缀
                        {"type": "text", "text": tool_result_prefix},
                        # 部分 2: 真实的工具输出
                        {"type": "text", "text": observation_content},
                        # 部分 3: 每次都附带的环境详情
                        {"type": "text", "text": environment_details_content}
                    ]
                }

                # 4. 将这个结构化的 user 消息添加到历史记录中
                history.append(tool_result_message)

            yield TaskEnd(success=False, final_message="Task failed to complete within the maximum number of turns.", message="❌ Task failed: reached maximum turns.")
        except Exception as e:
            import traceback
            traceback.print_stack()
            print(str(e))