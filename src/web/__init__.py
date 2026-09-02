"""Browser shell: the job entry points the Pyodide worker calls.

The GUI and the CLI are the other two shells over the same pipeline functions.
This one runs under Pyodide, which has no Qt and no threads, so it speaks JSON
strings across the JavaScript boundary and leaves translation to the page.
"""
