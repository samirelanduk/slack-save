import argparse
import os
import json
import urllib.request
import urllib.parse
import time
import random
from datetime import datetime

sleep_time = 20

def main():
    data, output_path = parse_args()
    output = {"channels": {}, "people": {}, "conversations": {}}
    output["channels"] = get_channels(data)
    save_output(output, output_path)
    output["people"] = get_users(output["channels"], data)
    save_output(output, output_path)
    for channel in output["channels"].values():
        process_conversation(channel, data, output, output_path)


def parse_args():
    """Parses the CLI arguments to produce the data config file, and the path
    for the output directory."""

    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    parser.add_argument("output_path", type=str)
    args = parser.parse_args()
    with open(args.data_path) as f:
        data = json.load(f)
    return data, args.output_path


def get_channels(data):
    """Gets all channels in the workspace as a mapping of channel ID to channel
    data. It will return all channels, including direct messages, group messages,
    and public and private channels."""

    log("Downloading channels")
    params = {"types": "public_channel,private_channel,im,mpim"}
    channel_list = slack_post("conversations.list", data, params=params)["channels"]
    return {channel["id"]: channel for channel in channel_list}


def get_users(channels, data):
    """Gets all users in the workspace as a mapping of user ID to user data. It
    goes through all channel and conversation overviews to get this data."""

    log("Downloading users")
    users = {}
    for channel_id in channels:
        params = {"channel": channel_id}
        response = slack_post("conversations.view", data, params=params)
        for user in response["users"]:
            users[user["id"]] = user
    return users


def process_conversation(channel, data, output, output_path):
    """Fully processes a conversation and updates the output object in place
    with the downloaded messages. As a side effect it will update the output on
    disk once completed, and save a text representation of the conversation."""

    readable_name = channel_readable_name(channel, output["people"])
    log(readable_name)
    messages = get_all_messages(channel["id"], data, output_path)
    output["conversations"][channel["id"]] = {
        "name": readable_name,
        "messages": messages
    }
    save_output(output, output_path)
    save_conversation_to_text(messages, readable_name, output["people"], output_path)


def channel_readable_name(channel, users):
    """Returns a readable name for a channel. This will be the channel name for
    regular channels, otherwise the names of the members."""

    if user := channel.get("user"):
        return user_id_to_user_name(user, users)
    elif members := channel.get("members"):
        return ",".join([user_id_to_user_name(member, users) for member in members])
    else:
        return channel["name"]


def user_id_to_user_name(id, users):
    """Returns the name of a user given their ID."""

    return users.get(id, {"name": id})["name"]


def get_all_messages(channel_id, data, output_path, reply_ts=None):
    """Gets all messages in a thread, whether for a channel or the replies to a
    single message. It will download all files attached to the messages, and
    find all replies recursively."""

    page = 1
    last_message_ts = None
    messages = []
    while True:
        new_messages = get_messages_page(channel_id, data, latest_ts=last_message_ts, reply_ts=reply_ts)
        if not new_messages: break
        if new_messages[-1]["ts"] == last_message_ts: break
        if reply_ts and page == 1:
            log(f"Getting replies to message {reply_ts}", indent=2)
        elif reply_ts and page > 1:
            log(f"Getting replies to message {reply_ts}, page {page}", indent=2)
        else:
            log(f"Page {page}", indent=1)
        new_messages = [message for message in new_messages if message.get("ts") != last_message_ts]
        for message in new_messages:
            check_replies(message, channel_id, data, output_path)
            check_files(message, data, output_path)
        messages += new_messages
        messages.sort(key=lambda x: x["ts"])
        page += 1
        last_message_ts = messages[0]["ts"]
    return messages


def get_messages_page(channel_id, data, latest_ts=None, reply_ts=None):
    """Gets a single page of messages for a particular channel, at a particular
    point in time."""

    path = "conversations.replies" if reply_ts else "conversations.history"
    params = {"channel": channel_id}
    if latest_ts: params["latest"] = latest_ts
    if reply_ts: params["ts"] = reply_ts
    messages = slack_post(path, data, params=params)["messages"]
    if reply_ts: messages.pop(0)
    return messages


def check_replies(message, channel_id, data, output_path):
    """Downloads any replies for a message, and adds them to the message."""

    if message.get("reply_count", 0) > 0:
        message["replies"] = get_all_messages(channel_id, data, output_path, reply_ts=message["ts"])
    else:
        message["replies"] = []


def check_files(message, data, output_path):
    """Downloads any files attached to a message, and saves them to disk. If the
    file has already been downloaded, it will not be downloaded again."""

    for file in message.get("files", []):
        if not file.get("url_private_download"): continue
        filename = f"{output_path}/slack_files/{file['id']}.{file['filetype']}"
        if not os.path.exists(filename):
            os.makedirs(f"{output_path}/slack_files", exist_ok=True)
            log(f"Downloading file {filename}...", indent=2)
            response = slack_get(file["url_private_download"], data)
            with open(filename, "wb") as f:
                f.write(response)
            log(f"Downloaded file {filename}", indent=2)


def save_conversation_to_text(messages, name, users,output_path):
    """Saves a conversation to a text file. It will format the messages in a
    human-readable way, and save the file to the output path."""

    lines = []
    for message in messages:
        user_name = user_id_to_user_name(message["user"], users)
        dt = datetime.fromtimestamp(float(message["ts"]))
        dt_string = dt.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{dt_string}: [{user_name}] {message['text']}\n")
        for reply in message.get("replies", []):
            user_name = user_id_to_user_name(reply["user"], users)
            lines.append(f"    [{user_name}] {reply['text']}")
        lines.append("")
    filename = name.replace(" ", "_").replace(",", "_")
    with open(f"{output_path}/{filename}.txt", "w") as f:
        f.write("\n".join(lines))
    

def slack_request(method, url, data, params=None, indent=1):
    """Makes a request to the Slack API. It will handle ratelimiting,
    authentication, and URL construction."""

    global sleep_time
    url = url if url.startswith("https://") else f"https://{data['workspace']}.slack.com/api/{url}"
    headers = {"cookie": data["cookie"]}
    while True:
        if method == "POST":
            body = urllib.parse.urlencode({"token": data["token"]}).encode()
        else:
            body = None
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req) as response:
            content = response.read()
        time.sleep(random.uniform(0.25, 0.75))
        if method == "GET": return content
        result = json.loads(content)
        if result.get("error") == "ratelimited":
            log(f"Ratelimited, sleeping for {sleep_time} seconds", indent=indent)
            time.sleep(sleep_time)
            sleep_time += 7
            continue
        return result


def slack_post(*args, **kwargs):
    """Makes a POST request to the Slack API."""

    return slack_request("POST", *args, **kwargs)


def slack_get(*args, **kwargs):
    """Makes a GET request to the Slack API."""

    return slack_request("GET", *args, **kwargs)


def log(message, indent=0):
    """Logs a message to the console with some indentation."""

    print(f"{'    ' * indent}{message}")


def save_output(output, output_path):
    """Saves the output object to a JSON file."""

    os.makedirs(output_path, exist_ok=True)
    with open(f"{output_path}/slack.json", "w") as f:
        json.dump(output, f, indent=4)


if __name__ == "__main__":
    main()