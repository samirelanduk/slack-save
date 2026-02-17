# slack-save

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![No Dependencies](https://img.shields.io/badge/dependencies-none*-brightgreen)

slack-save is a Python tool for exporting your Slack conversations, files and metadata to JSON by mimicking a browser.

```bash
# Download everything from a workspace
python slack.py config.json output/

# Visualize the results
python visualize.py output/slack.json
```

> **\* Note:** The core archiver (`slack.py`) uses only the Python standard library. The visualisation script (`vis.py`) requires [matplotlib](#visualisation).

---

## Disclaimer

This tool accesses Slack using session cookies and tokens extracted from your browser. **It is your responsibility** to ensure your use of this tool complies with Slack's Terms of Service, your workspace's policies, and any applicable laws. The authors accept no liability for misuse.

---

## Setup

### Requirements

- Python 3.10 or later
- A Slack workspace you are logged into in your browser

### Configuration

The archiver reads credentials from a JSON config file. Create a file (e.g. `config.json`) with the following structure:

```json
{
    "workspace": "your-workspace-name",
    "token": "xoxc-...",
    "cookie": "d=xoxd-..."
}
```

| Field | Description |
|-------|-------------|
| `workspace` | The subdomain of your Slack workspace (i.e. the `xxx` in `xxx.slack.com`) |
| `token` | Your `xoxc-` session token |
| `cookie` | Your browser's `d` cookie value for Slack |

To find these values:

1. Open your workspace in a browser and log in.
2. Open the browser developer tools (F12) and go to the **Network** tab.
3. Perform any action in Slack (e.g. switch channels) and inspect a request to `slack.com/api/`.
4. The `token` is in the POST request body.
5. The `cookie` is in the request headers under `Cookie`.

> **Tip:** Keep your config file out of version control — `*.json` is already in this project's `.gitignore`.

---

## Archiving

Run `slack.py` with the path to your config file and an output directory:

```bash
python slack.py config.json output/
```

This will download all channels, DMs, group messages, users, message history, and attached files into the output directory. The process is resumable — if interrupted, re-running the same command will pick up where it left off, skipping already-downloaded conversations.

### Options

| Argument | Description |
|----------|-------------|
| `data_path` | Path to the JSON config file (required) |
| `output_path` | Path to the output directory (required) |
| `--channel CHANNEL_ID` | Only process a single channel by its Slack ID |
| `--type TYPE` | Only fetch channels of a specific type: `public_channel`, `private_channel`, `im`, or `mpim` |

#### Examples

Download only direct messages:

```bash
python slack.py config.json output/ --type im
```

Download a specific channel:

```bash
python slack.py config.json output/ --channel C01ABCD2EFG
```

### Output

The output directory will contain:

- **`slack.json`** — a single JSON file with all channels, users, and conversation data.
- **`*.txt`** — a plain text file per conversation, with messages formatted as `YYYY-MM-DD HH:MM:SS: [username] message text`.
- **`slack_files/`** — any files attached to messages, saved as `{file_id}.{filetype}`.

---

## Visualisation

The `visualize.py` script plots a timeline of message activity across all conversations, showing when messages were sent in each channel as dots on a horizontal axis.

### Install matplotlib

matplotlib is the only external dependency and is only needed for visualisation:

```bash
pip install matplotlib
```

### Usage

Point it at the `slack.json` file produced by the archiver:

```bash
python visualize.py.py output/slack.json
```

#### Options

| Argument | Description |
|----------|-------------|
| `data_path` | Path to the `slack.json` output file (required) |
| `--title TITLE` | Custom title for the plot (default: `Channel Timeline`) |

```bash
python visualize.py output/slack.json --title "My Workspace Activity"
```
