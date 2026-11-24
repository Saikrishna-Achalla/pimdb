# stub: gen.py random mode never uses numpy; any use raises
def __getattr__(n): raise RuntimeError("numpy stub used: " + n)
