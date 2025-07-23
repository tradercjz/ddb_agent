import os
import json
from typing import List, Optional, Dict

from .snippet_model import Snippet

class SnippetManager:
    def __init__(self, project_path: str):
        self.snippets_file = os.path.join(project_path, ".ddb_agent", "snippets.json")
        self.snippets: Dict[str, Snippet] = self._load_snippets()

    def _load_snippets(self) -> Dict[str, Snippet]:
        if not os.path.exists(self.snippets_file):
            return {}
        try:
            with open(self.snippets_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {name: Snippet(**snippet_data) for name, snippet_data in data.items()}
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_snippets(self):
        os.makedirs(os.path.dirname(self.snippets_file), exist_ok=True)
        with open(self.snippets_file, 'w', encoding='utf-8') as f:
            json.dump({name: snippet.model_dump() for name, snippet in self.snippets.items()}, f, indent=2)

    def add_or_update_snippet(self, snippet: Snippet) -> bool:
        if not snippet.name:
            return False
        self.snippets[snippet.name] = snippet
        self._save_snippets()
        return True

    def get_snippet(self, name: str) -> Optional[Snippet]:
        return self.snippets.get(name)

    def delete_snippet(self, name: str) -> bool:
        if name in self.snippets:
            del self.snippets[name]
            self._save_snippets()
            return True
        return False

    def search_snippets(self, query: str) -> List[Snippet]:
        query_lower = query.lower()
        results = []
        for snippet in self.snippets.values():
            if (query_lower in snippet.name.lower() or
                (snippet.description and query_lower in snippet.description.lower()) or
                any(query_lower in tag.lower() for tag in snippet.tags)):
                results.append(snippet)
        return results

    def get_all_snippets(self) -> List[Snippet]:
        return list(self.snippets.values())