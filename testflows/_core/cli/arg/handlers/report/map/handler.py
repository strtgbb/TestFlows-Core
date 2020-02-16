# Copyright 2020 Vitaliy Zakaznikov (TestFlows Test Framework http://testflows.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import sys
import json
import time
import base64

from datetime import datetime

import testflows._core.cli.arg.type as argtype

from testflows._core import __version__
from testflows._core.cli.arg.common import epilog
from testflows._core.cli.arg.common import HelpFormatter
from testflows._core.flags import Flags, SKIP
from testflows._core.testtype import TestType
from testflows._core.cli.arg.handlers.handler import Handler as HandlerBase
from testflows._core.cli.arg.handlers.report.copyright import copyright
from testflows._core.transform.log.pipeline import ResultsLogPipeline
from testflows._core.transform.log.message import RawMap, RawNode
from testflows._core.utils.timefuncs import localfromtimestamp, strftimedelta

logo = '<img class="logo" src="data:image/png;base64,%(data)s" alt="logo"/>'
testflows = '<span class="testflows-logo"></span> [<span class="logo-test">Test</span><span class="logo-flows">Flows</span>]'
testflows_em = testflows.replace("[", "").replace("]", "")

template = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/5.15.0/d3.js">
</script>
<section class="clearfix">%(logo)s%(confidential)s%(copyright)s</section>

---
# Test Map Report
%(body)s
  
---
Generated by %(testflows)s Open-Source Test Framework

[<span class="logo-test">Test</span><span class="logo-flows">Flows</span>]: https://testflows.com
[ClickHouse]: https://clickhouse.yandex

