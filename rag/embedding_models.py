# file: ./rag/embedding_models.py
import os
from typing import Any, List
from volcenginesdkarkruntime import Ark 


class VolcanoEmbedding:
    """
    A standalone Embedding client for Volcano Engine using the official volcenginesdkarkruntime SDK.
    """
    def __init__(self, model_name: str = "doubao-embedding-text-240715"):
        """
        Initializes the VolcanoEmbedding client.

        It automatically authenticates using the ARK_API_KEY environment variable.
        """
        self.model_name = model_name
        # The SDK automatically reads the API key from the ARK_API_KEY environment variable.
        # It's good practice to check for its existence for clearer error messages.
        if not os.environ.get("ARK_API_KEY"):
            raise ValueError("ARK_API_KEY environment variable not set. The SDK requires it for authentication.")
        
        # Initialize the official client
        self.client = Ark()
        
        # As per the API docs, send small batches for better performance.
        self.batch_size = 4

    def _call_embedding_sdk(self, texts: List[str]) -> List[List[float]]:
        """
        Makes the SDK call to the Volcano Engine embedding service.
        The SDK handles retries and error management internally.
        """
        # The SDK's `create` method handles the API call.
        response = self.client.embeddings.create(
            model=self.model_name,
            input=texts,
            encoding_format="float",
        )
        
        # The SDK returns a Pydantic-like model, which is easy to work with.
        # We sort by index to ensure the order is correct, just as a safeguard.
        embeddings_data: List[Any] = sorted(response.data, key=lambda e: e.index)
        
        return [e.embedding for e in embeddings_data]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embeds a list of documents, handling batching as recommended by the API docs.
        """
        if not texts:
            return []
            
        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            # We can now remove the tenacity @retry decorator, as the official SDK
            # is expected to handle transient network errors.
            all_embeddings.extend(self._call_embedding_sdk(batch))
            
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        """
        Embeds a single query text.
        """
        # The SDK expects a list, so we wrap the single text in a list.
        return self._call_embedding_sdk([text])[0]