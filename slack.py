import argparse
import os
import json
import urllib.request
import urllib.parse
import time
import random
from datetime import datetime

sleep_time = 20

opener = urllib.request.build_opener(type(
    "NoRaise", (urllib.request.HTTPErrorProcessor,),
    {"http_response": lambda self, req, res: res, "https_response": lambda self, req, res: res}
))

def main():
    data, output_path, channel_id, channel_type = parse_args()
    output = load_output(output_path, data)
    new_channels = get_channels(data, channel_id=channel_id, channel_type=channel_type)
    for ch_id, ch_data in new_channels.items():
        if ch_id in output["channels"]:
            output["channels"][ch_id].update(ch_data)
        else:
            output["channels"][ch_id] = ch_data
    save_output(output, output_path)
    output["people"] = {
        **output["people"],
        **get_users(output["channels"], data, output_path)
    }
    save_output(output, output_path)
    for channel in output["channels"].values():
        if channel_id and channel["id"] != channel_id:
            continue
        if "messages" not in channel:
            process_conversation(channel, data, output, output_path)


def parse_args():
    """Parses the CLI arguments to produce the data config file, and the path
    for the output directory."""

    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    parser.add_argument("output_path", type=str)
    parser.add_argument("--channel", type=str, default=None, help="Only process the channel with this ID")
    parser.add_argument("--type", type=str, default=None, choices=["public_channel", "private_channel", "im", "mpim"], help="Only fetch channels of this type")
    args = parser.parse_args()
    with open(args.data_path) as f:
        data = json.load(f)
    return data, args.output_path.rstrip("/"), args.channel, args.type


def get_channels(data, channel_id=None, channel_type=None):
    """Gets all channels in the workspace as a mapping of channel ID to channel
    data. It will return all channels the user is a member of, including direct
    messages, group messages, and public and private channels. Falls back to
    client.userBoot for enterprise workspaces where users.conversations is
    restricted. If channel_id is provided, only that channel is returned. If
    channel_type is provided, only channels of that type are fetched."""

    log("Downloading channels")
    types = channel_type if channel_type else "public_channel,private_channel,im,mpim"
    types_set = set(types.split(","))
    response = slack_post("users.conversations", data, params={"types": types, "limit": 200})
    if response.get("ok") is not False:
        channel_list = response["channels"]
        cursor = response.get("response_metadata", {}).get("next_cursor", "")
        while cursor:
            response = slack_post("users.conversations", data, params={"types": types, "limit": 200, "cursor": cursor})
            channel_list += response["channels"]
            cursor = response.get("response_metadata", {}).get("next_cursor", "")
    else:
        channel_list = get_enterprise_channels(data, types_set)
    if channel_id:
        channel_list = [c for c in channel_list if c["id"] == channel_id]
    return {channel["id"]: channel for channel in channel_list}


def get_enterprise_channels(data, types_set):
    """Use the client.userBoot API to get all channels the user is a member of.
    This is the only way to get all channels in an enterprise workspace."""

    response = slack_post("client.userBoot", data)
    channel_list = []
    if types_set & {"public_channel", "private_channel", "mpim"}:
        for ch in response.get("channels", []):
            if ch.get("is_mpim") and "mpim" in types_set:
                channel_list.append(ch)
            elif ch.get("is_private") and "private_channel" in types_set:
                channel_list.append(ch)
            elif not ch.get("is_private") and not ch.get("is_mpim") and "public_channel" in types_set:
                channel_list.append(ch)
    if "im" in types_set:
        channel_list += response.get("ims", [])
    return channel_list


def get_users(channels, data, output_path):
    """Gets all users in the workspace as a mapping of user ID to user data. It
    goes through all channel and conversation overviews to get this data."""

    log("Downloading users")
    users = {}
    for channel_id in channels:
        params = {"channel": channel_id}
        response = slack_post("conversations.view", data, params=params)
        for user in response["users"]:
            users[user["id"]] = user
    if "USLACKBOT" not in users:
        response = slack_post("users.info", data, params={"user": "USLACKBOT"})
        if response.get("ok") and "user" in response:
            users["USLACKBOT"] = response["user"]
    for user in users.values():
        download_user_photo(user, data, output_path)
    return users


def download_user_photo(user, data, output_path):
    """Downloads a user's profile photo and saves it to slack_files/people/."""

    image_url = user.get("profile", {}).get("image_72") or user.get("icons", {}).get("image_72")
    if not image_url:
        return
    ext = image_url.rsplit(".", 1)[-1].split("?")[0] if "." in image_url else "jpg"
    filename = f"{output_path}/slack_files/people/{user['id']}.{ext}"
    if os.path.exists(filename):
        return
    os.makedirs(f"{output_path}/slack_files/people", exist_ok=True)
    response = slack_get(image_url, data)
    with open(filename, "wb") as f:
        f.write(response)