<script>
window.onload = function() {
  window.chart = chart();
  window.tests = tests();
};
</script>
"""

cdir = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(cdir, "chart.css"), encoding="utf-8") as fd:
    chart_style = fd.read()

with open(os.path.join(cdir, "chart.js"), encoding="utf-8") as fd:
    chart_script = fd.read()

with open(os.path.join(cdir, "tests.js"), encoding="utf-8") as fd:
    tests_script = fd.read()

class Formatter:
    def format_logo(self, data):
        if not data["company"].get("logo"):
            return ""
        data = base64.b64encode(data["company"]["logo"]).decode("utf-8")
        return '\n<p>' + logo % {"data": data} + "</p>\n"

    def format_confidential(self, data):
        if not data["company"].get("confidential"):
            return ""
        return f'\n<p class="confidential">Document status - Confidential</p>\n'

    def format_copyright(self, data):
        if not data["company"].get("name"):
            return ""
        return (f'\n<p class="copyright">\n'
            f'{copyright(data["company"]["name"])}\n'
            "</p>\n")

    def format_metadata(self, data):
        metadata = data["metadata"]
        s = (
            "\n\n"
            f"||**Date**||{localfromtimestamp(metadata['date']):%b %d, %Y %-H:%M}||\n"
            f'||**Framework**||'
            f'{testflows} {metadata["version"]}||\n'
        )
        return s + "\n"

    def format_paths(self, data):
        s = '\n##Tests\n\n'

        def get_paths(paths):
            graph_paths = []

            def get_path(path):
                nodes = []
                links = []
                l = len(path)
                for i, step in enumerate(path):
                    nodes.append(step.uid)
                    if i + 1 < l:
                        links.append({"source": step.uid, "target": path[i + 1].uid})
                return {"nodes": nodes, "links": links}

            for test, path in paths.items():
                graph_paths.append({"test": test, "path": get_path(path)})

            return graph_paths

        s += '<div id="tests-list" class="with-border" style="padding: 15px; max-height: 30vh; overflow: auto;"></div>\n'
        s += '<script>\n'
        s += f'{tests_script % {"paths": json.dumps(get_paths(data["paths"]), indent=2)}}\n'
        s += '</script>\n'
        return s + "\n"

    def format_map(self, data):

        def make_node(nodes, maps):
            if not isinstance(maps, RawMap):
                maps = RawMap(*maps)

            node = RawNode(*maps.node)

            if node.uid not in nodes:
                nodes[node.uid] = {
                    "node": RawNode(*maps.node),
                    "nexts": [],
                    "ins": [],
                    "outs": []
                }
            return nodes[node.uid]

        def generate_nodes(nodes, maps):
            if not isinstance(maps, RawMap):
                maps = RawMap(*maps)

            node = make_node(nodes, maps)

            if maps.nexts:
                [nodes[node["node"].uid]["nexts"].append(generate_nodes(nodes, n)) for n in maps.nexts]
            if maps.ins:
                [nodes[node["node"].uid]["ins"].append(generate_nodes(nodes, n)) for n in maps.ins]
            if maps.outs:
                [nodes[node["node"].uid]["outs"].append(generate_nodes(nodes, n)) for n in maps.outs]

            return node

        def gather_links(nodes, gnodes):
            links = []
            for node in nodes.values():
                for n in node["nexts"]:
                    links.append({"source": node["node"].uid, "target": n["node"].uid, "type": "link"})
                for n in node["ins"]:
                    links.append({"source": node["node"].uid, "target": n["node"].uid, "type": "inner link"})
                for n in node["outs"]:
                    links.append({"source": n["node"].uid, "target": node["node"].uid, "type": "inner link"})

            for link in links:
                for node in gnodes:
                    children_links = node["children"]["links"]
                    children_nodes = set(node["children"]["nodes"])
                    for child in children_nodes:
                        if child == link["source"] or child == link["target"]:
                            if ((link["source"] in children_nodes or link["source"] == node["id"])
                                    and (link["target"] in children_nodes or link["target"] == node["id"])):
                                children_links.append(link)

            return links

        def gather_nodes(nodes):
            gnodes = []
            for node in nodes.values():
                gnodes.append({
                    "id": node["node"].uid,
                    "type": "unvisited",
                    "name": node["node"].name,
                    "module": node["node"].module,
                    "next": [n["node"].uid for n in node["nexts"]],
                    "children": {
                        "nodes": set(),
                        "links": []
                    }
                })

                def find_all_children(node, start, children):
                    if node["node"].uid in children:
                        return
                    if node is start:
                        return
                    children.add(node["node"].uid)
                    if node["ins"] or node["outs"]:
                        return
                    for n in node["nexts"]:
                        find_all_children(n, start, children)

                for n in node["ins"] + node["outs"]:
                    find_all_children(n, node, gnodes[-1]["children"]["nodes"])
                gnodes[-1]["children"]["nodes"] = list(gnodes[-1]["children"]["nodes"])

            return gnodes

        nodes = {}
        generate_nodes(nodes, data["map"])

        gnodes = gather_nodes(nodes)
        glinks = gather_links(nodes, gnodes)

        chart_nodes = json.dumps(gnodes, indent=2)
        chart_links = json.dumps(glinks, indent=2)

        s = (
            '\n##Map\n\n'
            '<style>\n'
            f'{chart_style}\n'
            '</style>\n'
            '<div><div id="map-chart"></div></div>\n'
            '<script>\n'
            f'{chart_script % {"nodes": chart_nodes, "links": chart_links}}\n'
            '</script>\n'
        )
        return s + "\n"

    def format(self, data):
        body = ""
        body += self.format_metadata(data)
        body += self.format_paths(data)
        body += self.format_map(data)
        return template.strip() % {
            "testflows": testflows,
            "logo": self.format_logo(data),
            "confidential": self.format_confidential(data),
            "copyright": self.format_copyright(data),
            "body": body}

class Handler(HandlerBase):
    @classmethod
    def add_command(cls, commands):
        parser = commands.add_parser("map", help="map report", epilog=epilog(),
            description="Generate map report.",
            formatter_class=HelpFormatter)

        parser.add_argument("input", metavar="input", type=argtype.file("r", bufsize=1, encoding="utf-8"),
                nargs="?", help="input log, default: stdin", default="-")
        parser.add_argument("output", metavar="output", type=argtype.file("w", bufsize=1, encoding="utf-8"),
                nargs="?", help='output file, default: stdout', default="-")
        parser.add_argument("--format", metavar="type", type=str,
            help="output format, default: md (Markdown)", choices=["md"], default="md")
        parser.add_argument("--copyright", metavar="name", help="add copyright notice", type=str)
        parser.add_argument("--confidential", help="mark as confidential", action="store_true")
        parser.add_argument("--logo", metavar="path", type=argtype.file("rb"),
                help='use logo image (.png)')

        parser.set_defaults(func=cls())

    def metadata(self):
        return {
            "date": time.time(),
            "version": __version__,
        }

    def company(self, args):
        d = {}
        if args.copyright:
            d["name"] = args.copyright
        if args.confidential:
            d["confidential"] = True
        if args.logo:
            d["logo"] = args.logo.read()
        return d

    def paths(self, results):
        d = {}
        tests = list(results["tests"].values())

        def get_path(test, idx):
            started = test["test"].started
            ended = started + test["result"].p_time
            path = []

            for t in tests[idx + 1:]:
                flags = Flags(t["test"].p_flags)
                if flags & SKIP and settings.show_skipped is False:
                    continue
                if t["test"].started > ended:
                    break
                if t["test"].p_id.startswith(test["test"].p_id):
                    if t["test"].node:
                        path.append(t["test"].node)

            return path

        for idx, name in enumerate(results["tests"]):
            test = results["tests"][name]
            flags = Flags(test["test"].p_flags)
            if flags & SKIP and settings.show_skipped is False:
                continue
            if test["test"].p_type < TestType.Test:
                continue
            d[name] = get_path(test, idx)

        return d

    def data(self, results, args):
        d = dict()
        d["metadata"] = self.metadata()
        d["company"] = self.company(args)
        d["map"] = list(results["tests"].values())[0]["test"].map
        d["paths"] = self.paths(results)
        return d

    def generate(self, formatter, results, args):
        output = args.output
        output.write(
            formatter.format(self.data(results, args))
        )
        output.write("\n")

    def handle(self, args):
        results = {}
        formatter = Formatter()
        ResultsLogPipeline(args.input, results).run()
        self.generate(formatter, results, args)
