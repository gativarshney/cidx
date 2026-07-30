# Terminal demo script (60–90 seconds)

The exact command sequence for the recorded demo. Practice it twice before
recording; the run itself should be one take with no narration pauses.

## Setup (off camera)

```bash
pip install --pre cidx               # or from a checkout: pip install -e .
python scripts/clone_datasets.py     # materializes the pinned repos
cd benchmark/datasets/repos/click
```

## The take

```bash
# 1. Index a real project (~20k LOC) — watch the timing
cidx index --repo .

# 2. Where is the Context class defined?
cidx query Context --repo .

# 3. Who calls echo? Note the confidence tags and resolved targets.
cidx query echo --references --repo .

# 4. What does termui.py contain, without opening it?
cidx query src/click/termui.py --outline --repo .

# 5. Edit a file, reindex, and prove nothing drifted
echo "def demo_symbol(): pass" >> src/click/utils.py
cidx index --repo .
cidx query demo_symbol --repo .
cidx check --repo .

# 6. The freshness stamp agents see on every MCP response
python -c "from cidx.core import repoid; from cidx.core.store import Store; \
from cidx.ranking import budget; s = Store.open(repoid.index_path('.')); \
print(f'index_age_ms: {budget.index_age_ms(s)}'); s.close()"

# 7. Clean up the demo edit (off camera)
git checkout -- src/click/utils.py && cidx index --repo .
```

Beats to hit while it runs: the index time in step 1, the exact
`path:line` answers in steps 2–4, the sub-second reindex in step 5,
`no drift` from `cidx check`, and the small `index_age_ms` number in
step 6.

## Recording

macOS/Linux, with [asciinema](https://asciinema.org):

```bash
asciinema rec cidx-demo.cast --cols 100 --rows 28
# ... run the take, then Ctrl-D ...
asciinema play cidx-demo.cast          # review
agg cidx-demo.cast cidx-demo.gif       # GIF for the README (pip install agg / cargo install agg)
```

Windows: record the same take in Windows Terminal with
[terminalizer](https://github.com/faressoft/terminalizer)
(`npm i -g terminalizer; terminalizer record cidx-demo; terminalizer
render cidx-demo`) or capture the window with ScreenToGif.

Target output: `cidx-demo.gif`, for embedding in the README.