def get_missing_users(messages, data, known_users, output_path):
    """Finds user IDs in messages that aren't already known, looks them up via
    users.info, and returns a mapping of user_id to user data."""

    user_ids = set()
    for message in messages:
        for msg in [message] + message.get("replies", []):
            if uid := msg.get("user"):
                user_ids.add(uid)
            for reaction in msg.get("reactions", []):
                user_ids.update(reaction.get("users", []))
    user_ids -= set(known_users)
    users = {}
    for uid in user_ids:
        response = slack_post("users.info", data, params={"user": uid})
        if response.get("ok") and "user" in response:
            users[uid] = response["user"]
            log(f"Found user: {users[uid].get('name', uid)}", indent=1)
            download_user_photo(users[uid], data, output_path)
        else:
            log(f"Could not find user: {uid}", indent=1)
    return users


def get_bots(messages, data, known_bots, output_path):
    """Finds bot_ids in messages that aren't already known, looks them up via
    embedded bot_profile or the bots.info API, and returns a mapping of bot_id
    to bot data."""

    bot_ids = {}
    for message in messages:
        for msg in [message] + message.get("replies", []):
            bot_id = msg.get("bot_id")
            if bot_id and bot_id not in known_bots and bot_id not in bot_ids:
                bot_ids[bot_id] = msg.get("bot_profile")
    bots = {}
    for bot_id, bot_profile in bot_ids.items():
        if bot_profile:
            bots[bot_id] = bot_profile
        else:
            response = slack_post("bots.info", data, params={"bot": bot_id})
            if response.get("ok") and "bot" in response:
                bots[bot_id] = response["bot"]
            else:
                log(f"Could not find bot: {bot_id}", indent=1)
                continue
        log(f"Found bot: {bots[bot_id].get('name', bot_id)}", indent=1)
        download_user_photo(bots[bot_id], data, output_path)
    return bots


def process_conversation(channel, data, output, output_path):
    """Fully processes a conversation and updates the output object in place
    with the downloaded messages. As a side effect it will update the output on
    disk once completed, and save a text representation of the conversation."""

    readable_name = channel_readable_name(channel, output["people"])
    log(readable_name)
    messages = get_all_messages(channel["id"], data, output_path)
    output["people"].update(get_missing_users(messages, data, output["people"], output_path))
    output["bots"].update(get_bots(messages, data, output["bots"], output_path))
    channel["readable_name"] = readable_name
    channel["messages"] = messages
    save_output(output, output_path)
    save_conversation_to_text(messages, readable_name, output["people"], output["bots"], output_path)


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


def sender_name(message, people, bots):
    """Returns the display name for whoever sent a message, checking people
    first then bots."""

    if user := message.get("user"):
        return user_id_to_user_name(user, people)
    if bot_id := message.get("bot_id"):
        return bots.get(bot_id, {"name": bot_id}).get("name", bot_id)
    return ""


def format_timestamp(message):
    """Formats a message timestamp as a human-readable datetime string."""

    return datetime.fromtimestamp(float(message["ts"])).strftime("%Y-%m-%d %H:%M:%S")


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
            check_reactions(message, data, output_path)
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


def check_reactions(message, data, output_path):
    """Downloads any custom emoji images from reactions on a message."""

    for reaction in message.get("reactions", []):
        url = reaction.get("url")
        if not url:
            continue
        ext = url.rsplit(".", 1)[-1].split("?")[0] if "." in url else "png"
        filename = f"{output_path}/slack_files/reactions/{reaction['name']}.{ext}"
        if not os.path.exists(filename):
            os.makedirs(f"{output_path}/slack_files/reactions", exist_ok=True)
            log(f"Downloading reaction {reaction['name']}...", indent=2)
            response = slack_get(url, data)
            with open(filename, "wb") as f:
                f.write(response)


def save_conversation_to_text(messages, name, people, bots, output_path):
    """Saves a conversation to a text file. It will format the messages in a
    human-readable way, and save the file to the output path."""

    lines = []
    for message in messages:
        lines.append(f"{format_timestamp(message)}: [{sender_name(message, people, bots)}] {message['text']}\n")
        for reply in message.get("replies", []):
            lines.append(f"    [{sender_name(reply, people, bots)}] {reply['text']}")
        lines.append("")
    filename = name.replace(" ", "_").replace(",", "_")
    with open(f"{output_path}/{filename}.txt", "w") as f:
        f.write("\n".join(lines))
    

def slack_request(method, url, data, params=None, indent=1):
    """Makes a request to the Slack API. It will handle ratelimiting,
    authentication, and URL construction."""

    global sleep_time
    url = url if url.startswith("https://") else f"https://{data['workspace']}.slack.com/api/{url}"
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {"cookie": data["cookie"]}
    while True:
        if method == "POST":
            body = urllib.parse.urlencode({"token": data["token"]}).encode()
        else:
            body = None
        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        with opener.open(req) as response:
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


def load_output(output_path, data):
    """Loads existing output from disk, or returns an empty structure."""

    path = f"{output_path}/slack.json"
    if os.path.exists(path):
        with open(path) as f:
            output = json.load(f)
        output.setdefault("bots", {})
        return output
    return {
        "id": data.get("id", ""),
        "name": data["workspace"],
        "people": {},
        "bots": {},
        "channels": {},
    }


def save_output(output, output_path):
    """Saves the output object to a JSON file."""

    os.makedirs(output_path, exist_ok=True)
    with open(f"{output_path}/slack.json", "w") as f:
        json.dump(output, f, indent=4)


if __name__ == "__main__":
    main()