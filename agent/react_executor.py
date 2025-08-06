# file: ddb_agent/agent/react_executor.py

import json
from typing import Generator, Dict, Any, List
from agent.prompts import generate_final_user_answer, react_agent_prompt
from agent.tool_manager_enhanced import EnhancedToolManager
from rag.rag_entry import DDBRAG
from agent.task_status import ReactThought, ReactAction, ReactObservation, TaskStart, TaskEnd, TaskError
from utils.json_parser import parse_json_string
from agent.execution_result import ExecutionResult

class ReActExecutor:
    """
    Implements the Reason-Act (ReAct) agentic loop, integrating thought,
    action, and observation into a dynamic, iterative process.
    """
    def __init__(self, tool_manager: EnhancedToolManager, rag_system: DDBRAG):
        self.tool_manager = tool_manager
        self.rag = rag_system
        self.max_turns = 10  # Prevent infinite loops

    def execute_task(
        self,
        task_description: str
    ) -> Generator[Dict, None, Dict[str, Any]]:
        """
        Executes a task using the ReAct loop.

        Args:
            task_description: The user's primary goal for this task.
            conversation_history: The long-term history from the SessionManager.

        Yields:
            Status updates for the TUI.

        Returns:
            The final message to be added to the session history.
        """
        yield TaskStart(
            task_description=task_description,
            message="🚀 Starting ReAct task..."
        )

        local_react_loop_history: List[Dict[str, str]] = []
        task_execution_summary: List[Dict[str, Any]] = []
        
        # The conversation_history from SessionManager already contains the summary
        available_tools = json.dumps(self.tool_manager.get_tool_definitions(), indent=2)

        #rag_context_docs = list(self.rag.retrieve(task_description))
        rag_context = ""

        for i in range(self.max_turns):
            # 1. Reason: Call LLM to get the next thought and action
            # The full session history is passed to provide long-term context
            llm_response_content = self._get_llm_decision(
                task_description, local_react_loop_history, available_tools, rag_context
            )
            
            try:
                parsed_json = parse_json_string(llm_response_content)
                thought = parsed_json.get("thought", "Agent did not provide a thought.")
                action = parsed_json.get("action")
            except Exception as e:
                yield TaskError(message="Failed to parse LLM response.", error_details=str(e))
                return {"role": "assistant", "content": f"Critical Error: Could not parse LLM response. Details: {e}"}

            yield ReactThought(thought=thought, message=f"🤔 Thinking... (Turn {i+1})")

            task_execution_summary.append({"thought": thought})
            
            # 2. Check for Termination: If action is null, the task is done.
            if action is None:
                # Agent 认为它完成了，现在我们接管并生成最终的总结
                yield ReactThought(thought=thought, message="🤔 Agent finished thinking. Synthesizing final answer...")
                
                # 调用新的总结 prompt
                summary_generator = generate_final_user_answer(
                    task_description=task_description,
                    execution_history=local_react_loop_history,
                    final_thought=thought
                )
                
                # 从生成器中获取最终的、润色过的答案
                final_answer = ""
                try:
                    while True:
                        next(summary_generator)
                except StopIteration as e:
                    final_answer = e.value.content

                if not final_answer:
                    # 如果总结失败，则退回到使用原始的 thought
                    final_answer = thought

                yield TaskEnd(success=True, final_message=final_answer, final_script=None, message="✅ Task completed successfully.", )
                
                return final_answer, task_execution_summary
            
            # 3. Act: Execute the tool call
            tool_name = action.get("tool_name")
            arguments = action.get("arguments", {})
            task_execution_summary.append({"action": action})

            if not tool_name:
                observation = "Error: No tool_name was provided in the action."
                is_error = True
            else:
                yield ReactAction(tool_name=tool_name, tool_args=arguments, message=f"🎬 Calling tool: {tool_name}")
                exec_result = self.tool_manager.call_tool(tool_name, arguments)
                
                # 4. Observe: Format Result 
                if exec_result.success:
                    data = exec_result.data
                    if data is None: observation = "Tool executed successfully with no output."
                    elif isinstance(data, (list, dict)) and not data: observation = f"Tool '{tool_name}' returned an empty result."
                    elif isinstance(data, bool): observation = f"Tool '{tool_name}' returned the boolean value: {data}."
                    else: observation = str(data)
                    is_error = False
                else:
                    observation = f"Tool '{tool_name}' failed with an error: {exec_result.error_message}"
                    is_error = True

            #if len(observation) > 2500:
            #    observation = observation[:2500] + "\n\n... (Observation was truncated)"
            
            yield ReactObservation(observation=observation, is_error=is_error, message="🔍 Observing result...")
            task_execution_summary.append({"observation": observation})

            # 5.Update history in the format the prompt's template expects.
            local_react_loop_history.append({
                "thought": thought,
                "action_str": json.dumps(action, indent=2),
                "observation": observation,
            })

        # Loop finished without completion
        final_answer = "Task failed to complete within the maximum number of turns."
        yield TaskEnd(success=False, final_message=final_answer, final_script=None,message="❌ Task failed: reached maximum turns.", )
        return final_answer, task_execution_summary

    def _get_llm_decision(self, task, history, tools, rag) -> str:
        """Helper to call the LLM and get the raw JSON string response."""
        response_generator = react_agent_prompt(
            task_description=task,
            history=history,
            available_tools=tools,
            rag_context=rag
        )
        # Exhaust the generator to get the final response
        try:
            while True:
                next(response_generator)
        except StopIteration as e:
            return e.value.content
        return "" # Should not be reached