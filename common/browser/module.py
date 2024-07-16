import ast
from ast import iter_fields
import os
import typing as t
from collections import namedtuple
from . import CodeDisplayLevel, LineNumberMode

# Comments to exclude from the display.
EXCLUDE_COMMENTS = ["TODO", "FIXME"]

# Named tuple to represent a line index.
LineIdx = namedtuple("LineIdx", ["line", "idx"])



def is_assignment(node: ast.AST):
    """Check if a node is an assignment."""
    return isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign)

class SourceCode:
    def __init__(self, dataset_item: t.Dict[str, t.Any], modules, raw_files, dirs):
        self.dataset_item = dataset_item
        self.instance_id = dataset_item["instance_id"]
        self.modules: t.Dict[str, HighLevelModule] = modules
        self.raw_files: t.Dict[str, str] = raw_files
        self.dirs = dirs

    def get_dirs(self, prefix: str = None, max_depth: int = 0):
        if prefix is None:
            prefix = ""
        dirs = self.dirs
        if max_depth is not None:
            dirs = [d for d in dirs if d.count("/") <= max_depth]
        dirs = [d for d in dirs if d.startswith(prefix)]
        return dirs


class SourceFile:
    """Represents a source file."""
    def __init__(self, filename, content):
        self.filename = filename
        self.content = content
        self.lines = content.split("\n")
        self.stripped_lines = [line.strip() for line in self.lines]
        self.line_idxs = [LineIdx(line, idx) for idx, line in enumerate(self.lines)]
        self.stripped_lines_idxs = [LineIdx(line, idx) for idx, line in enumerate(self.stripped_lines)]
        self.line_padding = len(str(len(self.lines)))

    def parse_signature(self, node: ast.AST):
        start_line = node.lineno
        ending = ":"
        segment = self.stripped_lines_idxs[start_line-1:]
        idxes = []
        for l in segment:
            idxes.append(l.idx)
            if l.line.endswith(ending):
                break
        lo_idx = min(idxes)
        hi_idx = max(idxes)
        return "\n".join(self.lines[lo_idx:hi_idx+1]), lo_idx
    
    def parse_full(self, node: ast.AST):
        start_line = node.lineno
        end_line = node.end_lineno
        return "\n".join(self.lines[start_line-1:end_line]), (start_line-1)

    def parse_upper_comments(self, node: ast.AST):
        # Check for comments right above the node
        start_line = node.lineno
        if start_line <= 1:
            return None, None
        upper_segment = self.stripped_lines_idxs[:(start_line-1)]
        # Skip empty lines and decorators.
        upper_segment = [l for l in upper_segment if l.line != "" and not l.line.startswith("@")]
        if len(upper_segment) == 0:
            return None, None
        # If the last line is a comment, return contiguous comments
        idxs = []
        if upper_segment[-1].line.startswith("#"):
            # Find all the comments right above the node
            for l in reversed(upper_segment):
                if l.line.startswith("#"):
                    if any(comment in l.line for comment in EXCLUDE_COMMENTS):
                        continue
                    idxs.append(l.idx)
                else:
                    break
        # If the last line is a docstring, return contiguous docstrings.
        docstrings_tokens = ['"""', "'''"] if not is_assignment(node) else []
        starts_with_docstring = lambda line: any(line.startswith(token) for token in docstrings_tokens)
        ends_with_docstring = lambda line: any(line.endswith(token) for token in docstrings_tokens)
        is_only_docstring = lambda line: any(line == token for token in docstrings_tokens)
        if ends_with_docstring(upper_segment[-1].line):
            # Find all the docstrings right above the node
            last_line = True
            for l in reversed(upper_segment):
                idxs.append(l.idx)
                # Last line with just the tokens: continue parsing.
                if last_line and is_only_docstring(l.line):
                    last_line = False
                    continue
                last_line = False
                # Start of docstring: end
                if starts_with_docstring(l.line):
                    break
        if len(idxs) == 0:
            return None, None
        lo_idx = min(idxs)
        hi_idx = max(idxs)
        return "\n".join(self.lines[lo_idx:hi_idx+1]), lo_idx
    
    def parse_lower_comments(self, node: ast.AST):
        if isinstance(node, ast.Module):
            lower_segment = self.stripped_lines_idxs[0:]
        elif is_assignment(node):
            end_line = node.end_lineno
            lower_segment = self.stripped_lines_idxs[end_line:]
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            start_line = node.lineno
            end_line = node.end_lineno
            lower_segment = self.stripped_lines_idxs[start_line-1:end_line]
            # Skip up to ":". TODO: Find a better way to do this.
            signature_end = 0
            for i, l in enumerate(lower_segment):
                if l.line.endswith(":"):
                    signature_end = i
                    break
            lower_segment = lower_segment[signature_end+1:]
        else:
            raise NotImplementedError(f"Cannot parse lower comments for node {node}.")
        if len(lower_segment) == 0:
            return None, None
        idxs = []
        # If the first line is a comment, return contiguous comments
        if lower_segment[0].line.startswith("#") and not is_assignment(node):
            # Find all the comments right below the node
            for l in lower_segment:
                if l.line.startswith("#"):
                    if any(comment in l.line for comment in EXCLUDE_COMMENTS):
                        continue
                    idxs.append(l.idx)
                else:
                    break
        # If the first line is a docstring, return contiguous docstrings.
        docstrings_tokens = ['"""', "'''"]
        starts_with_docstring = lambda line: any(line.startswith(token) for token in docstrings_tokens)
        ends_with_docstring = lambda line: any(line.endswith(token) for token in docstrings_tokens)
        is_only_docstring = lambda line: any(line == token for token in docstrings_tokens)
        if starts_with_docstring(lower_segment[0].line):
            # Find all the docstrings right below the node
            first_line = True
            for l in lower_segment:
                idxs.append(l.idx)
                # First line with just the tokens: continue parsing.
                if first_line and is_only_docstring(l.line):
                    first_line = False
                    continue
                first_line = False
                # End of docstring: end
                if ends_with_docstring(l.line):
                    break
        if len(idxs) == 0:
            return None, None
        lo_idx = min(idxs)
        hi_idx = max(idxs)
        return "\n".join(self.lines[lo_idx:hi_idx+1]), lo_idx

    def display_content(self, content, starting_line, line_number_mode: LineNumberMode = LineNumberMode.ENABLED):
        if content is None:
            return ""
        line_num = starting_line + 1
        if isinstance(content, str):
            lines = content.split("\n")
        else:
            lines = content
        output = []
        for line in lines:
            if line.strip() == '7':
                print("Line 7")
                exit(0)
            if line_number_mode == LineNumberMode.ENABLED:
                line_num_str = str(line_num).rjust(self.line_padding)
                output.append(f"{line_num_str} |{line}")
            else:
                output.append(line)
            line_num += 1
        return "\n".join(output) + "\n"
    

    def find_line_num(self, char_idx: int):
        """Find the line number for a character index."""
        curr_idx = 0
        for l in self.line_idxs:
            curr_idx += len(l.line)
            if curr_idx >= char_idx:
                return l.idx

