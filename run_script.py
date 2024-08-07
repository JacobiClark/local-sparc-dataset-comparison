import os
import requests
import boto3
from pennsieve2.pennsieve import Pennsieve
from os.path import expanduser, join
from configparser import ConfigParser
import sys
import csv

PENNSIEVE_URL = "https://api.pennsieve.io"


def connect_pennsieve_client(account_name):
    """
    Connects to Pennsieve Python client to the Agent and returns the initialized Pennsieve object.
    """
    try:
        return Pennsieve(profile_name=account_name)
    except Exception as e:
        raise e


def get_profile_name_from_api_key(key):
    config = ConfigParser()
    userpath = expanduser("~")
    configpath = join(userpath, ".pennsieve", "config.ini")
    config.read(configpath)
    if "global" not in config:
        raise Exception("Profile has not been set")
    keyname = config["global"]["default_profile"]
    return config[keyname].get(key)


def get_access_token():
    """
    Creates a temporary access token for utilizing the Pennsieve API. Reads the api token and secret from the Pennsieve config.ini file.
    get cognito config
    """
    r = requests.get("https://api.pennsieve.io/authentication/cognito-config")
    r.raise_for_status()
    cognito_app_client_id = r.json()["tokenPool"]["appClientId"]
    cognito_region_name = r.json()["region"]
    cognito_idp_client = boto3.client("cognito-idp", region_name=cognito_region_name)
    login_response = cognito_idp_client.initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": get_profile_name_from_api_key("api_token"),
            "PASSWORD": get_profile_name_from_api_key("api_secret"),
        },
        ClientId=cognito_app_client_id,
    )
    cached_access_token = login_response["AuthenticationResult"]["AccessToken"]
    return cached_access_token


token = get_access_token()
print("Got access token")

user_account_name = input("What is your defaultBfAccount?")

print("Connecting to Pennsieve client...")
try:
    ps = connect_pennsieve_client(user_account_name)
    print("Connected to Pennsieve client.")
except Exception as e:
    print(f"Could not connect to the Pennsieve agent: {e}")
    sys.exit(1)


dataset_id = input("What is the dataset id you want to compare?")

try:
    ps.use_dataset(dataset_id)
    print(f"Using dataset {dataset_id}")
except Exception as e:
    print(f"Could not use dataset {dataset_id}: {e}")
    sys.exit(1)

user_path = input("Please enter the path to the source folder on your machine: ")

if not os.path.exists(user_path) and  not os.path.isdir(user_path):
    print(f"Path {user_path} does not exist or is not a directory")
    sys.exit(1)

path_children = os.listdir(user_path)


def create_request_headers(token):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

sds_compliant_folder_names = ["primary", "source", "derivative", "code", "docs", "protocol", "stimulus", "analysis"]
def get_sds_compliant_folders_package_ids(dataset_id):
    try:
        sds_compliant_folder_package_ids = {}
        headers = create_request_headers(token)
        r = requests.get(f"{PENNSIEVE_URL}/datasets/{dataset_id}", headers=headers)
        r.raise_for_status()
        response = r.json()
        dataset_root_children = response["children"]
        for child in dataset_root_children:
            if child["content"]["name"] in sds_compliant_folder_names:
                sds_compliant_folder_package_ids[child["content"]["name"]] = child["content"]["id"]
        return sds_compliant_folder_package_ids
    except Exception as e:
        print(f"Exception when calling API: {e}")
        sys.exit(1)


def get_packages_folders_and_files(package_children):
    folders = []
    files = []
    for child in package_children:
        if child["content"]["packageType"] == "Collection":
            folders.append(child["content"])
        else:
            files.append(child["content"])
    return folders, files


def get_package_children(package_id):
    try:
        headers = create_request_headers(token)
        r = requests.get(f"{PENNSIEVE_URL}/packages/{package_id}", headers=headers)
        r.raise_for_status()
        response = r.json()
        package_children = response["children"]
        return package_children
    except Exception as e:
        print(f"Exception when calling API: {e}")
        sys.exit(1)


sds_compliant_folder_packages_obj = get_sds_compliant_folders_package_ids(dataset_id)


