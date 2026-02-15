import argparse
import json
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def main():
    data, title = parse_args()
    plot_channel_timeline(data, title=title)
    plt.show()


def parse_args():
    """Parses the CLI arguments to produce the thread timestamp data and plot
    title."""

    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    parser.add_argument("--title", type=str, default="Channel Timeline", help="Title for the plot")
    args = parser.parse_args()
    with open(args.data_path) as f:
        jdata = json.load(f)
    data = extract_timestamps(jdata)
    return data, args.title


def extract_timestamps(jdata):
    """Extracts timestamps from the thread data, returning a mapping of thread
    names to lists of unix timestamps."""

    return {
        thread["name"]: [float(m["ts"]) for m in thread["messages"]]
        for thread in jdata["conversations"].values()
    }


def parse_timestamps(timestamps):
    """Parses a list of timestamps into datetime objects. Supports datetime
    objects, ISO format strings, and unix timestamps."""

    parsed = []
    for ts in timestamps:
        if isinstance(ts, datetime):
            parsed.append(ts)
        elif isinstance(ts, str):
            parsed.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
        elif isinstance(ts, (int, float)):
            parsed.append(datetime.fromtimestamp(ts))
        else:
            raise ValueError(f"Unsupported timestamp format: {type(ts)}")
    return parsed


def plot_channel_timeline(data, figsize=(12, 6), title="Channel Timeline"):
    """Plots timestamps for multiple channels as vertically stacked horizontal
    lines with scatter dots."""

    parsed_data = {channel: parse_timestamps(timestamps) for channel, timestamps in data.items()}

    all_timestamps = [ts for timestamps in parsed_data.values() for ts in timestamps]
    if not all_timestamps:
        raise ValueError("No timestamps provided")

    min_time = min(all_timestamps)
    max_time = max(all_timestamps)

    channels = list(parsed_data.keys())
    n_channels = len(channels)

    fig, axes = plt.subplots(n_channels, 1, figsize=figsize, sharex=True, squeeze=False)
    axes = axes.flatten()

    for idx, (channel, timestamps) in enumerate(parsed_data.items()):
        ax = axes[idx]
        plot_channel_row(ax, channel, timestamps, idx, n_channels)

    format_x_axis(axes[-1], min_time, max_time)
    fig.suptitle(title, fontweight='bold', fontsize=14)
    plt.subplots_adjust(left=0.25, hspace=0.1)

    return fig, axes


def label_fontsize(label, base=10, min_size=6):
    """Returns a font size for a channel label, scaling down for longer names
    to keep them from overflowing the left margin."""

    if len(label) <= 15:
        return base
    return max(min_size, base * 15 / len(label))


def plot_channel_row(ax, channel, timestamps, idx, n_channels):
    """Plots a single channel row with a horizontal baseline and scatter dots
    for each timestamp."""

    ax.axhline(y=0, color='lightgray', linewidth=1, zorder=1)

    if timestamps:
        y_values = [0] * len(timestamps)
        ax.scatter(timestamps, y_values, s=30, c='steelblue', zorder=2, edgecolors='white', linewidth=1)
        ax.scatter(timestamps, y_values, s=30, c='steelblue', zorder=2, edgecolors='none')

    label = channel or "<self>"
    fontsize = label_fontsize(label)
    ax.set_ylabel(label, rotation=0, ha='right', va='center', fontweight='bold', fontsize=fontsize)
    ax.set_ylim(-0.5, 0.5)
    ax.set_yticks([])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)

    if idx < n_channels - 1:
        ax.spines['bottom'].set_visible(False)
        ax.tick_params(bottom=False)


def format_x_axis(ax, min_time, max_time):
    """Formats the x-axis of the bottom subplot with date labels and
    appropriate padding."""

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45, ha='right')

    time_range = (max_time - min_time).total_seconds()
    padding = max(time_range * 0.05, 60)
    ax.set_xlim(min_time - timedelta(seconds=padding),
                max_time + timedelta(seconds=padding))


if __name__ == "__main__":
    main()
