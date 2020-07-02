import shutil
import requests
import json
import re
import argparse
from bs4 import BeautifulSoup
import os

parser = argparse.ArgumentParser()
parser.add_argument('--links', type=str)
parser.add_argument('--output', type=str)
cli_args = parser.parse_args()


def rreplace(s: str, old: str, new: str, occurrence: int):
    li = s.rsplit(old, occurrence)
    return new.join(li)


def get_page_config(url: str):
    page = requests.get(url)
    page.encoding = 'utf-8'
    soup = BeautifulSoup(page.content, 'html.parser')
    results = soup.find_all('script', string=lambda text: text and "folder" in text and "weblink_view" in text)
    json_config = results[0].string.replace('window.cloudSettings =', '')
    json_config = rreplace(json_config, ';', '', 1).replace('\\\"', '\'').replace('\\\\', '')
    json_config = re.sub(r'\\[a-zA-Z]', '', json_config)
    return json.loads(json_config, strict=False)


class O2D:
    def __init__(self, item: dict, host: str, base: str):
        self.name = item['name']
        self.weblink = item['weblink']
        self.host = host
        self.base = base

    def link(self):
        return self.host + self.weblink

    def dir(self):
        return self.weblink.replace(self.base, '').replace(self.name, '').replace('/', '', 1)

    def target(self):
        return self.weblink.replace(self.base, '').replace('/', '', 1)


def scan_folder(cfg: dict, url: str, keeper: list):
    if not url.endswith('/'):
        url = url + '/'
    download_host = cfg['dispatcher']['weblink_view'][0]['url']
    base_id = cfg['folders']['tree'][0]['list'][0]['weblink']
    folders = cfg['folders']['folder']['list']
    for item in folders:
        i_type = item['type']
        if i_type == 'file':
            keeper.append(O2D(item, download_host, base_id))
        elif i_type == 'folder':
            cfg = get_page_config(url + item['name'])
            scan_folder(cfg, url + item['name'], keeper)
        else:
            raise ValueError(i_type)


def download_file(url, target_file):
    with requests.get(url, stream=True) as r:
        with open(target_file, 'wb') as f:
            shutil.copyfileobj(r.raw, f)


def scan_and_download():
    output = cli_args.output
    if not os.path.exists(output):
        os.mkdir(output)
    with open(cli_args.links, 'r') as rf:
        for line in rf.readlines():
            if line and len(line) > 0:
                line = line.replace('\n', '')
                list_of_downloads = list()
                config = get_page_config(line)
                scan_folder(config, line, list_of_downloads)
                base_folder_name = config['folders']['tree'][0]['list'][0]['name']

                for a_file in list_of_downloads:
                    directory = os.path.join(output, base_folder_name, a_file.dir())
                    if not os.path.exists(directory):
                        os.makedirs(directory)
                    target = os.path.join(output, base_folder_name, a_file.target())
                    download_file(a_file.link(), target)


if __name__ == '__main__':
    scan_and_download()