class HighLevelFunction:
    """Represents a top level class or methods"""
    def __init__(self, node: ast.FunctionDef, source_file: SourceFile, parent_class=None):
        self.node = node
        self.source_file = source_file
        self.parent_class = parent_class
        self.upper_comments, self.upper_comments_line = source_file.parse_upper_comments(node)
        self.lower_comments, self.lower_comments_line = source_file.parse_lower_comments(node)
        self.signature, self.signature_line = source_file.parse_signature(node)
        self.full, self.full_line = source_file.parse_full(node)
    
    def display(self, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED) -> str:
        signature = self.source_file.display_content(self.signature, self.signature_line, line_mode)
        if level == CodeDisplayLevel.SIGNATURE:
            return signature
        elif level in [CodeDisplayLevel.MINIMAL, CodeDisplayLevel.MODERATE]:
            upper = self.source_file.display_content(self.upper_comments, self.upper_comments_line, line_mode)
            signature = self.source_file.display_content(self.signature, self.signature_line, line_mode)
            lower = self.source_file.display_content(self.lower_comments, self.lower_comments_line, line_mode)
            return f"{upper}{signature}{lower}"
        elif level == CodeDisplayLevel.FULL:
            upper = self.source_file.display_content(self.upper_comments, self.upper_comments_line, line_mode)
            full = self.source_file.display_content(self.full, self.full_line, line_mode)
            return f"{upper}{full}"


