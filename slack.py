import argparse
import os
import json
import requests
import time
import random

sleep_time = 20

def main():
    # Parse arguments
    data, output_path = parse_args()

    # Save a list of all the users in the workspace
    output = {"people": {}, "conversations": {}}
    output["people"] = get_users(data)
    save_output(output, output_path)

    for channel_id, channel_name in data["channels"].items():
        log(channel_name)
        output["conversations"][channel_id] = {
            "name": channel_name,
            "messages": get_all_messages(channel_id, data)
        }
        save_output(output, output_path)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    parser.add_argument("output_path", type=str)
    args = parser.parse_args()
    with open(args.data_path) as f:
        data = json.load(f)
    return data, args.output_path


def get_users(data):
    users = {}
    for channel_id in data["channels"] | data["conversations"]:
        params = {"channel": channel_id}
        response = slack_post("conversations.view", data, params=params)
        for user in response["users"]:
            users[user["id"]] = user
    return users


def get_all_messages(channel_id, data, reply_ts=None):
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
            check_replies(message, channel_id, data)
        messages += new_messages
        messages.sort(key=lambda x: x["ts"])
        page += 1
        last_message_ts = messages[0]["ts"]
    return messages


def get_messages_page(channel_id, data, latest_ts=None, reply_ts=None):
    path = "conversations.replies" if reply_ts else "conversations.history"
    params = {"channel": channel_id}
    if latest_ts: params["latest"] = latest_ts
    if reply_ts: params["ts"] = reply_ts
    messages = slack_post(path, data, params=params)["messages"]
    if reply_ts: messages.pop(0)
    return messages


def check_replies(message, channel_id, data):
    if message.get("reply_count", 0) > 0:
        message["replies"] = get_all_messages(channel_id, reply_ts=message["ts"], data=data)
    else:
        message["replies"] = []
    

def slack_request(method, url, data, params=None, indent=1):
    global sleep_time
    while True:
        response = requests.request(
            method,
            f"https://{data['workspace']}.slack.com/api/{url}",
            headers={"cookie": data["cookie"]},
            data={"token": data["token"]},
            params=params,
        )
        response.raise_for_status()
        if response.json().get("error") == "ratelimited":
            log(f"Ratelimited, sleeping for {sleep_time} seconds", indent=indent)
            time.sleep(sleep_time)
            sleep_time += 7
            continue
        time.sleep(random.uniform(0.25, 0.75))
        return response.json()


def slack_post(*args, **kwargs):
    return slack_request("POST", *args, **kwargs)


def slack_get(*args, **kwargs):
    return slack_request("GET", *args, **kwargs)


def log(message, indent=0):
    print(f"{'    ' * indent}{message}")


def save_output(output, output_path):
    os.makedirs(output_path, exist_ok=True)
    with open(f"{output_path}/slack.json", "w") as f:
        json.dump(output, f, indent=4)


if __name__ == "__main__":
    main()