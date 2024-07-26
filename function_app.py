from io import StringIO
import azure.functions as func
import logging
import os
from sqlalchemy import create_engine, Engine, over, text
import pandas as pd
from bs4 import BeautifulSoup
import requests
from azure.storage.blob import BlobServiceClient, ContainerClient, PublicAccess
from dataclasses import dataclass, field
from typing import Optional, Dict
import json

from sqlalchemy.sql.base import Options
from sqlalchemy.sql.lambdas import NonAnalyzedFunction


logger = logging.getLogger(__name__)
DB_NAME = os.getenv("DB_NAME") or "runiddb"
DB_HOST = os.getenv("DB_HOST") or "localhost"
DB_USER = os.getenv("DB_USER") or "emanuel"
DB_PASSWORD = os.getenv("DB_PASSWORD") or "superpassword"
DB_PORT = os.getenv("DB_PORT") or 5432

BASE_URLS = {
    "staging": "https://pasta-s.lternet.edu/",
    "development": "https://pasta-d.lternet.edu/",
    "production": "https://pasta.lternet.edu/",
}

EML_PATHS = {
    "dataset_name": "eml.dataset.datatable.entityName",
    "dataset_description": "eml.dataset.datatable.entityDescription",
    "csv_url": "eml.dataset.datatable.physical.distribution.online.url",
    "csv_size": "eml.dataset.dataTable.physical.size",
}


@dataclass
class EDIPipe:
    pkg_number: str
    az_blob_conn_str: str = field(repr=False)
    db_connection_string: str = field(repr=False)
    container_client: ContainerClient | None = None
    db_engine: Engine | None = None


def initialize_pipe(pipe: EDIPipe):
    """
    Initialize a pipe by checking if a corresponding blob structure exists, if not create it.
    Initialization also creates a connection to the database given the connection string. The
    fields `db_engine` and `container_client` are both populated after init is complete, for use
    in other functions.
    """
    # create blob connection
    blob_service_client = BlobServiceClient.from_connection_string(
        pipe.az_blob_conn_str
    )
    container_client = blob_service_client.get_container_client(pipe.pkg_number)
    if not container_client.exists():
        logging.info("container not found, creating from template...")
        container_client.create_container(public_access=PublicAccess.CONTAINER)
        init_files = ["xml/init.txt", "data/init.txt"]
        for file in init_files:
            container_client.upload_blob(file, b"")
        logging.info("creation successful")
    # create db connection
    db_engine = create_engine(pipe.db_connection_string)
    pipe.container_client = container_client
    pipe.db_engine = db_engine


def read_sql_from_file(file_name: str):
    with open(file_name, "r") as f:
        return f.read()


def read_sql_from_blob(blob_path: str): ...


def get_latest_data(db: Optional[Engine], query_statement: str):
    if db is None:
        raise Exception(
            "pipe db set to None, please initialize pipe with `initialize_pipe`"
        )
    else:
        with db.connect() as conn:
            data = pd.read_sql_query(query_statement, conn)
        return data


def upload_csv_to_blob(
    blob_prefix, blob_service_client, filename, data, overwrite=False
):
    blob_client = blob_service_client.get_blob_client(blob=f"data/{filename}.csv")
    csv_binary = StringIO()
    data.to_csv(csv_binary, index=False)
    csv_content = csv_binary.getvalue()
    blob_client.upload_blob(csv_content, overwrite=overwrite)
    return blob_client.url


def get_package_xmls(blob_service_client, sort=True):
    blob_list = list(blob_service_client.list_blobs(name_starts_with="xml/"))
    if len(blob_list) == 0:
        return None
    if sort:
        return sorted(blob_list, key=lambda x: x["last_modified"], reverse=True)
    return blob_list


def get_url_for_xml(blob_name, blob_service_client):
    blob_client = blob_service_client.get_blob_client(blob_name)
    return blob_client.url


def parse_xml_from_url(url: str):
    resp = requests.get(url)
    content = resp.content
    soup = BeautifulSoup(content, "lxml-xml")
    return soup


def update_package_id(xml, new_id):
    eml_tag = xml.find("eml:eml")
    if not eml_tag:
        raise Exception("unable to locate top level eml tag in xml file")

    eml_tag["packageId"] = new_id


def update_eml(eml: BeautifulSoup, kv: Dict[str, str]):
    for path, val in kv.items():
        node_path = path.split(".")
        current = eml
        for node in node_path:
            current = current.find(node)
            if current is None:
                break

        if current is not None:
            current.clear()
            current.append(val)


def update_package_id_tag(self) -> None:
    new_package_id = self.package_id_revision_increment()
    eml_tag = self.soup.find("eml:eml")
    if eml_tag:
        eml_tag["packageId"] = new_package_id


def increment_package_revision_number(id: str) -> str:
    split_id = id.split(".")
    revision = int(split_id[-1]) + 1
    split_id[-1] = str(revision)
    return ".".join(split_id)


def write_xml_to_blob(
    xml: BeautifulSoup, container_client: ContainerClient
) -> str | None:
    eml_tag = xml.find("eml:eml")
    if eml_tag is None:
        return None
    package_id = eml_tag.get("packageId")
    filename = f"xml/{package_id}.xml"
    blob_client = container_client.get_blob_client(filename)
    xml_content = str(xml)
    blob_client.upload_blob(xml_content, overwrite=True)

    return get_url_for_xml(filename, container_client)


app = func.FunctionApp()


@app.route(route="publishPackage", auth_level=func.AuthLevel.ANONYMOUS)
def publishPackage(req: func.HttpRequest) -> func.HttpResponse:
    package_number = req.params.get("package_number")
    sql_query_path = req.params.get("sqlPath")
    az_conn_string = os.environ["AZURE_BLOB_CONN_STRING"]
    db_conn_string = os.environ["DB_CONN_STRING"]

    if package_number is None:
        response_data = {
            "message": "the package id number is not valid",
            "package_number": package_number,
        }
        response_json = json.dumps(response_data)

        return func.HttpResponse(
            response_json, mimetype="application/json", status_code=400
        )

    if az_conn_string is None:
        response_data = {
            "message": "an azure connection string is needed",
        }
        response_json = json.dumps(response_data)

        return func.HttpResponse(
            response_json, mimetype="application/json", status_code=402
        )

    if db_conn_string is None:
        response_data = {
            "message": "a database connection string is needed",
        }
        response_json = json.dumps(response_data)

        return func.HttpResponse(
            response_json, mimetype="application/json", status_code=402
        )

    pipe = EDIPipe(package_number, az_conn_string, db_conn_string)
    initialize_pipe(pipe)

    q = read_sql_from_file("data-query.sql")
    data = get_latest_data(pipe.db_engine, q)
    new_url = upload_csv_to_blob(
        pipe.pkg_number, pipe.container_client, "genetics-data", data, overwrite=True
    )

    xmls = get_package_xmls(pipe.container_client, sort=True)
    xml_url = get_url_for_xml(xmls[0].name, pipe.container_client)
    xml_soup = parse_xml_from_url(xml_url)

    update_eml(xml_soup, {EML_PATHS["csv_url"]: new_url})

    response_data = {
        "message": "publish package execution complete",
        "package_number": package_number,
        "data_url": new_url,
        "xml_url": xml_url,
    }

    response_json = json.dumps(response_data)

    write_xml_to_blob(xml_soup, pipe.container_client)
    return func.HttpResponse(response_json, mimetype="application/json")


@app.route(route="listPackages", auth_level=func.AuthLevel.ANONYMOUS)
def listPackage(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("hello world\n")