class HighLevelAssignment:
    """Represents a top level or class constant assignment."""
    def __init__(self, node: t.Union[ast.Assign, ast.AnnAssign], source_file: SourceFile):
        self.node = node
        self.target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        self.source_file = source_file
        self.upper_comments, self.upper_comments_line = source_file.parse_upper_comments(node)
        self.lower_comments, self.lower_comments_line = source_file.parse_lower_comments(node)
        self.full, self.full_line = source_file.parse_full(node)

    def display(self, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED) -> str:
        full = self.source_file.display_content(self.full, self.full_line, line_mode)
        if level == CodeDisplayLevel.SIGNATURE:
            return full
        upper_comments = self.source_file.display_content(self.upper_comments, self.upper_comments_line, line_mode)
        lower_comments = self.source_file.display_content(self.lower_comments, self.lower_comments_line, line_mode)
        return f"{upper_comments}{full}{lower_comments}"


class HighLevelImport:
    """Represents a top level import"""
    def __init__(self, node: t.Union[ast.Import, ast.ImportFrom], source_file: SourceFile):
        self.node = node
        self.source_file = source_file
        self.full, self.full_line = source_file.parse_full(node)

    def display(self, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED) -> str:
        return self.source_file.display_content(self.full, self.full_line, line_mode)

class HighLevelClass:
    """Represents a top level class"""
    def __init__(self, node: ast.ClassDef, source_file: SourceFile):
        self.node = node
        self.source_file = source_file
        self.methods: t.Dict[str, HighLevelFunction] = {}
        self.constants: t.Dict[str, HighLevelAssignment] = {}
        self.ordering: t.List[t.Any] = []
        self.upper_comments, self.upper_comments_line = source_file.parse_upper_comments(node)
        self.lower_comments, self.lower_comments_line = source_file.parse_lower_comments(node)
        self.signature, self.signature_line = source_file.parse_signature(node)
        self.full, self.full_lines = source_file.parse_full(node)
    

    def add_method(self, node: ast.FunctionDef):
        # print(f"Adding method {node.name} to class {self.node.name}.")
        h = HighLevelFunction(node, self.source_file, parent_class=self.node.name)
        self.methods[node.name] = h
        self.ordering.append(h)

    def add_constant(self, node: t.Union[ast.Assign, ast.AnnAssign]):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        assert isinstance(target, ast.Name)
        # print(f"Adding constant {target.id} to class {self.node.name}.")
        h = HighLevelAssignment(node, self.source_file)
        self.constants[target.id] = h
        self.ordering.append(h)


    def display(self, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED):
        upper = self.source_file.display_content(self.upper_comments, self.upper_comments_line, line_mode)
        if level == CodeDisplayLevel.FULL:
            full = self.source_file.display_content(self.full, self.full_lines, line_mode)
            return f"{upper}{full}"
        class_signature = self.source_file.display_content(self.signature, self.signature_line, line_mode)
        lower = self.source_file.display_content(self.lower_comments, self.lower_comments_line, line_mode)  
        children = [child.display(level, line_mode) for child in self.ordering]
        children = "\n".join(children) + "\n"
        if level == CodeDisplayLevel.SIGNATURE:
            return f"{class_signature}{children}"
        if level == CodeDisplayLevel.MINIMAL:
            return f"{upper}{class_signature}{lower}"
        elif level == CodeDisplayLevel.MODERATE:
            return f"{upper}{class_signature}{lower}{children}"


class HighLevelModule:
    def __init__(self, filename, content):
        self.source_file = SourceFile(filename, content)
        self.functions: t.Dict[str, HighLevelFunction] = {}
        self.classes: t.Dict[str, HighLevelClass] = {}
        self.constants = {}
        self.imports = []
        self.ordering: t.List[t.Any] = []
        self.module_comments, self.module_comments_line = None, None

    def add_function(self, node: ast.FunctionDef):
        # print(f"Adding function {node.name}.")
        h = HighLevelFunction(node, self.source_file)
        self.functions[node.name] = h
        self.ordering.append(h)

    def add_class(self, node: ast.ClassDef):
        # print(f"Adding class {node.name}.")
        h = HighLevelClass(node, self.source_file)
        self.classes[node.name] = h
        self.ordering.append(h)

    def add_constant(self, node: t.Union[ast.Assign, ast.AnnAssign]):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        assert isinstance(target, ast.Name)
        # print(f"Adding constant {target.id}.")
        h = HighLevelAssignment(node, self.source_file)
        self.constants[target.id] = h
        self.ordering.append(h)

    def add_import(self, node: ast.Import):
        # print(f"Adding import: {node}")
        h = HighLevelImport(node, self.source_file)
        self.imports.append(h)
        self.ordering.append(h)

    def display(self, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED):
        if level == CodeDisplayLevel.FULL:
            return self.source_file.display_content(self.source_file.content, 0, line_mode)
        upper = self.source_file.display_content(self.module_comments, self.module_comments_line, line_mode)
        children = [child.display(level, line_mode) for child in self.ordering]
        children = "\n".join(children) + "\n"
        if level == CodeDisplayLevel.MINIMAL:
            return upper
        elif level == CodeDisplayLevel.SIGNATURE:
            return children
        elif level == CodeDisplayLevel.MODERATE:
            return f"{upper}{children}"
    
    def display_class(self, class_name, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED):
        if class_name not in self.classes:
            return None
        return self.classes[class_name].display(level, line_mode)
    
    def display_function(self, function_name, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED):
        if function_name not in self.functions:
            return None
        return self.functions[function_name].display(level, line_mode)
    
    def display_method(self, class_name, method_name, level: CodeDisplayLevel, line_mode: LineNumberMode = LineNumberMode.ENABLED):
        if class_name not in self.classes:
            return None
        if method_name not in self.classes[class_name].methods:
            return None
        return self.classes[class_name].methods[method_name].display(level, line_mode)
    


