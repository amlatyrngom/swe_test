import tomllib
import re

class Injection:
    def __init__(self, filename: str):
        with open(filename, "rb") as f:
            injections = tomllib.load(f)
            if "injections" in injections:
                injections = injections["injections"]
        self.injections = [
            (re.compile(v['match']), v['content']) for v in injections if v.get('enabled', True)
        ]
        self.match_cache = {}

    def find_matching_injections(self, term) -> str:
        if term in self.match_cache:
            return self.match_cache[term]
        matches = [v for k, v in self.injections if k.search(term)]
        matches = "\n---\n".join(matches)
        self.match_cache[term] = matches
        return matches