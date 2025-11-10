# tests/conftest.py
import asyncio
import sys

# This is the crucial fix for Windows asyncio issues with pytest.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())