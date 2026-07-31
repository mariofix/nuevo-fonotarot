import re

with open("nuevo_fonotarot/utils.py", "r") as f:
    content = f.read()

new_content = content.replace("def _fetch_order_stats() -> dict:", "def _fetch_order_stats(year: int | None = None, month: int | None = None) -> dict:")

# Update the logic inside
# Instead of doing it with regex, maybe I'll edit it manually with default_api:edit
