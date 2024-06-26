import typing as t
from enum import Enum


class RetrievedItem:
    def __init__(self):
        pass

    def format_for_prompt(self, display_level: t.Optional[Enum]) -> str:
        pass


class FileDisplayLevel(Enum):
    """
    Enum for the level of detail to display when showing a file.
    TODO: Add some kind of `importance` option where only the main classes/functions are shown.
    """
    FILE_ONLY = 1
    LINES_ONLY = 2
    FILE_AND_LINES = 3


class RetrievedFile(RetrievedItem):
    """Represents a file that was retrieved from the repository. May contain the whole file content or only a part of it."""
    def __init__(
            self,
            file_path: str,
            file_content: str = None,
            lang: str = "py",
            lines: t.List[t.Tuple[int, int]] = None,
        ):
        self.file_path = file_path
        self.lang = lang
        self.lines = lines
        self.file_content = file_content

    def format_for_prompt(self, display_level: FileDisplayLevel = FileDisplayLevel.FILE_AND_LINES) -> str:
        if display_level is None:
            raise ValueError("display_level must be provided.")
        if display_level != FileDisplayLevel.FILE_ONLY and self.lines is not None:
            sections = []
            for start, end in self.lines:
                section = self.file_content.split("\n")[(start-1):(end-1)]
                # Add line numbers
                num_digits = len(str(end))
                line_nums = [str(i).rjust(num_digits) for i in range(start, end)]
                section = [f"{num} |{line}" for num, line in zip(line_nums, section)]
                section = "\n".join(section)
                section = f"""
Here is a portion of {self.file_path} from line {start} to {end-1}:
```py
{section}
```
""".strip()
                sections.append(section)
            sections = "\n-----\n".join(sections)
            sections = f"\n-----\n{sections}\n-----\n"
        else:
            sections = ""
        if display_level != FileDisplayLevel.LINES_ONLY or self.lines is None:
            file_content = self.file_content.split("\n")
            start_line = 1
            end_line = len(file_content) + 1
            num_digits = len(str(end_line))
            line_nums = [str(i).rjust(num_digits) for i in range(start_line, end_line)]
            file_content = [f"{num} |{line}" for num, line in zip(line_nums, file_content)]
            file_content = "\n".join(file_content)
            file_content = f"Here is the full content of {self.file_path}:\n{file_content}"
            file_content = f"\n-----\n{file_content}\n-----\n"
        else:
            file_content = ""
        return f"{file_content}{sections}"

    def __str__(self):
        return f"RetrievedFile({self.file_path}, lines={self.lines})"
    
    def __repr__(self):
        return str(self)