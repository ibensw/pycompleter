from sublime import Region, INHIBIT_WORD_COMPLETIONS
import sublime_plugin
import sys
import importlib
import pycompleter.parso.parso as parso
import os.path
from time import time


def recursive_dict(path, value):
    if len(path) > 1:
        return {path[0].value: ("Import", recursive_dict(path[1:], value))}
    elif len(path) == 1:
        return {path[0].value: value}


def generate_full_paths(path, searchpath):
    for root in searchpath:
        for i in range(len(path), 0, -1):
            trypath = os.path.join(root, "/".join(path[:i])) + ".py"
            if os.path.isfile(trypath):
                yield trypath, path[i:]
            trypath = os.path.join(root, "/".join(path[:i]), "__init__.py")
            if os.path.isfile(trypath):
                yield trypath, path[i:]


class ParsoVisitor:
    def __init__(self, recursion=1, version="3.6", searchpath=[], filename=None):
        self.data = {}
        self.name = None
        self.current = self.data
        self.recursion = recursion
        self.stack = []
        self.version = version
        self.searchpath = searchpath
        self.filename = filename

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
            if node.get_path_for_name(name) != path:
                value = "Import", self.import_parser(path)
                items = self.current.get(name.value, ("Import", {}))[1]
                items.update(recursive_dict(path[1:], value))
                self.current[name.value] = "Import", items
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
                "Import " + path,
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
        for var in node.get_defined_names():
            self.current[var.value] = "Variable", None

    def visit_PythonNode(self, node):
        self.visit_Module(node)

    def visit_IfStmt(self, node):
        self.visit_Module(node)

    def generic_visit(self, node):
        # print("Not parsed:", node)
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
        localpath = []
        if self.filename:
            localpath = [os.path.dirname(self.filename)]
        filename, subtree = next(
            generate_full_paths(importpath, localpath + self.searchpath), (None, None)
        )
        if filename:
            print("Will scan ", filename, subtree)
            filetree = ast_parser(filename, None, False, self.version, self.searchpath)
            for s in subtree:
                filetree = filetree.get(s, (None, {}))[1]
            return filetree
        else:
            print("Could not find import", importpath)


def ast_parser(filename, source=None, recurse=True, version="3.6", searchpath=[]):
    start = time()
    if source is None:
        with open(filename, "r") as fn:
            source = fn.read()
    tree = parso.parse(source, path=filename, version=version, cache=True)
    visitor = ParsoVisitor(
        recursion=1 * recurse, searchpath=searchpath, filename=filename
    )
    visitor.visit(tree)
    end = time()
    print("Parsing", filename, end - start)
    return visitor.data


class pycompleterListener(sublime_plugin.EventListener):
    def build_matches(self, view):
        viewdata = view.substr(Region(0, view.size()))
        filename = view.file_name()

        version = view.settings().get("pycompleter.version", "3.6")
        searchpath = view.settings().get("pycompleter.path", [])

        data = ast_parser(filename, viewdata, version=version, searchpath=searchpath)
        return data

    @staticmethod
    def sublime_completions(data, prefix):
        r = []
        for k, (v, subdict) in data.items():
            if k.startswith(prefix):
                r.append(["{}\t{}".format(k, v), k])
        return sorted(r)

    def on_query_completions(self, view, prefix, locations):
        for location in locations:
            if view.scope_name(location).split(" ", 1)[0] != "source.python":
                return

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
            if matches is None:
                return

            for item in path:
                matches = matches.get(item, (None, {}))[1]

            ret = self.sublime_completions(matches, prefix)
            return (ret, INHIBIT_WORD_COMPLETIONS)