def verify_local_folders_and_files_exist_on_pennsieve(
    local_path, pennsieve_package_id, recursivePath
):  
    # Step 1: Get the children of the Pennsieve package
    package_children = get_package_children(pennsieve_package_id)
    folders_on_pennsieve, files_on_pennsieve = get_packages_folders_and_files(
        package_children
    )

    # Step 1: Create a list of the names of the folders and files on Pennsieve
    folder_names_on_pennsieve = []
    file_names_on_pennsieve = []
    for folder in folders_on_pennsieve:
        folder_names_on_pennsieve.append(folder["name"])
    for file in files_on_pennsieve:
        file_names_on_pennsieve.append(file["name"])

    # Step 2: Get the children of the local path
    local_path_children = os.listdir(local_path)
    local_folders = []
    local_files = []
    empty_local_folders = []
    local_zero_kb_files = []
    for child in local_path_children:
        child_path = os.path.join(local_path, child)
        if os.path.isdir(child_path):
            if os.listdir(child_path) == []:
                empty_local_folders.append(child)
            else:
                local_folders.append(child)
        else:
            if os.path.getsize(child_path) == 0:
                local_zero_kb_files.append(child)
            else:
                local_files.append(child)
    folders_local_and_pennsieve = []
    # Step 3: Add local folders that are not on Pennsieve to a list
    for folder in local_folders:
        if folder not in folder_names_on_pennsieve:
            folders_in_local_dataset_but_not_on_pennsieve.append(
                f"{recursivePath}{folder}"
            )
        # If the folder is in both the local dataset and on Pennsieve, add it to a list
        else:
            for folder_on_pennsieve in folders_on_pennsieve:
                if folder_on_pennsieve["name"] == folder:
                    folders_local_and_pennsieve.append(folder_on_pennsieve)

    # Step 3 B: Add local empty folders that on Pennsieve to a list
    for folder in empty_local_folders:
        if folder in folder_names_on_pennsieve:
            empty_local_folders_on_pennsieve.append(f"{recursivePath}{folder}")

    # Step 4: Add local files that are not on Pennsieve to a list (excludes 0kb files)
    for file in local_files:
        if file not in file_names_on_pennsieve:
            files_in_local_dataset_but_not_on_pennsieve.append(f"{recursivePath}{file}")

    # Step 4 B: Add local 0kb files that are not on Pennsieve to a list
    for file in local_zero_kb_files:
        if file not in file_names_on_pennsieve:
            zero_kb_files_in_local_dataset_but_not_on_pennsieve.append(
                f"{recursivePath}{file}"
            )

    # Step 5: Add Pennsieve folders that are not on the local dataset to a list
    for folder in folder_names_on_pennsieve:
        if folder not in local_folders:
            folder_on_pennsieve_but_not_in_local_dataset.append(
                f"{recursivePath}{folder}"
            )

    # Step 6: Add Pennsieve files that are not on the local dataset to a list
    for file in file_names_on_pennsieve:
        if file not in local_files:
            file_on_pennsieve_but_not_in_local_dataset.append(f"{recursivePath}{file}")

    # Step 7: Recursively call this function on each folder in the local dataset that is on Pennsieve
    for folder in folders_local_and_pennsieve:
        local_folder_path_to_verify = os.path.join(local_path, folder["name"])
        verify_local_folders_and_files_exist_on_pennsieve(
            local_folder_path_to_verify,
            folder["id"],
            f"{recursivePath}{folder['name']}/",
        )

folders_in_local_dataset_but_not_on_pennsieve = []
files_in_local_dataset_but_not_on_pennsieve = []
zero_kb_files_in_local_dataset_but_not_on_pennsieve = []

folder_on_pennsieve_but_not_in_local_dataset = []
file_on_pennsieve_but_not_in_local_dataset = []
empty_local_folders_on_pennsieve = []

print("Starting function that checks for differences in local dataset and Pennsieve...")
print("This may take a whie for large datasets...")

# Iterate over all top-level folders in the Pennsieve dataset
for folder_name, folder_id in sds_compliant_folder_packages_obj.items():
    verify_local_folders_and_files_exist_on_pennsieve(os.path.join(user_path, folder_name), folder_id, f"{folder_name}/")

