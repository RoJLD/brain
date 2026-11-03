"""Research knowledge graph — typed store loader, query model, and validation.

Reads the local (gitignored) store under ``notes/graph/`` into a networkx
DiGraph. The package is path-agnostic: tests point it at a fixture store,
the CLI defaults to ``notes/graph``.
"""

__version__ = "0.2.1"
