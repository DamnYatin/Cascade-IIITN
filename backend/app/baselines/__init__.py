"""Baselines package for the 72-Hour Warning.

Rule V1:
  - Consumes ONLY StreamView.
  - MUST NOT import ground truth, generator internals, or scenario label files.
  - Dependency direction is eval -> baselines, never baselines -> eval.
"""