# Check if there are folders in the local dataset that do not exist on Pennsieve
if len(folders_in_local_dataset_but_not_on_pennsieve) != 0:
    # Print the count and list of such folders
    print(
        f"Number of folders in local dataset but not on Pennsieve: {len(folders_in_local_dataset_but_not_on_pennsieve)}"
    )
    for folder in folders_in_local_dataset_but_not_on_pennsieve:
        print(folder)
else:
    print("All folders in local dataset exist on Pennsieve")

# Check if there are files in the local dataset that do not exist on Pennsieve
if len(files_in_local_dataset_but_not_on_pennsieve) != 0:
    # Print the count and list of such files
    print(
        f"Number of files in local dataset but not on Pennsieve: {len(files_in_local_dataset_but_not_on_pennsieve)}"
    )
    for file in files_in_local_dataset_but_not_on_pennsieve:
        print(file)
else:
    print("All files in local dataset exist on Pennsieve")

# Check if there are folders on Pennsieve that do not exist in the local dataset
if len(folder_on_pennsieve_but_not_in_local_dataset) != 0:
    # Print the count and list of such folders
    print(
        f"Number of folders on Pennsieve but not in local dataset: {len(folder_on_pennsieve_but_not_in_local_dataset)}"
    )
    for folder in folder_on_pennsieve_but_not_in_local_dataset:
        print(folder)
else:
    print("All folders on Pennsieve exist in the local dataset")

# Check if there are files on Pennsieve that do not exist in the local dataset
if len(file_on_pennsieve_but_not_in_local_dataset) != 0:
    # Print the count and list of such files
    print(
        f"Number of files on Pennsieve but not in local dataset: {len(file_on_pennsieve_but_not_in_local_dataset)}"
    )
    for file in file_on_pennsieve_but_not_in_local_dataset:
        print(file)
else:
    print("All files on Pennsieve exist in the local dataset")

# Check if there are zero-kb files in the local dataset that do not exist on Pennsieve
if len(zero_kb_files_in_local_dataset_but_not_on_pennsieve) != 0:
    # Print the count and list of such zero-kb files
    print(
        f"Number of 0kb files in local dataset but not on Pennsieve: {len(zero_kb_files_in_local_dataset_but_not_on_pennsieve)}"
    )
    for file in zero_kb_files_in_local_dataset_but_not_on_pennsieve:
        print(file)
else:
    print("No 0kb files in local dataset but not on Pennsieve")

# Check if there are empty local folders on Pennsieve
if len(empty_local_folders_on_pennsieve) != 0:
    # Print the count and list of such empty folders
    print(
        f"Number of empty local folders on Pennsieve: {len(empty_local_folders_on_pennsieve)} # Note: These folders may not be empty on Pennsieve"
    )
    for folder in empty_local_folders_on_pennsieve:
        print(folder)
else:
    print("No empty local folders on Pennsieve")


def export_logs_to_csv():
    headers = ["Mismatch description", "Folder/file path"]
    with open("source-mismatch-logs.csv", mode="w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)

        # Write the logs to the CSV file
        logs = [
            (
                "Folder in local dataset but not on Pennsieve",
                folders_in_local_dataset_but_not_on_pennsieve,
            ),
            (
                "File in local dataset but not on Pennsieve",
                files_in_local_dataset_but_not_on_pennsieve,
            ),
            (
                "Folder on Pennsieve but not in local dataset",
                folder_on_pennsieve_but_not_in_local_dataset,
            ),
            (
                "File on Pennsieve but not in local dataset",
                file_on_pennsieve_but_not_in_local_dataset,
            ),
            (
                "0kb file in local dataset but not on Pennsieve",
                zero_kb_files_in_local_dataset_but_not_on_pennsieve,
            ),
            (
                "Empty local folder uploaded to Pennsieve",
                empty_local_folders_on_pennsieve,
            ),
        ]

        for log_type, log_data in logs:
            for item in log_data:
                writer.writerow([log_type, item])


# Call the export_logs_to_csv function at the end of your script to export the logs
try:
    export_logs_to_csv()
    print("Logs exported to source-mismatch-logs.csv")
except Exception as e:
    print(f"Could not export logs to CSV: {e}")
    sys.exit(1)