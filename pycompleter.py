from sublime import Region, INHIBIT_WORD_COMPLETIONS
import sublime_plugin
from threading import Timer
import sys
import importlib
import pycompleter.parso.parso as parso
import os.path

VERSION = "3.6"
PATHS = [
    "/usr/lib/python38.zip",
    "/usr/lib/python3.8",
    "/usr/lib/python3.8/lib-dynload",
    "/home/wibens/.local/lib/python3.8/site-packages",
    "/usr/local/lib/python3.8/dist-packages",
    "/usr/lib/python3/dist-packages",
    "/home/wibens/deepfield-bootstrap/pipedream/lib",
]


def recursive_dict(path, value):
    if len(path) > 1:
        return {path[0].value: ("Import", recursive_dict(path[1:], value))}
    elif len(path) == 1:
        return {path[0].value: value}


def generate_full_paths(path):
    for root in PATHS:
        for i in range(len(path), 0, -1):
            trypath = os.path.join(root, "/".join(path[:i])) + ".py"
            if os.path.isfile(trypath):
                yield trypath, path[i:]


class ParsoVisitor:
    def __init__(self, recursion=1):
        self.data = {}
        self.name = None
        self.current = self.data
        self.recursion = recursion
        self.stack = []

    def push(self, newcurrent):
        self.stack.append(self.current)
        self.current = newcurrent
        self.recursion -= 1

    def pop(self):
        self.current = self.stack.pop()
        self.recursion += 1

    def visit(self, node):
        nodetype = node.__class__.__name__
        getattr(self, "visit_" + nodetype, self.generic_visit)(node)

    def visit_Module(self, node):
        for child in node.children:
            self.visit(child)

    def visit_Class(self, node):
        subdict = {}
        self.current[node.name.value] = "Class", subdict
        self.push(subdict)
        for child in node.children:
            self.visit(child)
        self.pop()

    def visit_ImportName(self, node):
        for name, path in zip(node.get_defined_names(), node.get_paths()):
            path_merged = map(lambda x: x.value, path)
            path_merged = ".".join(path_merged)
            print("ImportName", name)
            if node.get_path_for_name(name) != path:
                value = "Import", self.import_parser(path)
                for i in path:
                    self.current[name.value] = "Import", recursive_dict(path[1:], value)
                    self.current[path_merged] = value
            else:
                self.current[name.value] = (
                    "Import",
                    self.import_parser(path),
                )

    def visit_ImportFrom(self, node):
        for name in node.get_defined_names():
            path = map(lambda x: x.value, node.get_path_for_name(name))
            path = ".".join(path)
            self.current[name.value] = (
                "Import" + path,
                self.import_parser(node.get_path_for_name(name)),
            )

    def visit_Function(self, node):
        def parse_params(p):
            params = "*" * p.star_count + p.name.value
            if p.default:
                return "[" + params + "]"
            return params

        params = map(parse_params, node.get_params())
        params = ",".join(params)
        self.current[node.name.value] = "(" + params + ")", None

    def visit_ExprStmt(self, node):
        print(node.get_rhs())
        for var in node.get_defined_names():
            self.current[var.value] = "Variable", None

    def visit_PythonNode(self, node):
        self.visit_Module(node)

    def generic_visit(self, node):
        print("Not parsed:", node)
        pass

    def import_parser(self, importpath):
        subdict = {}
        if self.recursion > 0:
            self.push(subdict)
            if importpath[0].value in sys.builtin_module_names:
                mod = importlib.import_module(importpath[0].value)
                for builtin in dir(mod):
                    self.current[builtin] = "builtin", None
            else:
                subdict = self.import_lib(importpath)
            self.pop()
        return subdict

    def import_lib(self, importpath):
        importpath = list(map(lambda x: x.value, importpath))
        print(importpath)
        filename, subtree = next(generate_full_paths(importpath), (None, None))
        if filename:
            print("Should scan ", filename, subtree)
            filetree = ast_parser(filename, None, False)
            for s in subtree:
                filetree = filetree[s]
            return filetree
        else:
            print("Error import", importpath)


def ast_parser(filename, source=None, recurse=True):
    print(__file__)
    if source is None:
        with open(filename, "r") as fn:
            source = fn.read()
    tree = parso.parse(source, path=filename, version=VERSION, cache=True)
    visitor = ParsoVisitor(recursion=1 * recurse)
    visitor.visit(tree)
    return visitor.data


class pycompleterListener(sublime_plugin.EventListener):
    value = 5

    def __init__(self):
        self.errors = {}
        self.popuptimer = Timer(0.3, lambda: None)
        self.completions = {}

    def build_matches(self, view):
        viewdata = view.substr(Region(0, view.size()))
        filename = view.file_name() or "-"

        data = ast_parser(filename, viewdata)
        # print(data)
        return data

    @staticmethod
    def sublime_completions(data, prefix):
        r = []
        for k, (v, subdict) in data.items():
            if k.startswith(prefix):
                r.append(["{}\t{}".format(k, v), k])
        return sorted(r)

    def on_query_completions(self, view, prefix, locations):
        print("I get called: {} / {}".format(prefix, locations))
        for location in locations:
            path = []
            i = location - len(prefix)
            while i > 1:
                if view.substr(Region(i - 1, i)) == ".":
                    prevword = view.word(i - 2)
                    path.insert(0, view.substr(prevword))
                    i = prevword.a
                else:
                    break

            matches = self.build_matches(view)
            print("matches")
            print(matches)
            if matches is None:
                return

            for item in path:
                matches = matches.get(item, (None, {}))[1]

            ret = self.sublime_completions(matches, prefix)
            return (ret, INHIBIT_WORD_COMPLETIONS)
