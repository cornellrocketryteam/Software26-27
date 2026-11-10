# Fill-station dashboard

Use `uv` with a persistent `.venv` so the dashboard can run without internet.
From the repository root, set it up once while online:

```sh
cd fill-station/client
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

For every launch afterward, run from `fill-station/client`:

```sh
uv run --no-project --offline --python .venv/bin/python \
  python -m streamlit run dashboard_v2.py
```

No activation is needed. Keep `.venv` and the uv-managed Python installation;
the command reuses the installed dependencies and disables network access.
Do not add `--with-requirements` to this launch command. If `.venv` is missing
or a dependency cannot be imported, repeat the setup while online. After
changing `requirements.txt`, rerun the `uv pip install` command while online.
The old `client_env` environment is no longer used. The dashboard still needs
a local network connection to the board, but not an internet connection.

Open the local URL printed by Streamlit. Set **Server URL** to
`ws://192.168.8.171:9000`, replacing the IP if the board's address changes.
The dashboard defaults to `ws://localhost:9000`, which connects to a server
on your Mac rather than the board. Stop the dashboard with Ctrl-C.

For local development without the board, run the mock server in another terminal:

```sh
uv run --no-project --offline --python .venv/bin/python \
  python mock_server.py
```

Use `ws://localhost:9000` with the mock server. It simulates hardware; it does
not validate the physical board or actuators.
