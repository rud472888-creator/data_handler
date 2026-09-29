"""Post-completion visual QA: decode replica clips, ask a local VLM, report evidence.

Only the light modules (``scheduler``, ``inputs``, ``settings``, ``store``) are
imported by the main app. Pillow / PyAV / MLX are imported lazily by the worker so
the backup environment keeps working without the inference dependencies.
"""
