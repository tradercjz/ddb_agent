# file: ./rag/inverted_index.py
from collections import defaultdict
from typing import Dict, List, Set

from .types import BaseIndexModel
from utils.tokenizer import smart_tokenize

class InvertedIndex:
    """
    A high-performance in-memory inverted index for keyword-based pre-filtering.

    This index maps tokens (keywords) to a set of document IDs (file_paths) 
    that contain them, enabling extremely fast candidate retrieval.
    """
    def __init__(self):
        # The core of the inverted index: Dict[token, Set[file_path]]
        self._index: Dict[str, Set[str]] = defaultdict(set)
        self._is_built = False

    def build_from_indices(self, all_index_items: List[BaseIndexModel]):
        """
        Builds or rebuilds the inverted index from a list of index models.

        This method is designed to be idempotent. Calling it again will
        clear the old index and build a new one.
        """
        print("Building in-memory inverted index...")
        self._index.clear()
        
        for item in all_index_items:
            # We create a searchable text block from the most relevant metadata.
            # For TextChunkIndex, this includes the summary, keywords, and the question.
            # For CodeIndex, it's the summary and symbols.
            
            searchable_text = ""
            if hasattr(item, 'summary'):
                searchable_text += item.summary + " "
            if hasattr(item, 'keywords') and item.keywords:
                searchable_text += " ".join(item.keywords) + " "
            if hasattr(item, 'hypothetical_question') and item.hypothetical_question:
                searchable_text += item.hypothetical_question + " "
            if hasattr(item, 'symbols') and item.symbols:
                searchable_text += " ".join(s.name for s in item.symbols)

            # Use our smart tokenizer to get meaningful keywords
            tokens = smart_tokenize(searchable_text)
            
            for token in tokens:
                self._index[token].add(item.file_path)
        
        self._is_built = True
        print(f"Inverted index built successfully with {len(self._index)} unique tokens.")

    def search(self, query: str) -> Set[str]:
        """
        Searches the index for a given query and returns a set of matching
        document file_paths.

        Args:
            query: The user's search query.

        Returns:
            A set of file_paths that match the query keywords.
        """
        if not self._is_built:
            # This should ideally not happen if the flow is correct, but it's a good safeguard.
            print("Warning: InvertedIndex search called before it was built.")
            return set()

        query_tokens = smart_tokenize(query)
        if not query_tokens:
            return set()

        # Retrieve matching document sets for each token
        # Using a generator expression for memory efficiency
        matching_sets = (self._index.get(token, set()) for token in query_tokens)
        
        # We start with the result of the first token, then find the union 
        # with the rest. This finds documents that contain ANY of the keywords.
        # It's a good strategy for recall.
        try:
            result_set = next(matching_sets)
            for doc_set in matching_sets:
                result_set.update(doc_set)
            return result_set
        except StopIteration:
            # This happens if query_tokens was not empty but no token was found in the index
            return set()