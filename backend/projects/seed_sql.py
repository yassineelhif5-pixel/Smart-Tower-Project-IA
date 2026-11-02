"""Lecture de supabase/seed.sql (données de démonstration) sans base Supabase.

seed.sql est généré par supabase/generate_seed.py dans un format fixe :
`insert into public.<table> (<colonnes>) values (<littéraux>), … ;`
avec des littéraux null, true/false, nombres, 'texte' ('' échappé), '…'::jsonb,
array['…', …]::text[] et '{}'::text[]. Ce module ne lit que ce format et
s'arrête sur tout autre élément, pour qu'aucune donnée ne soit perdue en silence.
"""
import json
import re

INSERT = re.compile(r"insert into public\.(\w+) \(([^)]*)\) values\s*", re.S)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


class SeedFormatError(ValueError):
    pass


class _Reader:
    def __init__(self, text, pos):
        self.text, self.pos = text, pos

    def error(self, what):
        line = self.text.count("\n", 0, self.pos) + 1
        return SeedFormatError(f"seed.sql ligne {line} : {what}")

    def skip_ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def expect(self, char):
        self.skip_ws()
        if not self.text.startswith(char, self.pos):
            raise self.error(f"« {char} » attendu")
        self.pos += len(char)

    def peek(self, word):
        self.skip_ws()
        return self.text.startswith(word, self.pos)

    def string(self):
        self.expect("'")
        out = []
        while True:
            end = self.text.find("'", self.pos)
            if end < 0:
                raise self.error("chaîne non terminée")
            out.append(self.text[self.pos:end])
            self.pos = end + 1
            if self.text.startswith("'", self.pos):  # '' = apostrophe échappée
                out.append("'")
                self.pos += 1
            else:
                return "".join(out)

    def value(self):
        self.skip_ws()
        if self.peek("null"):
            self.pos += 4
            return None
        if self.peek("true"):
            self.pos += 4
            return True
        if self.peek("false"):
            self.pos += 5
            return False
        if self.peek("array["):
            self.pos += 6
            items = []
            while not self.peek("]"):
                items.append(self.value())
                if self.peek(","):
                    self.pos += 1
            self.expect("]")
            self.expect("::text[]")
            return items
        if self.peek("'"):
            raw = self.string()
            if self.peek("::jsonb"):
                self.pos += 7
                return json.loads(raw)
            if self.peek("::text[]"):
                self.pos += 8
                if raw != "{}":
                    raise self.error("tableau texte littéral non vide inattendu")
                return []
            return raw
        match = NUMBER.match(self.text, self.pos)
        if match:
            self.pos = match.end()
            number = match.group()
            return float(number) if any(c in number for c in ".eE") else int(number)
        raise self.error("valeur non reconnue")

    def row(self, size):
        self.expect("(")
        values = []
        for i in range(size):
            values.append(self.value())
            if i < size - 1:
                self.expect(",")
        self.expect(")")
        return values


def parse(text):
    """Renvoie {table: [ {colonne: valeur}, … ]} dans l'ordre du fichier."""
    tables = {}
    for match in INSERT.finditer(text):
        table = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",")]
        reader = _Reader(text, match.end())
        rows = tables.setdefault(table, [])
        while True:
            rows.append(dict(zip(columns, reader.row(len(columns)))))
            if reader.peek(","):
                reader.pos += 1
                continue
            reader.expect(";")
            break
    return tables


def load(path):
    return parse(path.read_text(encoding="utf-8"))
