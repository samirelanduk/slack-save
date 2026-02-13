import argparse
import os
import json
import requests

def main():
    data_path, output_path = get_paths()

    with open(data_path) as f:
        data = json.load(f)
    os.makedirs(output_path, exist_ok=True)

    
    users = get_users(data)

    with open(f"{output_path}/slack.json", "w") as f:
        json.dump(users, f, indent=4)



def get_users(data):
    users = {}
    conversations_url = f"https://{data['workspace']}.slack.com/api/conversations.view"
    for channel_id in data["channels"] | data["conversations"]:
        response = slack_post(conversations_url, data, params={"channel": channel_id})
        for user in response["users"]:
            users[user["id"]] = user
    return users


def slack_request(method, url, data, params=None):
    response = requests.request(
        method,
        url,
        headers={"cookie": data["cookie"]},
        data={"token": data["token"]},
        params=params,
    )
    response.raise_for_status()
    return response.json()


def slack_post(*args, **kwargs):
    return slack_request("POST", *args, **kwargs)


def slack_get(*args, **kwargs):
    return slack_request("GET", *args, **kwargs)



def get_paths():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    parser.add_argument("output_path", type=str)
    args = parser.parse_args()
    return args.data_path, args.output_path


if __name__ == "__main__":
    main()