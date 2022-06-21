import arcpy
try:
    from ujson import loads, load
    from ujson import dumps, dump
except:
    from json import loads, load
    from json import dumps, dump
from os import path
from os.path import join, isdir
from os import mkdir
import requests
import logging
import time
import traceback

timestr = time.strftime("%Y%m%d-%H%M%S")
logs_dir = path.abspath(path.join(path.dirname(__file__), "..", "logs"))
if not path.isdir(logs_dir):
    mkdir(logs_dir)
logfile = join(logs_dir, "log-{}.txt".format(timestr))
logging.basicConfig(
    filename=logfile,
    format="%(asctime)s - %(levelname)-8s - %(message)s",
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S")

# Get the current project
aprx = arcpy.mp.ArcGISProject("CURRENT")
defaultGDB = aprx.defaultGeodatabase
# Manage the results layer 
fc_name = "Airbus_Results"
out_fc = join(defaultGDB, fc_name)

if not arcpy.Exists(defaultGDB):
    arcpy.CreateFileGDB_management(path.split(defaultGDB)[0], path.basename(defaultGDB))
if not arcpy.Exists(out_fc):
    sr = arcpy.SpatialReference(4326)
    arcpy.CreateFeatureclass_management(defaultGDB, fc_name, "POLYGON", spatial_reference = sr)
    arcpy.management.AddFields(
        out_fc,[["acquisitiondate", "TEXT", "acquisitiondate", 60, "", ""],
        ])

# Check for the active Map
try:
    m = aprx.listMaps(aprx.activeMap.name)[0]
    # Check for the results layer and load it if necessary
    layer_list = []
    for lyr in m.listLayers():
        layer_list.append(lyr.name)
    if not "Airbus_Results" in layer_list: 
        m.addDataFromPath(out_fc)
        # Set results layer symbology
        l = m.listLayers("Airbus_Results")[0]
        sym = l.symbology
        sym.renderer.symbol.color = {"RGB" : [0, 0, 0, 0]}
        sym.renderer.symbol.outlineColor = {"RGB" : [255, 0, 0, 100]}
        l.symbology = sym
except:
    tb = traceback.format_exc()
    logging.info("Exception while managing the Airbus_Results layer. Do you have an Active Map in this ArcGIS Pro Project? - traceback: " + tb)

def get_api_key():
    with open(path.abspath(path.join(path.dirname(__file__), "settings.json")), "r") as settings_file:
        data = settings_file.read()
    obj = loads(data)
    key = str(obj["apikey"])
    settings_file.close()        
    return key.strip()

def get_dl_dir():
    with open(path.abspath(path.join(path.dirname(__file__), "settings.json")), "r") as settings_file:
        data = settings_file.read()
    obj = loads(data)
    dl_dir = str(obj["download_dir"])
    settings_file.close()
    return dl_dir

def get_token(api_key):
    url = "https://authenticate.foundation.api.oneatlas.airbus.com/auth/realms/IDP/protocol/openid-connect/token"
    payload="client_id=IDP&grant_type=api_key&apikey=" + api_key
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.request("POST", url, headers=headers, data=payload)
    # TODO try except on HTTP403 (stale apikey)
    return loads(response.text)["access_token"]

def get_products_in_workspace(token):
    # Get user's One Atlas Data subscription details
    workspace_id = get_subscription_info(token)
    # Query the workspace for delivered products
    url = "https://search.foundation.api.oneatlas.airbus.com/api/v1/opensearch"
    querystring = {"itemsPerPage":100, "startPage":1, "sortBy": "-publicationDate", "workspace": workspace_id}
    headers = {"Cache-Control": "no-cache","Authorization": token, "Content-Type": "application/json"}
    response = requests.request("GET", url, headers=headers, params=querystring)
    products = []
    for feature in loads(response.text)["features"]:
        try:
            if ("properties" in feature) and ("acquisitionDate" in feature["properties"]) and ("processingLevel" in feature["properties"]) and ("productType" in feature["properties"])  and ("id" in feature["properties"]) and ("download" in feature["_links"]) and ("resourceId" in feature["_links"]["download"][1]):
                products.append(feature["properties"]["acquisitionDate"] + ", " 
                    + feature["properties"]["processingLevel"] + ", "
                    + feature["properties"]["productType"] + ", "
                    + feature["_links"]["download"][1]["resourceId"] 
                    + ", ID=" + feature["properties"]["id"])
        except:
            logging.info("get_products_in_workspace: exception during products.append. Has something changed in the OneAtlas Data API response?")
    return products

def get_subscription_info(token):
    url = "https://data.api.oneatlas.airbus.com/api/v1/me"
    payload={}
    headers = {"Authorization": token}
    my_info = requests.request("GET", url, headers=headers, data=payload)
    workspace_id = loads(my_info.text)["contract"]["workspaceId"]
    return workspace_id

def get_product_geometry(selected_product, token):
    workspace_id = get_subscription_info(token)
    # search the workspace
    url = "https://search.foundation.api.oneatlas.airbus.com/api/v1/opensearch"
    querystring = {"workspaceid":workspace_id, "id":selected_product}
    headers = {"Cache-Control": "no-cache","Authorization": token, "Content-Type": "application/json"}
    response = requests.request("GET", url, headers=headers, params=querystring)
    for feature in loads(response.text)["features"]:
        geometry = feature["geometry"]
    return dumps(geometry)

class ToolValidator(object):
    """Class for validating a tool's parameter values and controlling
    the behavior of the tool's dialog."""

    def __init__(self):
        """Setup arcpy and the list of tool parameters.""" 
        self.params = arcpy.GetParameterInfo()
        #self.params[1].enabled = False

    def initializeParameters(self): 
        """Refine the properties of a tool's parameters. This method is 
        called when the tool is opened."""
        self.params[1].enabled = False
        logging.info("==============Airbus OneAtlas Data Downloader tools script opened==============")
        oad_api_key = get_api_key()
        if oad_api_key == "" or " " in oad_api_key or oad_api_key == None:
            self.params[0].value = "Enter your valid OneAtlas Data API Key here"
            self.params[1].enabled = False
        else:
            self.params[0].value = oad_api_key
            self.params[5].value = "Bearer " + get_token(oad_api_key)
            self.params[1].enabled = True
            self.params[1].filter.list = get_products_in_workspace(self.params[5].value)
        dl_dir = get_dl_dir()
        if isdir(dl_dir):
            self.params[3].value = dl_dir
        else: 
            if dl_dir == "" or dl_dir == None or dl_dir == "Select directory for downloading":
                logging.info("initializeParameters - A valid download directory has not been specified.")
                self.params[3].value = "Select directory for downloading"
        return

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self):
        """Modify the values and properties of parameters before internal
        validation is performed. This method is called whenever a parameter
        has been changed."""
        logging.info("updateParameters - function called.")
        logging.info("updateParameters - self.params[1].filter.list: " + str(self.params[1].filter.list))
        self.params[5].enabled = False
        self.params[0].value == self.params[0].value.strip() 
        if self.params[0].value == "" or " " in self.params[0].value or self.params[0].value == None:
            self.params[0].value = "Enter your valid OneAtlas Data API Key here"
            self.params[1].enabled = False
            self.params[2].enabled = False
            self.params[4].enabled = False
        else:
            self.params[1].enabled = True
            self.params[2].enabled = True
            self.params[4].enabled = True
            self.params[5].value = "Bearer " + get_token(self.params[0].value)
            self.params[1].filter.list = get_products_in_workspace(self.params[5].value)

        # Get the geometry for selected product
        if self.params[2].value == False or self.params[2].value == None:
            if self.params[1].value is not None and "Enter your valid OneAtlas Data API Key here" not in self.params[1].filter.list[0]:
                selected_product = self.params[1].value.split("=",1)[1]
                geojsonpoly = str(get_product_geometry(selected_product, self.params[5].value))
                logging.info("updateParameters - geometry for product:" + self.params[1].value.split(",")[3] + ": " + geojsonpoly)
                # Delete any existing feature
                if int(arcpy.GetCount_management(out_fc)[0]) > 0:
                    arcpy.DeleteFeatures_management(out_fc)
                # Insert the geometry and ID from selected product    
                icur = arcpy.da.InsertCursor(out_fc, ["SHAPE@", "acquisitiondate"])
                newPoly = arcpy.AsShape(geojsonpoly)
                icur.insertRow([newPoly, self.params[1].value.split(",")[0]])
                del icur
                arcpy.RecalculateFeatureClassExtent_management(out_fc)

        elif self.params[2].value == True and "Enter your valid OneAtlas Data API Key here" not in self.params[1].filter.list[0]:
            # Delete any existing features
            if int(arcpy.GetCount_management(out_fc)[0]) > 0:
                arcpy.DeleteFeatures_management(out_fc)
            # Iterate over all products
            for item in self.params[1].filter.list:
                product = item.split("=",1)[1]                   
                geojsonpoly = str(get_product_geometry(product, self.params[5].value))
                logging.info("updateParameters - geometry for product:" + self.params[1].value.split(",")[3] + ": " + geojsonpoly)
                # Insert the geometry and ID from selected product    
                icur = arcpy.da.InsertCursor(out_fc, ["SHAPE@", "acquisitiondate"])
                newPoly = arcpy.AsShape(geojsonpoly)
                icur.insertRow([newPoly, item.split(",")[0]])
                del icur

        arcpy.RecalculateFeatureClassExtent_management(out_fc)
        desc = arcpy.Describe(out_fc)
        if len(aprx.listMaps()) > 0:
            aprx.activeView.camera.setExtent(desc.extent)
            aprx.activeView.camera.scale*= 1.20

        # update the settings json file with user's specified download directory         
        a_file = open(path.abspath(path.join(path.dirname(__file__), "settings.json")), "r")
        json_object = load(a_file)
        if isdir(str(self.params[3].value)):
            json_object["download_dir"] = str(self.params[3].value)
        else:
            json_object["download_dir"] = "Select directory for downloading"
        a_file = open(path.abspath(path.join(path.dirname(__file__), "settings.json")), "w")
        dump(json_object, a_file)
        a_file.close()

        # update the settings json file with user's API Key  
        a_file = open(path.abspath(path.join(path.dirname(__file__), "settings.json")), "r")
        json_object = load(a_file)
        json_object["apikey"] = str(self.params[0].value)
        a_file = open(path.abspath(path.join(path.dirname(__file__), "settings.json")), "w")
        dump(json_object, a_file)
        a_file.close()

        # Control visibility of the product selection parameter based on 'Select all products' status
        if self.params[0].value != "" and " " not in self.params[0].value and self.params[0].value != None:
            if self.params[2].value == True:
                self.params[1].enabled = False
            else:
                self.params[1].enabled = True

        return

    def updateMessages(self):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""

        # Make sure there is a product selected when 'Select all products' is unchecked 
        if not self.params[1].value and self.params[2].value == False:
            self.params[1].setErrorMessage("No product selection has been made.")

        return
