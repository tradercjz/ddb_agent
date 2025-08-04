# file: ddb_agent/session/summarizer.py

from typing import List, Dict, Any
from llm.llm_prompt import llm

# We can give the summarizer a dedicated, faster model if needed.
@llm.prompt(model="deepseek-chat")
def summarize_history_prompt(conversation_to_summarize: str) -> str:
    """
    You are an expert conversation summarizer. Your task is to read a raw conversation history and distill it into a concise, structured summary. This summary will be used as long-term memory for an AI assistant.

    **Conversation History:**
    ```
    {{ conversation_to_summarize }}
    ```

    **Instructions:**
    1.  Identify the user's primary goals and the overall topic of the conversation.
    2.  Extract any critical information, key decisions, or constraints mentioned (e.g., "The user requires the final script to be compatible with DolphinDB version 2.00.8").
    3.  Include any important code snippets, file paths, or data structures that were discussed or generated.
    4.  Note any unresolved questions or tasks that the assistant was left with.
    5.  The summary should be neutral, third-person, and factual.

    **Output Format:**
    Your output must be a concise text summary. Do not use JSON or other complex formats. Start with a brief overview, then use bullet points for key details.

    **Example Output:**
    The user's goal was to create a script for calculating VWAP. The assistant provided an initial script which failed due to an incorrect function call. After debugging, a corrected script using a `tumble` window was generated. The user specified that the 'timestamp' column must be in UTC. The task was successfully completed.
    - Key file: `/data/trades.csv`
    - Final script snippet: `select wavg(price, qty) from trades.tumble(timestamp, 1h)`
    """
    pass

class HistorySummarizer:
    """
    A class dedicated to summarizing conversation history to maintain long-term context.
    """
    @staticmethod
    def summarize(history: List[Dict[str, Any]]) -> str:
        """
        Takes a list of message dictionaries and returns a summary string.

        Args:
            history: The list of conversation turns to summarize.

        Returns:
            A string containing the summarized history.
        """
        if not history:
            return ""

        # Format the history into a simple, readable string for the LLM.
        history_str = "\n".join(
            f"{msg['role'].capitalize()}: {msg.get('content', '')}"
            for msg in history
        )

        try:
            # Call the LLM prompt to get the summary.
            # We need to handle the generator nature of the llm.prompt decorator.
            summary_generator = summarize_history_prompt(
                conversation_to_summarize=history_str
            )
            # Exhaust the generator to get the final LLMResponse
            while True:
                try:
                    next(summary_generator)
                except StopIteration as e:
                    llm_response = e.value
                    break
            
            if llm_response.success and llm_response.content:
                return llm_response.content.strip()
            else:
                # Fallback in case of summarization failure
                return "Failed to generate summary."
        except Exception as e:
            print(f"Error during history summarization: {e}")
            return f"Error during summarization: {e}"