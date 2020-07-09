import shutil
from abc import abstractmethod

import requests
import json
import re
import argparse
from bs4 import BeautifulSoup
import os
import sys

mail_cloud_marker = 'cloud.mail'
yandex_cloud_marker = 'yadi.sk'
yandex_api_fetch = 'https://yadi.sk/public/api/fetch-list'

parser = argparse.ArgumentParser()
parser.add_argument('--links', type=str)
parser.add_argument('--output', type=str)
cli_args = parser.parse_args()


def progress(count, total, status='', bar_len=60):
    filled_len = int(round(bar_len * count / float(total)))

    percents = round(100.0 * count / float(total), 1)
    bar = '=' * filled_len + '-' * (bar_len - filled_len)

    fmt = '[%s] %s%s ...%s' % (bar, percents, '%', status)
    print('\b' * len(fmt), end='')
    sys.stdout.write(fmt)
    sys.stdout.flush()


def rreplace(s: str, old: str, new: str, occurrence: int):
    li = s.rsplit(old, occurrence)
    return new.join(li)


def get_mail_page_config(url: str):
    page = requests.get(url)
    page.encoding = 'utf-8'
    soup = BeautifulSoup(page.content, 'html.parser')
    results = soup.find_all('script', string=lambda text: text and "folder" in text and "weblink_view" in text)
    json_config = results[0].string.replace('window.cloudSettings =', '')
    json_config = rreplace(json_config, ';', '', 1).replace('\\\"', '\'').replace('\\\\', '')
    json_config = re.sub(r'\\[a-zA-Z]', '', json_config)
    return json.loads(json_config, strict=False)


def get_yandex_page_config(url: str):
    page = requests.get(url)
    page.encoding = 'utf-8'
    soup = BeautifulSoup(page.content, 'html.parser')
    results = soup.find_all('script', id='store-prefetch')[0].string
    json_config = json.loads(results, strict=False)
    json_config['cookie'] = page.cookies
    json_config['base'] = next(filter(lambda res: res[1]['parent'] is None, json_config['resources'].items()))[1]
    return json_config


class O2D:
    @abstractmethod
    def get_name(self):
        pass

    @abstractmethod
    def link(self):
        pass

    @abstractmethod
    def dir(self):
        pass

    @abstractmethod
    def target(self):
        pass


class Y2D(O2D):
    def __init__(self, name, url_dir: str, url_full: str, host: str):
        self.name = name
        self.url_dir = url_dir
        self.url_full = url_full
        self.host = host

    def get_name(self):
        return self.name

    def link(self):
        return self.host + self.url_full

    def dir(self):
        return self.url_dir.replace("/", "", 1)

    def target(self):
        return self.url_full.replace("/", "", 1)


class M2D(O2D):
    def __init__(self, name: str, weblink: str, host: str, base: str):
        self.name = name
        self.weblink = weblink
        self.host = host
        self.base = base

    def get_name(self):
        return self.name

    def link(self):
        return self.host + self.weblink

    def dir(self):
        return self.weblink.replace(self.base, '').replace(self.name, '').replace('/', '', 1)

    def target(self):
        return self.weblink.replace(self.base, '').replace('/', '', 1)


def scan_mail_folder(cfg: dict, url: str, keeper: list):
    if not url.endswith('/'):
        url = url + '/'
    download_host = cfg['dispatcher']['weblink_view'][0]['url']
    tree_list = cfg['folders']['tree'][0]['list']
    if len(tree_list) > 0:
        def keep(item):
            keeper.append(
                M2D(item['name'], item['weblink'], download_host, cfg['folders']['tree'][0]['list'][0]['weblink']))

        iter_over_folders(cfg, keeper, url, keep)
    else:
        def keep(item):
            keeper.append(M2D(item['name'], item['weblink'] + '/' + item['name'], download_host, item['weblink']))

        iter_over_folders(cfg, keeper, url, keep)


def iter_over_folders(cfg: dict, keeper: list, url: str, keep: callable):
    for item in cfg['folders']['folder']['list']:
        i_type = item['type']
        if i_type == 'file':
            keep(item)
        elif i_type == 'folder':
            inner_url = url + item['name']
            cfg = get_mail_page_config(inner_url)
            scan_mail_folder(cfg, inner_url, keeper)
        else:
            raise ValueError(i_type)


def scan_yandex_folder(cfg: dict, url: str, keeper: list):
    if not url.endswith('/'):
        url = url + '/'
    payload = json.dumps({
        'hash': cfg['base']['hash'] + ":" + url,
        'sk': cfg['environment']['sk'],
        "offset": 0,
        "withSizes": True,
    })
    headers = {
        'Content-Type': 'text/plain'
    }
    output = requests.post(yandex_api_fetch, data=payload, headers=headers, cookies=cfg['cookie'])
    if output.status_code == 200:
        resources = json.loads(output.content)['resources']
        for item in resources:
            sub_url = url + item['name']
            if item['type'] != 'dir':
                keeper.append(Y2D(item['name'], url, sub_url, cfg['base']['meta']['short_url']))
            else:
                scan_yandex_folder(cfg, sub_url, keeper)


def download_file(url, target_file):
    with requests.get(url, stream=True) as r:
        with open(target_file, 'wb') as f:
            shutil.copyfileobj(r.raw, f)


def download_all(base_folder_name, list_of_downloads, output):
    last_filename = ''
    for index, a_file in enumerate(list_of_downloads):
        last_filename = a_file.get_name()
        progress(index, len(list_of_downloads), status=f"Loading {last_filename}")
        directory = os.path.join(output, base_folder_name, a_file.dir())
        if not os.path.exists(directory):
            os.makedirs(directory)
        target = os.path.join(output, base_folder_name, a_file.target())
        download_file(a_file.link(), target)
    progress(len(list_of_downloads), len(list_of_downloads), status=f"Loading {last_filename}")


def mail_cloud_download():
    def base_folder(cfg: dict):
        tree_list = cfg['folders']['tree'][0]['list']
        if len(tree_list) > 0:
            return cfg['folders']['tree'][0]['list'][0]['name']
        else:
            return cfg['state']['id'].split('/')[-1]

    def filter_line(line):
        return line and len(line) > 0 and mail_cloud_marker in line

    output = cli_args.output
    if not os.path.exists(output):
        os.mkdir(output)
    with open(cli_args.links, 'r') as rf:
        for line in rf.readlines():
            if filter_line(line):
                line = line.replace('\n', '')
                list_of_downloads = list()
                config = get_mail_page_config(line)
                scan_mail_folder(config, line, list_of_downloads)
                base_folder_name = base_folder(config)

                download_all(base_folder_name, list_of_downloads, output)


def yandex_cloud_download():
    def base_folder(cfg: dict):
        return cfg['base']['name']

    def filter_line(line):
        return line and len(line) > 0 and yandex_cloud_marker in line

    output = cli_args.output
    if not os.path.exists(output):
        os.mkdir(output)
    with open(cli_args.links, 'r') as rf:
        for line in rf.readlines():
            if filter_line(line):
                line = line.replace('\n', '')
                list_of_downloads = list()
                config = get_yandex_page_config(line)
                scan_yandex_folder(config, '', list_of_downloads)
                base_folder_name = base_folder(config)

                download_all(base_folder_name, list_of_downloads, output)


if __name__ == '__main__':
    mail_cloud_download()
    yandex_cloud_download()
