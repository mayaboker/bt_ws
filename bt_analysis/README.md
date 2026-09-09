# bt-analysis

Read-only local dashboard for BT flight blackbox logs.

## Run

From the workspace root:

```bash
uv run --project bt_analysis bt-analysis run
```

Open <http://127.0.0.1:8002>. By default the dashboard reads
`./bt_app/logs/blackbox` relative to the directory where the command is run. If
running from inside `bt_analysis`, provide the workspace path explicitly:

```bash
uv run bt-analysis run --logs-dir ../bt_app/logs/blackbox
```

The server is read-only. The dashboard initially selects the newest finished
(`complete` or `unclean`) session. Use the **Flight log** combobox to analyze
an older session and **Refresh logs** after a flight finishes. A session that
is still recording is excluded until bt-app finalizes it. Use **Browse folder**
to select a different blackbox root or an individual `*_blackbox` session
folder; the native chooser is available when the server runs on a Linux desktop
with Zenity.
