# file: ./rag/vector_search.py
import numpy as np
import faiss  # <-- Import Faiss
from typing import List, Tuple
from .types import BaseIndexModel
import chromadb
import os 

class FaissVectorSearch:
    """
    A high-performance vector search engine using Faiss for Approximate 
    Nearest Neighbor (ANN) search.
    """
    def __init__(self, all_index_items: List[BaseIndexModel]):
        self.index_items = []
        self.faiss_index = None
        
        vectors_to_load = []
        for item in all_index_items:
            # We only index items that actually have an embedding
            if hasattr(item, 'embedding') and item.embedding:
                self.index_items.append(item)
                vectors_to_load.append(item.embedding)
        
        if not vectors_to_load:
            print("No vectors found to build Faiss index.")
            return

        # Convert to a NumPy matrix, Faiss requires this format
        vectors = np.array(vectors_to_load, dtype=np.float32)
        
        # Get the dimension of the vectors (e.g., 768 or 1024)
        d = vectors.shape[1]

        # --- Build the Faiss Index ---
        # We'll use IndexIVFFlat, a standard and effective choice.
        # It partitions the space into `nlist` cells (Voronoi cells).
        # A good value for `nlist` is often around the square root of the number of vectors.
        nlist = min(100, int(np.sqrt(len(vectors)))) # Capping at 100 for smaller datasets
        quantizer = faiss.IndexFlatL2(d)  # The quantizer defines the cells
        
        # The main index. L2 stands for Euclidean distance, which works well for normalized embeddings.
        self.faiss_index = faiss.IndexIVFFlat(quantizer, d, nlist, faiss.METRIC_L2)
        
        # --- Train and Add ---
        if not self.faiss_index.is_trained:
            self.faiss_index.train(vectors)
            
        self.faiss_index.add(vectors)
        
        print(f"Faiss index built successfully with {self.faiss_index.ntotal} vectors.")

    def search(self, query_vector: List[float], top_k: int) -> List[Tuple[str, float]]:
        """
        Performs an ANN search using the built Faiss index.

        Args:
            query_vector: The embedding of the user's query.
            top_k: The number of results to return.

        Returns:
            A list of tuples, each containing (file_path, similarity_score).
            Note: Faiss returns distances, so we convert them to similarities.
        """
        if not self.faiss_index:
            return []

        # Faiss expects a 2D array for queries
        query_np = np.array([query_vector], dtype=np.float32)

        # Search the index
        distances, indices = self.faiss_index.search(query_np, top_k)
        
        results = []
        for i, dist in zip(indices[0], distances[0]):
            if i != -1: # Faiss returns -1 for invalid indices
                # Convert L2 distance to a similarity score (0-1), higher is better
                # This is a common heuristic
                similarity = 1.0 / (1.0 + dist) 
                results.append((self.index_items[i].file_path, similarity))
        
        return results

class ChromaVectorSearch:
    """
    A vector search engine powered by ChromaDB.

    This class handles the creation, synchronization, and querying of a 
    persistent ChromaDB collection, acting as the semantic search backbone.
    """
    def __init__(self, project_path: str, all_index_items: List[BaseIndexModel]):
        """
        Initializes the ChromaVectorSearch.

        Args:
            project_path: The root path of the project, used to store the ChromaDB database.
            all_index_items: The list of all parsed index items from the JSON file.
        """
        # We store the ChromaDB database within our .ddb_agent directory
        db_path = os.path.join(project_path, ".ddb_agent", "chroma_db")
        
        # Initialize the persistent client
        self.client = chromadb.PersistentClient(path=db_path)
        
        # Get or create a collection. A collection is like a table in a database.
        self.collection = self.client.get_or_create_collection(
            name="ddb_agent_rag_collection"
        )
        
        # Synchronize the database with the provided index items
        self._sync(all_index_items)

    def _sync(self, all_index_items: List[BaseIndexModel]):
        """
        Synchronizes the ChromaDB collection with the current state of the index file.

        This method efficiently adds new documents, updates existing ones, and
        removes ones that are no longer in the index.
        """
        if not all_index_items:
            # If there are no items, we should consider clearing the collection
            # or simply do nothing. For now, we'll do nothing.
            print("No index items provided to sync with ChromaDB.")
            return

        print("Synchronizing ChromaDB collection...")
        
        # Get all existing IDs from ChromaDB to check for deletions
        existing_ids_in_db = set(self.collection.get(include=[])['ids'])
        
        # Prepare lists for upserting
        ids_to_upsert = []
        embeddings_to_upsert = []
        metadatas_to_upsert = []

        current_ids_in_index = set()

        for item in all_index_items:
            if hasattr(item, 'embedding') and item.embedding:
                # Use file_path as the unique document ID
                doc_id = item.file_path
                current_ids_in_index.add(doc_id)
                
                ids_to_upsert.append(doc_id)
                embeddings_to_upsert.append(item.embedding)
                
                # Store useful metadata for potential future filtering
                metadata = {
                    "summary": item.summary or "",
                    "source_document": getattr(item, 'source_document', item.file_path)
                }
                metadatas_to_upsert.append(metadata)

        # Upsert documents (add new or update existing)
        if ids_to_upsert:
            # ChromaDB's upsert is idempotent and efficient
            self.collection.upsert(
                ids=ids_to_upsert,
                embeddings=embeddings_to_upsert,
                metadatas=metadatas_to_upsert
            )
        
        # Identify and delete documents that are in the DB but not in the new index
        ids_to_delete = list(existing_ids_in_db - current_ids_in_index)
        if ids_to_delete:
            self.collection.delete(ids=ids_to_delete)
            print(f"Deleted {len(ids_to_delete)} stale entries from ChromaDB.")

        print(f"ChromaDB collection synchronized. Total entries: {self.collection.count()}")

    def search(self, query_vector: List[float], top_k: int) -> List[Tuple[str, float]]:
        """
        Performs a similarity search in the ChromaDB collection.

        Args:
            query_vector: The embedding of the user's query.
            top_k: The number of results to return.

        Returns:
            A list of tuples, each containing (file_path, similarity_score).
        """
        if self.collection.count() == 0:
            return []

        # ChromaDB's query is straightforward
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=min(top_k, self.collection.count()), # Ensure we don't request more than exists
        )
        
        # The result object contains ids, distances, metadatas, etc.
        # We need to parse it into our desired format.
        ids = results['ids'][0]
        # Chroma returns distances, let's convert them to a 0-1 similarity score
        # Note: Chroma uses L2 distance by default. A common conversion is 1 / (1 + L2_distance)
        distances = results['distances'][0]
        
        search_results = []
        for doc_id, dist in zip(ids, distances):
            similarity = 1.0 / (1.0 + dist)
            search_results.append((doc_id, similarity))
            
        return search_results