class HighLevelVisitor(ast.NodeVisitor):
    def __init__(self, filename, content):
        self.is_top_level = False
        self.current_class: t.Optional[HighLevelClass] = None
        self.filename = filename
        self.content = content
        self.top_level_module = HighLevelModule(filename, content)


    def custom_visit(self, node, top_level=False, parent_class=None):
        """Copied from real source code. Visit a node."""
        method = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method, self.custom_generic_visit)
        self.is_top_level = top_level
        self.current_class = parent_class
        return visitor(node)

    def custom_generic_visit(self, node, top_level=False, parent_class=None):
        """Copied from the real source code. Called if no explicit visitor function exists for a node."""
        for field, value in iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.custom_visit(item, top_level=top_level, parent_class=parent_class)
            elif isinstance(value, ast.AST):
                self.custom_visit(value, top_level=top_level, parent_class=parent_class)


    def visit_FunctionDef(self, node: ast.FunctionDef) -> t.Any:
        # print(f"Visiting function {node.name}")
        if not(self.is_top_level or self.current_class is not None):
            # Not relevant for us.
            self.custom_generic_visit(node)
            return
        if self.is_top_level:
            self.top_level_module.add_function(node)
        elif self.current_class is not None:
            self.current_class.add_method(node)
        self.custom_generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> t.Any:
        # print(f"Visiting class {node.name}")
        if not self.is_top_level:
            # Irrelevant for us.
            self.custom_generic_visit(node)
            return
        self.top_level_module.add_class(node)
        parent_class = self.top_level_module.classes[node.name]
        self.custom_generic_visit(node, parent_class=parent_class)

    def visit_Module(self, node: ast.Module) -> t.Any:
        # print("Visiting module")
        self.top_level_module.module_comments, self.top_level_module.module_comments_line = self.top_level_module.source_file.parse_lower_comments(node)
        self.custom_generic_visit(node, top_level=True)

    def visit_assignment(self, node: t.Union[ast.Assign, ast.AnnAssign]) -> t.Any:
        if not(self.is_top_level or self.current_class is not None):
            # Not relevant for us.
            self.custom_generic_visit(node)
            return
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if not isinstance(target, ast.Name):
            # Not relevant for us.
            self.custom_generic_visit(node)
            return
        if self.is_top_level:
            self.top_level_module.add_constant(node)
        elif self.current_class is not None:
            self.current_class.add_constant(node)
        self.custom_generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> t.Any:
        self.visit_assignment(node)
            
    def visit_AnnAssign(self, node: ast.AnnAssign) -> t.Any:
        self.visit_assignment(node)


    def visit_Import(self, node: ast.Import) -> t.Any:
        # print("Visiting import")
        if not self.is_top_level:
            # Not relevant for us.
            self.custom_generic_visit(node)
            return
        self.top_level_module.add_import(node)
        self.custom_generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> t.Any:
        # print("Visiting import from")
        if not self.is_top_level:
            # Not relevant for us.
            self.custom_generic_visit(node)
            return
        self.top_level_module.add_import(node)
        self.custom_generic_visit(node)


def build_module(filename) -> t.Optional[HighLevelModule]:
    try:
        with open(filename, "r") as file:
            content = file.read()
            tree = ast.parse(content)
            visitor = HighLevelVisitor(filename, content)
            visitor.visit(tree)
            return visitor.top_level_module
    except SyntaxError as e:
        print(f"Syntax error in file {filename}: {e}")
        return None