"""
Rules package - Contains all code smell detection rule implementations.

Each rule class exposes a `check(tree)` method that takes a parsed AST and
returns a list of issue dictionaries.
"""
from .god_class import GodClassRule
from .duplicated_code import DuplicatedCodeRule

__all__ = ['GodClassRule', 'DuplicatedCodeRule', 'LongMethodRule', 'DeadCodeRule', 'MutableDefaultArguments']