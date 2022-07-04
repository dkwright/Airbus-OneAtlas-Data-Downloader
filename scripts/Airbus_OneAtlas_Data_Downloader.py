from arcpy import AddMessage, GetParameterAsText
import requests
from os import path
from zipfile import ZipFile
try:
    from ujson import loads
except:
    from json import loads
import os
val = path.abspath(path.join(path.dirname(__file__), "..", "Parameter", "Config", "DEA.xml"))
def read_api_key():
    with open(path.abspath(path.join(path.dirname(__file__), "..", "arcgis", "settings.json")), "r") as settings_file:
        data = settings_file.read()
    obj = loads(data)
    api_key = str(obj["apikey"])
    settings_file.close()
    return api_key

def get_token(user_api_key):
    url = "https://authenticate.foundation.api.oneatlas.airbus.com/auth/realms/IDP/protocol/openid-connect/token"
    payload="client_id=IDP&grant_type=api_key&apikey=" + user_api_key
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.request("POST", url, headers=headers, data=payload)
    return loads(response.text)["access_token"]

def get_workspace_id(auth_header):
    url = "https://data.api.oneatlas.airbus.com/api/v1/me"
    payload={}
    headers = {"Authorization": auth_header}
    my_info = requests.request("GET", url, headers=headers, data=payload)
    return loads(my_info.text)["contract"]["workspaceId"]

# Get products available in the My Data workspace
def get_products_in_workspace(auth_header, workspace_id):
    url = "https://search.foundation.api.oneatlas.airbus.com/api/v1/opensearch"
    headers = {"Authorization": auth_header}
    querystring = {"itemsPerPage":100, "startPage":1, "sortBy": "-publicationDate", "workspace": workspace_id}
    headers = {"Cache-Control": "no-cache","Authorization": auth_header, "Content-Type": "application/json"}
    response = requests.request("GET", url, headers=headers, params=querystring)
    products = []
    for feature in loads(response.text)["features"]:
        products.append(feature["properties"]["id"] + "," 
            + feature["_links"]["download"][1]["href"] + ","
            + feature["_links"]["download"][1]["resourceId"])
    return products

def get_product_info(workspace_id, selected_product, auth_header):
    url = "https://search.foundation.api.oneatlas.airbus.com/api/v1/opensearch"
    querystring = {"workspaceid":workspace_id, "id":selected_product}
    headers = {"Cache-Control": "no-cache","Authorization": auth_header, "Content-Type": "application/json"}
    response = requests.request("GET", url, headers=headers, params=querystring)
    for feature in loads(response.text)["features"]:
        product_href = feature["_links"]["download"][1]["href"]
        product_resource_id = feature["_links"]["download"][1]["resourceId"]
    return product_href, product_resource_id

def download_product_stream(href, filename):
    AddMessage("Started downloading {0}".format(filename))
    global auth_header
    headers = {"Authorization": auth_header}
    with requests.get(href, stream=True, headers=headers) as r:
        r.raise_for_status()
        with open(path.join(download_dir_param, filename), "wb") as f:
            for chunk in r.iter_content(chunk_size=4096):
                f.write(chunk)
    f.close()
    AddMessage("Finished downloading {0}".format(filename))
    return

def extract_product(product_resource_id, download_dir):
    zf = ZipFile(path.join(download_dir, product_resource_id))
    AddMessage("Extracting product archive...")
    archive_base_name = path.splitext(product_resource_id)[0]
    archive_local_path = path.join(download_dir, archive_base_name)
    zf.extractall(archive_local_path)
    zf.close()
    AddMessage("Product extracted to: " + archive_local_path)
    return

if __name__ == "__main__":
    #Use this for debugging in the execution code
    #with open(path.abspath(path.join(path.dirname(__file__), "..", "logs", "processing-log.txt")), "w") as proc_log_file:
    #    proc_log_file.write("processing...")
    #    proc_log_file.close()

    AddMessage("Started processing.")

    api_key_param = GetParameterAsText(0)
    selected_product_param = GetParameterAsText(1)
    all_products_param = GetParameterAsText(2)
    download_dir_param = GetParameterAsText(3)
    extract_param = GetParameterAsText(4)
    token_param = GetParameterAsText(5)
    api_key = read_api_key()
    auth_header = "Bearer " + get_token(api_key)
    workspace_id = get_workspace_id(auth_header)

    if all_products_param == "false" or all_products_param == "":
        selected_product_param = selected_product_param.split("=",1)[1]
        AddMessage("Selected Product: " + selected_product_param)
        AddMessage("Download Directory: " + download_dir_param)
        product_href, product_resource_id = get_product_info(workspace_id, selected_product_param, auth_header)
        if not path.exists(path.join(download_dir_param, product_resource_id)):
            download_product_stream(product_href, product_resource_id)
        else:
            AddMessage("File {} already exists, skipping download.".format(path.join(download_dir_param, product_resource_id)))
        if extract_param == "true":
            extract_product(product_resource_id, download_dir_param)
    else:
        AddMessage("All products selected")
        AddMessage("Download Directory: " + download_dir_param)
        products_list = get_products_in_workspace(auth_header, workspace_id)
        num_products = len(products_list)
        i = 1
        for product in products_list:
            AddMessage("Handling product {} of {}".format(i, num_products))
            product_href, product_resource_id = get_product_info(workspace_id, product, auth_header)
            if not path.exists(path.join(download_dir_param, product_resource_id)):
                download_product_stream(product_href, product_resource_id)
            else:
                AddMessage("File {} already exists, skipping download.".format(path.join(download_dir_param, product_resource_id)))
            if extract_param == "true":
                extract_product(product_resource_id, download_dir_param)
            i += 1

    AddMessage("Finished processing.")