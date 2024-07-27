import requests
from dataclasses import dataclass


@dataclass
class EDIAPI:
    username: str
    password: str
    package_id: int

    def construct_auth(self):
        self.auth_string = (
            f"uid={self.username},o=EDI,dc=edirepository,dc=org",
            f"{self.password}",
        )

    def evaluate_package(self, xml_url: str) -> str:
        self.construct_auth()
        eval_endpoint = "https://pasta.lternet.edu/package/evaluate/eml"
        xml_data = requests.get(xml_url)
        xml_content = xml_data.content
        headers = {
            "Content-Type": "application/xml",
            "Authorization": f"Basic {self.auth_string}",
        }
        resp = requests.post(
            url=eval_endpoint,
            headers=headers,
            auth=self.auth_string,
            data=xml_content,
        )

        self.evaluate_transaction_id = resp.text
        return self.evaluate_transaction_id

    def evaluate_results(self):
        if self.evaluate_transaction_id is None:
            raise Exception("no transaction id found, submit a package for evaluation")

        evaluate_report_endpoint = f"https://pasta.lternet.edu/package/evaluate/report/eml/{self.evaluate_transaction_id}"
        resp = requests.get(
            url=evaluate_report_endpoint,
        )

        return resp.text

    def upload_package(self, xml_url: str):
        upload_endpoint = "https://pasta.lternet.edu/package/eml"
        headers = {"Content-Type": "application/xml"}
        resp = requests.post(url=upload_endpoint, data=xml_url, headers=headers)

        return resp.text

    def update_package(self, xml_url: str):
        upload_endpoint = "https://pasta.lternet.edu/package/eml"
        headers = {"Content-Type": "application/xml"}
        resp = requests.post(url=upload_endpoint, data=xml_url, headers=headers)

        return resp.text

    def list_revisions(self):
        revisions_list_endpoint = (
            f"https://pasta.lternet.edu/package/eml/edi/{self.package_id}?filter=newest"
        )

        resp = requests.get(url=revisions_list_endpoint)
        return resp.text
